"""Project intake: public GitHub clone or uploaded zip, with the 1 GB size gate."""
import hashlib
import io
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


def delete_project_files(root: Path) -> None:
    """Secure-enough deletion for the prototype: remove the working copy."""
    base = root
    if base.parent != config.PROJECTS_DIR and config.PROJECTS_DIR in base.parents:
        # extracted zips may nest one level down; remove the outer dir
        while base.parent != config.PROJECTS_DIR:
            base = base.parent
    shutil.rmtree(base, ignore_errors=True)
