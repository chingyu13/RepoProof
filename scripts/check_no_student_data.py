#!/usr/bin/env python3
"""Refuse to commit student project data.

.gitignore keeps `data/` out of the repository, but `git add -f`, a stray path,
or a rename can still stage a real submission. Student code must never reach
GitHub — that is an ethics commitment, not just tidiness — so this fails the
commit instead of relying on the ignore file alone.

Install as a hook:

    ln -s ../../scripts/check_no_student_data.py .git/hooks/pre-commit
    chmod +x scripts/check_no_student_data.py

Run manually:

    python3 scripts/check_no_student_data.py
"""
from __future__ import annotations

import subprocess
import sys

# Paths that may never be committed. tests/fixtures/ is the sanctioned place for
# synthetic sample projects.
BLOCKED_PREFIXES = ("data/", "uploads/", "docs/ethics/")
BLOCKED_SUFFIXES = (".ipynb",)
ALLOWED_PREFIXES = ("tests/fixtures/",)


def staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True, text=True, check=False)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def offenders(paths: list[str]) -> list[str]:
    bad = []
    for path in paths:
        if path.startswith(ALLOWED_PREFIXES):
            continue
        if path.startswith(BLOCKED_PREFIXES) or path.endswith(BLOCKED_SUFFIXES):
            bad.append(path)
    return bad


def main() -> int:
    bad = offenders(staged_files())
    if not bad:
        return 0
    print("BLOCKED: these staged paths may contain student project data:\n", file=sys.stderr)
    for path in bad:
        print(f"  {path}", file=sys.stderr)
    print(
        "\nStudent submissions must never be committed. Unstage them with:\n"
        "  git restore --staged <path>\n"
        "Synthetic sample projects belong in tests/fixtures/.",
        file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
