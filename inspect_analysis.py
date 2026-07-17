"""互動式檢視 static analysis + evidence chunking 兩個階段的輸出。

用法(擇一):
    # 1) 快速看一次印出來的摘要
    python inspect_analysis.py data/try

    # 2) 進 ipython 手動戳(analysis / chunks 會留在 namespace)
    TARGET=data/try ipython -i inspect_analysis.py

把要檢測的專案放進一個資料夾(例如 data/try/),路徑指到「資料夾」而不是單一檔案。
進去之後可用:
    show(analysis["stats"])          # 統計
    show(analysis["functions"][0])   # 第一個 function 抽出來長怎樣
    show(chunks[3])                  # build_chunks 的第 4 顆證據
    [c["title"] for c in chunks]     # 所有 chunk 的標題
"""
import os
import sys
import json
from pathlib import Path

# 讓 `import app` 找得到(從專案根目錄載入)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.analyzer import analyze_project      # noqa: E402
from app.knowledge import build_chunks        # noqa: E402

TARGET = Path(os.environ.get("TARGET") or (sys.argv[1] if len(sys.argv) > 1 else "data/try"))


def show(x):
    """好讀地印出 dict / list。"""
    print(json.dumps(x, ensure_ascii=False, indent=2, default=str))


if not TARGET.exists():
    print(f"找不到 {TARGET} — 先建資料夾並放入要檢測的檔案,例如:")
    print(f"  mkdir -p {TARGET} && cp your_code.py {TARGET}/")
    sys.exit(1)

# === 階段 1:靜態分析 ===  input = 資料夾路徑, output = 結構化事實 dict
analysis = analyze_project(TARGET)

# === 階段 2:證據切塊 ===  input = 上面的 analysis dict + snapshot 字串, output = chunk list
chunks = build_chunks(analysis, snapshot_id="local-test")

print("=" * 70)
print(f"analyze_project({TARGET})  →  keys: {list(analysis.keys())}")
print("=" * 70)
show(analysis["stats"])
print(f"\nfunctions={len(analysis['functions'])}  classes={len(analysis['classes'])}  "
      f"calls={len(analysis['calls'])}  notebooks={len(analysis['notebooks'])}")

print("\n" + "=" * 70)
print(f"build_chunks(analysis, 'local-test')  →  {len(chunks)} 顆 chunk")
print("=" * 70)
for c in chunks:
    print(f"  {c['id']:>4}  {c['kind']:<13} {(c['file'] or '-'):<18} {c['title']}")

print("\n可用變數: analysis, chunks")
print("小工具:   show(analysis['functions'][0])   /   show(chunks[3])")
