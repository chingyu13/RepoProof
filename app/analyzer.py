"""Project analysis.

Python gets deep stdlib-`ast` analysis (functions, classes, imports, call
edges). All other supported source types get text-level analysis: file
contents with lightweight declaration extraction, and per-cell parsing for
Jupyter notebooks. The design doc's Tree-sitter path replaces the generic
layer when per-language AST support is needed.
"""
import ast
import json
import re
import shutil
from pathlib import Path

from .ingest import SKIP_DIRS

import os

# Per-FILE caps for evidence extraction (distinct from REPOPROOF_MAX_MB, which
# limits the total PROJECT size at intake). Files above these are skipped from
# analysis so huge data files or minified bundles don't flood LLM prompts.
MAX_FILE_BYTES = int(float(os.environ.get("REPOPROOF_MAX_FILE_MB", "1")) * 1_000_000)
# Notebooks embed base64 outputs/images, so raw size says little about code size;
# we only extract cell sources, so a generous cap is safe.
NOTEBOOK_MAX_BYTES = int(float(os.environ.get("REPOPROOF_MAX_NOTEBOOK_MB", "25")) * 1_000_000)
MAX_SNIPPET_CHARS = 1500
MAX_TEXT_CHARS = 6000
README_CAP = 12_000

LANG_BY_EXT = {
    ".py": "Python", ".ipynb": "Jupyter Notebook",
    ".r": "R", ".rmd": "R Markdown",
    ".java": "Java", ".kt": "Kotlin", ".scala": "Scala",
    ".js": "JavaScript", ".jsx": "JavaScript (React)", ".mjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript (React)", ".vue": "Vue",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS",
    ".sql": "SQL",
    ".c": "C", ".h": "C/C++ header", ".cpp": "C++", ".cc": "C++", ".hpp": "C++ header",
    ".cs": "C#", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".sh": "Shell", ".ps1": "PowerShell",
    ".swift": "Swift", ".jl": "Julia", ".lua": "Lua", ".pl": "Perl",
    ".m": "MATLAB/Objective-C", ".dart": "Dart",
    ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML", ".json": "JSON",
}

SKIP_FILENAMES = {"package-lock.json", "yarn.lock", "poetry.lock", "pnpm-lock.yaml"}

# Extensionless files the analyzer still uses for project context (README and
# dependency manifests are found by name in _find_readme / _find_dependencies).
KEEP_FILENAMES = {"dockerfile", "procfile", "makefile", "description", "gemfile", "rakefile", "license"}


def _is_source_file(p: Path) -> bool:
    """True if the analyzer would use this file (code/text or key metadata)."""
    name = p.name.lower()
    if p.suffix.lower() in LANG_BY_EXT:
        return True
    if name in KEEP_FILENAMES:
        return True
    return name.startswith("readme") or name.startswith("requirements")


def prune_non_source(root: Path) -> dict:
    """Delete non-programming files (images, media, fonts, archives, binaries)
    and noise directories from an extracted/cloned snapshot, keeping only what
    the analyzer reads. Runs AFTER the size gate. Returns a small summary."""
    removed = kept = removed_bytes = 0
    # remove noise directories wholesale (.git, node_modules, build, ...)
    for d in list(root.rglob("*")):
        if d.is_dir() and d.name in SKIP_DIRS:
            for f in d.rglob("*"):
                if f.is_file():
                    try:
                        removed_bytes += f.stat().st_size
                        removed += 1
                    except OSError:
                        pass
            shutil.rmtree(d, ignore_errors=True)
    # remove non-source files elsewhere
    for p in root.rglob("*"):
        if not p.is_file() or set(p.parts) & SKIP_DIRS:
            continue
        if _is_source_file(p):
            kept += 1
            continue
        try:
            removed_bytes += p.stat().st_size
            p.unlink()
            removed += 1
        except OSError:
            pass
    # drop directories left empty by the prune
    for p in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if p.is_dir():
            try:
                p.rmdir()
            except OSError:
                pass
    return {"removed": removed, "kept": kept, "removed_mb": round(removed_bytes / 1_000_000, 1)}

# crude but broadly useful declaration matcher for the generic languages
_DECL_RE = re.compile(
    r"^[ \t]*(?:export[ \t]+|public[ \t]+|private[ \t]+|protected[ \t]+|static[ \t]+|final[ \t]+|async[ \t]+)*"
    r"(?:function|def|class|interface|struct|enum|trait|impl|fn|func|sub|module|CREATE[ \t]+TABLE|create[ \t]+table)"
    r"[ \t]+[\"'`]?([A-Za-z_][\w.]*)",
    re.M,
)


def _iter_source_files(root: Path, skipped: list[str]):
    for p in sorted(root.rglob("*")):
        if not p.is_file() or set(p.parts) & SKIP_DIRS:
            continue
        ext = p.suffix.lower()
        if ext not in LANG_BY_EXT:
            continue
        if p.name in SKIP_FILENAMES or ".min." in p.name:
            continue
        limit = NOTEBOOK_MAX_BYTES if ext == ".ipynb" else MAX_FILE_BYTES
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size > limit:
            skipped.append(f"{p.relative_to(root)} ({size / 1_000_000:.1f} MB)")
            continue
        yield p, ext


