"""Project intake: public GitHub clone or uploaded zip, with the 1 GB size gate."""
import hashlib
import io
import json
import re
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path

from . import config

GITHUB_URL_RE = re.compile(r"^https://github\.com/[\w.\-]+/[\w.\-]+?(\.git)?/?$")

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".tox", "dist", "build", ".idea", ".vscode", ".eggs",
}

RAW_CODE_EXTENSIONS = {
    ".py", ".ipynb", ".r", ".rmd", ".java", ".kt", ".scala", ".js", ".jsx", ".mjs",
    ".ts", ".tsx", ".vue", ".html", ".htm", ".css", ".scss", ".sql", ".c", ".h",
    ".cpp", ".cc", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".ps1",
    ".swift", ".jl", ".lua", ".pl", ".m", ".dart",
}
RAW_CONTEXT_NAMES = {
    "dockerfile", "procfile", "makefile", "gemfile", "rakefile", "requirements.txt",
    "pyproject.toml", "setup.py", "setup.cfg", "package.json", "composer.json", "runtime.txt",
    "pom.xml", "build.gradle", "build.gradle.kts", "cargo.toml", "go.mod",
}
RAW_SKIP_NAMES = {
    "package-lock.json", "yarn.lock", "poetry.lock", "pnpm-lock.yaml",
}
RAW_SKIP_DIRS = {".claude", "coverage"}


class IngestError(Exception):
    """User-facing intake failure."""


def _tree_size_mb(root: Path) -> float:
    total = 0
    for p in root.rglob("*"):
        if p.is_file() and not (set(p.parts) & SKIP_DIRS):
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total / 1_000_000


def _size_gate(root: Path) -> None:
    size_mb = _tree_size_mb(root)
    if size_mb > config.MAX_PROJECT_MB:
        shutil.rmtree(root, ignore_errors=True)
        raise IngestError(
            f"Project is {size_mb:,.0f} MB, over the {config.MAX_PROJECT_MB:,} MB limit. "
            f"Larger projects need the Pro tier (pending) — email {config.PRO_CONTACT} to discuss."
        )


def clone_github(url: str) -> tuple[Path, str, str]:
    """Shallow-clone a public GitHub repo. Returns (path, snapshot_id, project_name)."""
    url = url.strip()
    if not GITHUB_URL_RE.match(url):
        raise IngestError("Please paste a public GitHub repository URL like https://github.com/owner/repo")
    dest = config.PROJECTS_DIR / uuid.uuid4().hex
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            check=True, capture_output=True, text=True, timeout=600,
        )
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        detail = (exc.stderr or "").strip().splitlines()
        raise IngestError(
            "Could not clone the repository. Is it public and spelled correctly? "
            + (detail[-1] if detail else "")
        ) from exc
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise IngestError("Cloning timed out. The repository may be too large.") from exc

    sha = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    _size_gate(dest)
    name = url.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]
    return dest, sha[:12], name


def extract_upload(data: bytes, filename: str) -> tuple[Path, str, str]:
    """Extract an uploaded .zip archive. Returns (path, snapshot_id, project_name)."""
    if len(data) > config.MAX_PROJECT_MB * 1_000_000:
        raise IngestError(
            f"Upload is over the {config.MAX_PROJECT_MB:,} MB limit. "
            f"Larger projects need the Pro tier (pending) — email {config.PRO_CONTACT} to discuss."
        )
    checksum = hashlib.sha256(data).hexdigest()[:12]
    dest = config.PROJECTS_DIR / uuid.uuid4().hex
    dest.mkdir(parents=True)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            # "Zip-slip" guard: a malicious archive can contain entries like
            # ../../etc/passwd. resolve() normalizes those traversals; if the
            # normalized target escapes the extraction dir, reject the archive
            # BEFORE extracting anything.
            for member in zf.infolist():
                target = (dest / member.filename).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    raise IngestError("Archive contains unsafe paths and was rejected.")
            zf.extractall(dest)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise IngestError("Only .zip archives are supported.") from exc

    _size_gate(dest)
    # If the zip wraps everything in one folder, descend into it.
    entries = [p for p in dest.iterdir() if p.name != "__MACOSX"]
    root = entries[0] if len(entries) == 1 and entries[0].is_dir() else dest
    name = Path(filename).stem or "uploaded-project"
    return root, checksum, name


def _notebook_source(text: str) -> str:
    try:
        notebook = json.loads(text)
    except json.JSONDecodeError:
        return ""
    cells = []
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") not in {"code", "markdown"}:
            continue
        source = cell.get("source", [])
        cells.append(source if isinstance(source, str) else "".join(source))
    return "\n\n".join(cells)


def _raw_file_priority(path: Path, root: Path) -> int | None:
    relative = path.relative_to(root)
    name = path.name.lower()
    parts = {part.lower() for part in relative.parts}
    if parts & RAW_SKIP_DIRS or name in RAW_SKIP_NAMES or ".min." in name:
        return None
    if name == ".env" or name.startswith(".env.") or any(
        marker in name for marker in ("credential", "secret", ".pem", ".key")
    ):
        return None
    if name.startswith("readme") or name in RAW_CONTEXT_NAMES:
        return 0
    if path.suffix.lower() in RAW_CODE_EXTENSIONS:
        return 2 if any(part in {"test", "tests"} for part in parts) else 1
    return None


def raw_project_files(root: Path, max_chars: int) -> list[dict]:
    candidates = []
    for path in root.rglob("*"):
        if not path.is_file() or set(path.parts) & SKIP_DIRS:
            continue
        priority = _raw_file_priority(path, root)
        if priority is not None:
            candidates.append((priority, path))

    files = []
    total_chars = 0
    max_file_chars = max_chars // 2
    for _, path in sorted(candidates, key=lambda item: (item[0], item[1].as_posix())):
        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise IngestError(f"Could not read source file {path.name}: {exc}") from exc
        text = _notebook_source(raw_text) if path.suffix.lower() == ".ipynb" else raw_text
        if not text.strip() or len(text) > max_file_chars or total_chars + len(text) > max_chars:
            continue
        files.append({
            "id": f"f{len(files)}",
            "file": path.relative_to(root).as_posix(),
            "text": text,
        })
        total_chars += len(text)
    if not files:
        raise IngestError("No usable source files fit the GPT context limit.")
    return files


def delete_project_files(root: Path) -> None:
    base = root.resolve()
    projects_root = config.PROJECTS_DIR.resolve()
    if base == projects_root or projects_root not in base.parents:
        return
    while base.parent != projects_root:
        base = base.parent
    shutil.rmtree(base, ignore_errors=True)
