"""Project analysis.

Python gets deep stdlib-`ast` analysis (functions, classes, module-level
constants/config, imports, call edges). Java/JavaScript/TypeScript/C/C++ get
the same function/class-level granularity via tree-sitter instead of `ast`
(_analyze_treesitter_structured): qualname, args, a Javadoc/JSDoc-style
leading comment as the docstring equivalent, a comment-stripped code
snippet, and call-graph edges (_ts_collect_calls) — so pilot-language
evidence chunks, including the "flow" chunks knowledge.py builds from
`calls`, are shaped just like Python's rather than a single raw-text dump.
Declaration-shaped text inside a comment or string literal is never
misread as a real declaration. If the grammar/parser is unavailable or a
file fails to parse, that file falls back to _analyze_generic() (regex-based
_DECL_RE declaration extraction). Every other, non-pilot source type always
uses that generic path, plus per-cell parsing for Jupyter notebooks.
Widening the tree-sitter pilot to more languages is the remaining
design-doc Tree-sitter work.
"""
import ast
import io
import json
import re
import shutil
import tokenize
from pathlib import Path

from .ingest import SKIP_DIRS

import os

try:
    from tree_sitter_language_pack import get_parser as _ts_get_parser
except ImportError:
    _ts_get_parser = None

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
ANALYSIS_VERSION = 2

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

# Crude but broadly useful declaration matcher for the generic (non-Python)
# languages. Reading it left to right: optional modifiers (export/public/
# static/async...), then a declaration keyword (function/def/class/fn/func/
# CREATE TABLE...), then the captured identifier. re.M makes ^ match at every
# line start, so findall() returns one name per declaration line.
_DECL_RE = re.compile(
    r"^[ \t]*(?:export[ \t]+|public[ \t]+|private[ \t]+|protected[ \t]+|static[ \t]+|final[ \t]+|async[ \t]+)*"
    r"(?:function|def|class|interface|struct|enum|trait|impl|fn|func|sub|module|CREATE[ \t]+TABLE|create[ \t]+table)"
    r"[ \t]+[\"'`]?([A-Za-z_][\w.]*)",
    re.M,
)


def _collapse_blank_lines(text: str) -> str:
    """Remove trailing whitespace without changing source line positions."""
    return re.sub(r"[ \t]+\n", "\n", text).rstrip()


def _strip_python_comments(src: str) -> str:
    """Remove Python comments without mistaking # inside a string for one.

    Docstrings are STRING tokens, so they remain available as useful context.
    """
    try:
        tokens = tokenize.generate_tokens(io.StringIO(src).readline)
        cleaned = tokenize.untokenize(tok for tok in tokens if tok.type != tokenize.COMMENT)
    except (tokenize.TokenError, IndentationError):
        # Syntax-invalid source is already excluded from AST evidence; leave it
        # intact here rather than risk corrupting a generic fallback.
        cleaned = src
    return _collapse_blank_lines(cleaned)


