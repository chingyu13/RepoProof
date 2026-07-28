"""Inspect static analysis + evidence chunking outputs.

Usage (pick one):
    # 1) Print a one-shot summary
    python inspect_analysis.py data/try

    # 2) Drop into ipython with analysis / chunks in the namespace
    TARGET=data/try ipython -i inspect_analysis.py

Point TARGET at a project folder (not a single file), e.g. put sample
sources under data/try/.

Afterwards you can run:
    show(analysis["stats"])          # summary stats
    show(analysis["functions"][0])   # first extracted function
    show(chunks[3])                  # 4th evidence chunk (includes Code:)
    [c["title"] for c in chunks]     # all chunk titles
"""
import os
import sys
import json
from pathlib import Path

# Make `import app` work from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.analyzer import analyze_project      # noqa: E402
from app.knowledge import build_chunks        # noqa: E402

TARGET = Path(os.environ.get("TARGET") or (sys.argv[1] if len(sys.argv) > 1 else "data/try"))


def show(x):
    """Pretty-print a dict / list as JSON."""
    print(json.dumps(x, ensure_ascii=False, indent=2, default=str))


if not TARGET.exists():
    print(f"Not found: {TARGET}")
    print("Create a folder and copy source files into it, e.g.:")
    print(f"  mkdir -p {TARGET} && cp your_code.py {TARGET}/")
    sys.exit(1)

# Stage 1: static analysis  input = folder path, output = structured IR dict
analysis = analyze_project(TARGET)

# Stage 2: evidence chunks  input = analysis + snapshot id, output = chunk list
chunks = build_chunks(analysis, snapshot_id="local-test")

print("=" * 70)
print(f"analyze_project({TARGET})  →  keys: {list(analysis.keys())}")
print("=" * 70)
show(analysis["stats"])
print(f"\nfunctions={len(analysis['functions'])}  classes={len(analysis['classes'])}  "
      f"calls={len(analysis['calls'])}  notebooks={len(analysis['notebooks'])}")

print("\n" + "=" * 70)
print(f"build_chunks(analysis, 'local-test')  →  {len(chunks)} chunks")
print("=" * 70)
for c in chunks:
    print(f"  {c['id']:>4}  {c['kind']:<13} {(c['file'] or '-'):<18} {c['title']}")

print("\nAvailable: analysis, chunks")
print("Helpers:   show(analysis['functions'][0])   /   show(chunks[3])")
print("Code chunks: show(next(c for c in chunks if 'Code:\\n' in c['text']))")