class _Visitor(ast.NodeVisitor):
    def __init__(self, src: str, rel: str):
        self.src = src
        self.rel = rel
        self.stack: list[str] = []
        self.functions: list[dict] = []
        self.classes: list[dict] = []
        self.calls: list[tuple[str, str]] = []

    def visit_ClassDef(self, node: ast.ClassDef):
        qual = ".".join(self.stack + [node.name])
        self.classes.append({
            "name": node.name,
            "qualname": qual,
            "file": self.rel,
            "start_line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno),
            "bases": [ast.unparse(b) for b in node.bases],
            "docstring": (ast.get_docstring(node) or "")[:300],
            "methods": [n.name for n in node.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))],
        })
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def _visit_func(self, node):
        qual = ".".join(self.stack + [node.name])
        args = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
        snippet = ast.get_source_segment(self.src, node) or ""
        callees = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                fn = sub.func
                if isinstance(fn, ast.Name):
                    callees.add(fn.id)
                elif isinstance(fn, ast.Attribute):
                    callees.add(fn.attr)
        self.functions.append({
            "name": node.name,
            "qualname": qual,
            "file": self.rel,
            "start_line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno),
            "args": args,
            "docstring": (ast.get_docstring(node) or "")[:300],
            "code": snippet[:MAX_SNIPPET_CHARS],
            "is_async": isinstance(node, ast.AsyncFunctionDef),
        })
        for c in sorted(callees):
            self.calls.append((f"{self.rel}::{qual}", c))
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _visit_func
    visit_AsyncFunctionDef = _visit_func


def _imports_of(tree: ast.AST) -> list[str]:
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return sorted(mods)


def _analyze_python(path: Path, rel: str, src: str, out: dict) -> None:
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        out["errors"].append(f"{rel}: {exc.msg} (line {exc.lineno})")
        return
    visitor = _Visitor(src, rel)
    visitor.visit(tree)
    out["functions"].extend(visitor.functions)
    out["classes"].extend(visitor.classes)
    out["calls"].extend(visitor.calls)
    imports = _imports_of(tree)
    if imports:
        out["file_imports"][rel] = imports


def _analyze_notebook(rel: str, raw: str, out: dict) -> str | None:
    """Returns the notebook language label, or None if unparseable."""
    try:
        nb = json.loads(raw)
    except json.JSONDecodeError:
        out["errors"].append(f"{rel}: not valid notebook JSON")
        return None
    lang = (nb.get("metadata", {}).get("kernelspec", {}).get("language")
            or nb.get("metadata", {}).get("language_info", {}).get("name")
            or "unknown")
    cells = []
    for i, cell in enumerate(nb.get("cells", [])):
        src = cell.get("source", [])
        src = "".join(src) if isinstance(src, list) else str(src)
        if src.strip():
            cells.append({"index": i, "type": cell.get("cell_type", "code"),
                          "source": src[:2000]})
    out["notebooks"].append({"file": rel, "language": lang, "cells": cells[:200]})
    return f"Notebook ({lang})"


def _analyze_generic(rel: str, language: str, src: str, out: dict) -> None:
    lines = src.count("\n") + 1
    decls = _DECL_RE.findall(src)[:30]
    out["other_files"].append({
        "file": rel,
        "language": language,
        "line_count": lines,
        "declarations": decls,
        "text": src[:MAX_TEXT_CHARS],
    })


def _find_readme(root: Path) -> str | None:
    for p in sorted(root.iterdir()):
        if p.is_file() and p.name.lower().startswith("readme"):
            try:
                return p.read_text(encoding="utf-8", errors="replace")[:README_CAP]
            except OSError:
                return None
    return None


def _find_dependencies(root: Path) -> list[str]:
    deps: list[str] = []
    for req in root.glob("requirements*.txt"):
        try:
            for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.split("#")[0].strip()
                if line and not line.startswith("-"):
                    deps.append(line)
        except OSError:
            pass
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.S)
            if m:
                deps.extend(re.findall(r"[\"']([^\"']+)[\"']", m.group(1)))
        except OSError:
            pass
    package_json = root / "package.json"
    if package_json.is_file():
        try:
            pkg = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
            for section in ("dependencies", "devDependencies"):
                deps.extend(f"{k} {v} (npm)" for k, v in pkg.get(section, {}).items())
        except (OSError, json.JSONDecodeError):
            pass
    for desc in root.glob("DESCRIPTION"):  # R packages
        try:
            m = re.search(r"Imports:\s*(.+?)(?:\n\S|$)", desc.read_text(errors="replace"), re.S)
            if m:
                deps.extend(f"{d.strip()} (R)" for d in m.group(1).split(",") if d.strip())
        except OSError:
            pass
    return sorted(set(deps))


def analyze_project(root: Path) -> dict:
    """Build the structured analysis dict the knowledge layer consumes."""
    out = {
        "files": [],                # [(rel, language)]
        "functions": [], "classes": [], "calls": [],
        "file_imports": {},
        "notebooks": [],
        "other_files": [],
        "readme": _find_readme(root),
        "dependencies": _find_dependencies(root),
        "errors": [],
    }
    by_language: dict[str, int] = {}
    skipped: list[str] = []
    loc = 0

    for path, ext in _iter_source_files(root, skipped):
        rel = str(path.relative_to(root))
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        language = LANG_BY_EXT[ext]
        if ext == ".py":
            _analyze_python(path, rel, src, out)
        elif ext == ".ipynb":
            label = _analyze_notebook(rel, src, out)
            if label is None:
                continue
            language = label
        else:
            _analyze_generic(rel, language, src, out)
        out["files"].append((rel, language))
        by_language[language] = by_language.get(language, 0) + 1
        loc += src.count("\n") + 1

    out["stats"] = {
        "source_files": len(out["files"]),
        "files_by_language": dict(sorted(by_language.items(), key=lambda kv: -kv[1])),
        "python_files": by_language.get("Python", 0),
        "notebooks": len(out["notebooks"]),
        "functions": len(out["functions"]),
        "classes": len(out["classes"]),
        "lines_of_code": loc,
        "parse_errors": len(out["errors"]),
        "skipped_files": skipped[:10],
    }
    return out