def _strip_generic_comments(src: str, *, hash_comments: bool = False,
                            dash_comments: bool = False, percent_comments: bool = False,
                            html_comments: bool = False) -> str:
    """Remove common code comments while preserving quoted strings and newlines.

    This deliberately handles the comment syntaxes used by the generic source
    formats. Newlines inside removed comments are retained so source locations
    still refer to the original file.
    """
    out: list[str] = []
    i = 0
    quote = ""
    while i < len(src):
        if quote:
            ch = src[i]
            out.append(ch)
            if ch == "\\" and i + 1 < len(src):
                out.append(src[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue

        if src.startswith("<!--", i) and html_comments:
            end = src.find("-->", i + 4)
            removed = src[i:] if end < 0 else src[i:end + 3]
            out.extend("\n" for ch in removed if ch == "\n")
            i += len(removed)
            continue
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            removed = src[i:] if end < 0 else src[i:end + 2]
            out.extend("\n" for ch in removed if ch == "\n")
            i += len(removed)
            continue
        line_marker = (
            src.startswith("//", i)
            or (dash_comments and src.startswith("--", i))
            or (hash_comments and src[i] == "#")
            or (percent_comments and src[i] == "%")
        )
        if line_marker:
            end = src.find("\n", i)
            if end < 0:
                break
            out.append("\n")
            i = end + 1
            continue
        if src[i] in ("'", '"', '`'):
            quote = src[i]
        out.append(src[i])
        i += 1
    return _collapse_blank_lines("".join(out))


def _strip_comments(src: str, ext: str = "", language: str = "") -> str:
    """Return code-oriented text with ordinary comments removed.

    Documentation deliberately remains only where the structured analyzers
    explicitly extract a Python docstring or adjacent Javadoc/JSDoc comment.
    """
    ext = ext.lower()
    lang = language.lower()
    if ext == ".py" or lang in {"python", "ipython"}:
        return _strip_python_comments(src)
    return _strip_generic_comments(
        src,
        hash_comments=ext in {".r", ".rmd", ".sh", ".ps1", ".yaml", ".yml", ".toml", ".pl", ".rb"}
        or lang in {"r", "shell", "powershell", "julia", "perl", "ruby", "yaml", "toml"},
        dash_comments=ext in {".sql", ".lua"} or lang in {"sql", "lua"},
        percent_comments=ext == ".m" or lang in {"matlab", "objective-c"},
        html_comments=ext in {".html", ".htm", ".vue"} or lang in {"html", "vue"},
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
    """Single-pass AST walker that records every class/function definition.

    The tricky part is `self.stack`: it holds the names of the enclosing
    class/function scopes at any moment during the walk. Pushing on entry and
    popping on exit gives each definition a dotted "qualname"
    (e.g. `TaskReport.summary` for a method, `outer.inner` for a nested
    function) without needing a second pass.
    """
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
        # get_source_segment slices the ORIGINAL text using the node's
        # line/column info — cheaper and more faithful than ast.unparse().
        snippet = _strip_python_comments(ast.get_source_segment(self.src, node) or "")
        # Approximate call graph: we only record the NAME being called, not the
        # resolved target. `foo()` -> "foo"; `obj.method()` -> "method" (the
        # receiver is ignored). Python is dynamic, so true resolution would
        # need type inference — name-level edges are good enough for evidence.
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

    # NodeVisitor dispatches by method name (`visit_<NodeType>`); aliasing both
    # def types to the same handler treats `def` and `async def` identically.
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


def _python_import_details(tree: ast.AST) -> list[dict]:
    """Full import records (vs. _imports_of's display-only top-level names):
    {"module": dotted path, "names": [(imported, local_alias)], "level": n}.
    `level` is the number of leading dots in a relative import
    (`from ..pkg import x` -> level=2) — needed to resolve the target file.
    A plain `import a.b` is recorded with names=[] (it binds the module, not
    symbols), which is all the import-graph edge needs."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append({"module": a.name, "names": [], "level": 0})
        elif isinstance(node, ast.ImportFrom):
            names = [(a.name, a.asname or a.name) for a in node.names if a.name != "*"]
            out.append({"module": node.module or "", "names": names, "level": node.level})
    return out


def _resolve_import_graph(out: dict) -> None:
    """Cross-file resolution: turn per-file Python import records into
    (1) `import_edges` — [src_file, dst_file, imported_names] limited to files
        that actually exist in THIS repo (stdlib/third-party imports resolve to
        nothing and are simply skipped), and
    (2) `imported_symbols` — {file: {local_name: [dst_file, original_name]}},
        a shallow symbol table that lets the call-graph builder follow
        `load_tasks()` in cli.py back to its definition in storage.py.
    Resolution is by module-path mapping only (src/storage.py <-> src.storage,
    pkg/__init__.py <-> pkg) — no type inference, so attribute calls through
    objects remain unresolved by design."""
    module_to_file: dict[str, str] = {}
    for entry in out["files"]:
        rel = entry[0] if isinstance(entry, (list, tuple)) else entry
        if not rel.endswith(".py"):
            continue
        parts = rel[:-3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            module_to_file[".".join(parts)] = rel
    # files may not be filled yet for the current walk order — caller invokes
    # this AFTER the walk, so python_imports is complete here.
    edges: list[list] = []
    symbols: dict[str, dict[str, list]] = {}
    for rel, imports in out.get("python_imports", {}).items():
        pkg_parts = rel[:-3].split("/")[:-1] if rel.endswith(".py") else []
        for imp in imports:
            if imp["level"]:  # relative import: climb `level-1` packages up
                base = pkg_parts[: len(pkg_parts) - (imp["level"] - 1)] if imp["level"] > 1 else pkg_parts
                module = ".".join(base + ([imp["module"]] if imp["module"] else []))
            else:
                module = imp["module"]
            dst = module_to_file.get(module)
            if dst is None and imp["names"]:
                # `from pkg import mod` where mod is itself a module file
                for name, alias in imp["names"]:
                    sub = module_to_file.get(f"{module}.{name}" if module else name)
                    if sub:
                        edges.append([rel, sub, [name]])
            if dst is None or dst == rel:
                continue
            edges.append([rel, dst, [n for n, _ in imp["names"]]])
            for name, alias in imp["names"]:
                symbols.setdefault(rel, {})[alias] = [dst, name]
    out["import_edges"] = edges
    out["imported_symbols"] = symbols


def _module_level_vars(tree: ast.Module, src: str, rel: str) -> list[dict]:
    """Top-level `NAME = ...` / `NAME: type = ...` statements — module-scope
    constants/config (schemas, topic lists, intervals, ...) that _Visitor
    never records since it only visits ClassDef/FunctionDef. Scanning
    tree.body directly (not ast.walk) keeps this to true module scope: an
    assignment inside a function body is already covered by that function's
    own code snippet, so recording it again here would just duplicate it."""
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        if not names:
            continue
        snippet = _strip_python_comments(ast.get_source_segment(src, node) or "")
        out.append({
            "names": names,
            "file": rel,
            "start_line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno),
            "code": snippet[:MAX_SNIPPET_CHARS],
        })
    return out


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
    out["module_vars"].extend(_module_level_vars(tree, src, rel))
    imports = _imports_of(tree)
    if imports:
        out["file_imports"][rel] = imports
    details = _python_import_details(tree)
    if details:
        out.setdefault("python_imports", {})[rel] = details


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
    python_notebook = str(lang).lower() in {"python", "python3", "ipython"}
    for i, cell in enumerate(nb.get("cells", [])):
        # Markdown is narrative rather than executable project evidence. It
        # can dominate a notebook upload, so only index non-empty code cells.
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", [])
        src = "".join(src) if isinstance(src, list) else str(src)
        src = _strip_comments(src, language=lang)
        if src.strip():
            cells.append({"index": i, "type": "code", "source": src.strip()[:2000]})
            if python_notebook:
                try:
                    tree = ast.parse(src)
                except SyntaxError:
                    continue
                visitor = _Visitor(src, rel)
                visitor.visit(tree)
                for item in visitor.functions + visitor.classes:
                    item["cell_index"] = i
                    item["start_line"] = i
                    item["end_line"] = i
                out["functions"].extend(visitor.functions)
                out["classes"].extend(visitor.classes)
                out["calls"].extend(visitor.calls)
    out["notebooks"].append({"file": rel, "language": lang, "cells": cells[:200]})
    return f"Notebook ({lang})"


# Pilot languages analyzed with tree-sitter instead of _DECL_RE: a real
# grammar-based parser can't be fooled by declaration-shaped text sitting
# inside a comment or a string literal, which regex can. Everything else
# still uses _DECL_RE below — widen this dict to extend the pilot.
_TS_LANG_BY_EXT = {
    ".java": "java",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
}
_TS_CLASS_TYPES = {
    "java": {"class_declaration", "interface_declaration", "enum_declaration"},
    "javascript": {"class_declaration"},
    "typescript": {"class_declaration", "interface_declaration"},
    "tsx": {"class_declaration", "interface_declaration"},
    "c": {"struct_specifier", "enum_specifier"},
    "cpp": {"class_specifier", "struct_specifier"},
}
_TS_FUNC_TYPES = {
    "java": {"method_declaration", "constructor_declaration"},
    "javascript": {"function_declaration", "method_definition"},
    "typescript": {"function_declaration", "method_definition"},
    "tsx": {"function_declaration", "method_definition"},
    "c": {"function_definition"},
    "cpp": {"function_definition"},
}
# Union of the two above, keyed the same way — used by the declarations-only
# fallback (_treesitter_declarations) when full structured parsing fails.
_TS_DECL_NODE_TYPES = {lang: _TS_CLASS_TYPES[lang] | _TS_FUNC_TYPES[lang] for lang in _TS_CLASS_TYPES}
# Call/constructor-invocation node types per grammar, for call-graph extraction
# (mirrors Python's _visit_func: only the callee NAME is recorded, not a
# resolved target — see _ts_call_target for how each shape reduces to a name).
_TS_CALL_TYPES = {
    "java": {"method_invocation", "object_creation_expression"},
    "javascript": {"call_expression", "new_expression"},
    "typescript": {"call_expression", "new_expression"},
    "tsx": {"call_expression", "new_expression"},
    "c": {"call_expression"},
    "cpp": {"call_expression", "new_expression"},
}
_ts_parser_cache: dict[str, object] = {}


def _ts_node_name(node, src_bytes: bytes) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        # C/C++ function_definition: the identifier is nested inside 'declarator'.
        decl = node.child_by_field_name("declarator")
        name_node = decl.child_by_field_name("declarator") if decl else None
    return src_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", "replace") if name_node else None


def _ts_leading_comment(node, src_bytes: bytes) -> str:
    """Docstring equivalent for non-Python languages: the Javadoc/JSDoc/plain
    comment block sitting directly above the declaration, if any (Python has
    `ast.get_docstring`; these grammars have no such built-in concept)."""
    parent = node.parent
    if parent is None:
        return ""
    siblings = parent.children
    idx = siblings.index(node)
    if idx == 0:
        return ""
    prev = siblings[idx - 1]
    # must be adjacent — no blank-line gap — or it's unrelated to this declaration
    if "comment" not in prev.type or node.start_point[0] - prev.end_point[0] > 1:
        return ""
    text = src_bytes[prev.start_byte:prev.end_byte].decode("utf-8", "replace")
    text = re.sub(r"^/\*+|\*/$", "", text.strip())
    text = re.sub(r"^//+", "", text.strip())
    lines = [ln.strip().lstrip("*").strip() for ln in text.splitlines()]
    return " ".join(ln for ln in lines if ln)[:300]


def _ts_strip_comments(node, src_bytes: bytes) -> str:
    """Node's own source text with nested `comment` nodes removed — mirrors
    ast.get_source_segment() for Python, which naturally excludes comments
    since they were never AST nodes to begin with."""
    text = bytearray(src_bytes[node.start_byte:node.end_byte])
    spans = []

    def collect(n):
        if "comment" in n.type:
            spans.append((n.start_byte, n.end_byte))
        else:
            for c in n.children:
                collect(c)

    collect(node)
    for start, end in sorted(spans, reverse=True):
        del text[start - node.start_byte:end - node.start_byte]
    result = text.decode("utf-8", "replace")
    result = re.sub(r"[ \t]+\n", "\n", result)          # trailing whitespace left behind
    result = re.sub(r"\n[ \t]*\n+", "\n", result)        # blank lines left behind
    return result.strip()


def _ts_leaves(node) -> list:
    if not node.children:
        return [node]
    out = []
    for c in node.children:
        out.extend(_ts_leaves(c))
    return out


def _ts_args(node, src_bytes: bytes) -> list[str]:
    params = node.child_by_field_name("parameters")
    if params is None:
        # C/C++: parameters live on the nested declarator, same as the name lookup above.
        decl = node.child_by_field_name("declarator")
        params = decl.child_by_field_name("parameters") if decl else None
    if params is None:
        return []
    args = []
    for p in params.named_children:
        idents = [n for n in _ts_leaves(p) if n.type == "identifier"]
        if idents:
            last = idents[-1]
            args.append(src_bytes[last.start_byte:last.end_byte].decode("utf-8", "replace"))
    return args


def _ts_call_target(node):
    """Return the child node whose text is the bare callee name for a
    call/constructor node, or None if the shape isn't recognized. Handles:
    Java `method_invocation` (field `name`) and `object_creation_expression`
    (field `type`); JS/TS/C/C++ `call_expression` (field `function`, which is
    either a plain identifier or a member/field access — in which case only
    the accessed member's name is used, receiver ignored) and `new_expression`
    (field `constructor`)."""
    for field in ("name", "type", "constructor"):
        target = node.child_by_field_name(field)
        if target is not None:
            return target
    fn = node.child_by_field_name("function")
    if fn is None:
        return None
    if fn.type in ("member_expression", "field_expression"):
        return fn.child_by_field_name("property") or fn.child_by_field_name("field")
    return fn


def _ts_collect_calls(node, call_types: set, src_bytes: bytes) -> list[str]:
    """All callee names found anywhere in node's subtree (like Python's
    `ast.walk(node)` inside _visit_func — nested functions' calls are swept
    up too, an existing approximation this mirrors rather than fixes)."""
    names = []

    def walk(n):
        if n.type in call_types:
            target = _ts_call_target(n)
            if target is not None:
                names.append(src_bytes[target.start_byte:target.end_byte].decode("utf-8", "replace"))
        for c in n.children:
            walk(c)

    walk(node)
    return names


def _analyze_treesitter_structured(rel: str, ts_lang: str, src: str, out: dict) -> bool:
    """Function/class-level analysis via tree-sitter, matching the shape
    _analyze_python() produces (qualname, docstring, args, code, start/end
    line) so pilot languages get the same evidence granularity as Python —
    one chunk per function/class — instead of a single raw-text dump.
    Returns False if the grammar/parser isn't available or the file fails to
    parse, so the caller falls back to _analyze_generic()."""
    if _ts_get_parser is None:
        return False
    parser = _ts_parser_cache.get(ts_lang)
    if parser is None:
        try:
            parser = _ts_get_parser(ts_lang)
        except Exception:
            return False
        _ts_parser_cache[ts_lang] = parser
    src_bytes = src.encode("utf-8", "replace")
    try:
        tree = parser.parse(src_bytes)
    except Exception:
        return False

    class_types = _TS_CLASS_TYPES[ts_lang]
    func_types = _TS_FUNC_TYPES[ts_lang]
    call_types = _TS_CALL_TYPES[ts_lang]
    stack: list[str] = []

    def walk(node):
        if node.type in class_types:
            name = _ts_node_name(node, src_bytes) or "?"
            out["classes"].append({
                "name": name,
                "qualname": ".".join(stack + [name]),
                "file": rel,
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "bases": [],
                "docstring": _ts_leading_comment(node, src_bytes),
                "methods": [],
            })
            stack.append(name)
            for c in node.children:
                walk(c)
            stack.pop()
            return
        if node.type in func_types:
            name = _ts_node_name(node, src_bytes) or "?"
            qual = ".".join(stack + [name])
            out["functions"].append({
                "name": name,
                "qualname": qual,
                "file": rel,
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "args": _ts_args(node, src_bytes),
                "docstring": _ts_leading_comment(node, src_bytes),
                "code": _ts_strip_comments(node, src_bytes)[:MAX_SNIPPET_CHARS],
                "is_async": False,
            })
            for callee in _ts_collect_calls(node, call_types, src_bytes):
                out["calls"].append((f"{rel}::{qual}", callee))
            stack.append(name)
            for c in node.children:
                walk(c)
            stack.pop()
            return
        for c in node.children:
            walk(c)

    walk(tree.root_node)
    return True


def _treesitter_declarations(src: str, ts_lang: str) -> list[str] | None:
    """Declaration names via tree-sitter. None if unavailable, so the caller
    falls back to _DECL_RE (e.g. grammar missing, or the file fails to parse)."""
    if _ts_get_parser is None:
        return None
    parser = _ts_parser_cache.get(ts_lang)
    if parser is None:
        try:
            parser = _ts_get_parser(ts_lang)
        except Exception:
            return None
        _ts_parser_cache[ts_lang] = parser
    src_bytes = src.encode("utf-8", "replace")
    try:
        tree = parser.parse(src_bytes)
    except Exception:
        return None
    wanted = _TS_DECL_NODE_TYPES[ts_lang]
    names: list[str] = []

    def walk(node):
        if node.type in wanted:
            name = _ts_node_name(node, src_bytes)
            if name:
                names.append(name)
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return names[:30]


def _analyze_generic(rel: str, ext: str, language: str, src: str, out: dict) -> None:
    lines = src.count("\n") + 1
    cleaned = _strip_comments(src, ext, language)
    # A comment-only file has no code evidence. It remains in the project
    # structure, but consumes neither chunk budget nor BM25 statistics.
    if not cleaned:
        return
    ts_lang = _TS_LANG_BY_EXT.get(ext)
    decls = _treesitter_declarations(cleaned, ts_lang) if ts_lang else None
    if decls is None:
        decls = _DECL_RE.findall(cleaned)[:30]
    out["other_files"].append({
        "file": rel,
        "language": language,
        "line_count": lines,
        "declarations": decls,
        "text": cleaned[:MAX_TEXT_CHARS],
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


# ---------------------------------------------------------------------------
# Parser plugin registry.
# A parser is `handler(rel, src, out) -> language_label | None`; it appends
# into the IR dict (see analyze_project docstring). Returning None means "this
# file could not be parsed — skip it". Extensions NOT in the registry fall
# through analyze_project's built-in ladder: tree-sitter pilot -> generic
# regex. To add a language properly, write a handler that fills the same IR
# keys (functions/classes/calls/...) and call register_parser(".ext", handler).
# ---------------------------------------------------------------------------

def _parse_python(rel: str, src: str, out: dict) -> str:
    _analyze_python(None, rel, src, out)
    return "Python"


def _parse_notebook(rel: str, src: str, out: dict) -> str | None:
    return _analyze_notebook(rel, src, out)


PARSER_REGISTRY: dict[str, object] = {
    ".py": _parse_python,
    ".ipynb": _parse_notebook,
}


def register_parser(ext: str, handler) -> None:
    """Plug in an additional language parser (see registry note above)."""
    PARSER_REGISTRY[ext.lower()] = handler


def analyze_project(root: Path) -> dict:
    """Build the intermediate representation (IR) the knowledge layer consumes.

    IR SCHEMA — every parser writes into this shared shape, which is what
    makes the downstream (chunking, retrieval, generation) language-agnostic:
      files            [(rel_path, language)]
      functions        [{name, qualname, file, start/end_line, args,
                         docstring, code, is_async}]
      classes          [{name, qualname, file, start/end_line, bases,
                         docstring, methods}]
      calls            [(caller "file::qualname", callee_name)] — name-level
      module_vars      [{names, file, start/end_line, code}]
      file_imports     {file: [top-level module names]} — display only
      python_imports   {file: [{module, names, level}]} — full records
      import_edges     [[src_file, dst_file, [names]]] — repo-internal only
      imported_symbols {file: {local_name: [dst_file, original_name]}}
      notebooks        [{file, language, cells}]
      other_files      [{file, language, line_count, declarations, text}]
      readme, dependencies, errors, stats
    """
    out = {
        "files": [],                # [(rel, language)]
        "functions": [], "classes": [], "calls": [], "module_vars": [],
        "file_imports": {},
        "python_imports": {},
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
        handler = PARSER_REGISTRY.get(ext)
        if handler is not None:
            label = handler(rel, src, out)
            if label is None:
                continue
            language = label
        else:
            ts_lang = _TS_LANG_BY_EXT.get(ext)
            if not (ts_lang and _analyze_treesitter_structured(rel, ts_lang, src, out)):
                _analyze_generic(rel, ext, language, src, out)
        out["files"].append((rel, language))
        by_language[language] = by_language.get(language, 0) + 1
        loc += src.count("\n") + 1

    # cross-file pass: needs the complete file list + import records
    _resolve_import_graph(out)

    out["stats"] = {
        "analysis_version": ANALYSIS_VERSION,
        "source_files": len(out["files"]),
        "files_by_language": dict(sorted(by_language.items(), key=lambda kv: -kv[1])),
        "python_files": by_language.get("Python", 0),
        "notebooks": len(out["notebooks"]),
        "functions": len(out["functions"]),
        "classes": len(out["classes"]),
        "module_vars": len(out["module_vars"]),
        "import_edges": len(out.get("import_edges", [])),
        "lines_of_code": loc,
        "parse_errors": len(out["errors"]),
        "skipped_files": skipped[:10],
    }
    return out
