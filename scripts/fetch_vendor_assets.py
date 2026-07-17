"""Download the CDN assets RepoProof uses into app/static/vendor/ so the app
works fully OFFLINE. Run this ONCE while you still have internet:

    python3 scripts/fetch_vendor_assets.py

Downloads:
  - JSZip 3.10.1 (folder-upload packing)
  - Oxanium woff2 fonts (400/500/600/700) + a local @font-face css

The HTML pages already prefer these local files and only fall back to the
CDN when they are missing.
"""
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "app" / "static" / "vendor"
FONTS = VENDOR / "fonts"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")  # woff2-capable UA


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main() -> None:
    VENDOR.mkdir(parents=True, exist_ok=True)
    FONTS.mkdir(parents=True, exist_ok=True)

    # 1. JSZip
    js = fetch("https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js")
    (VENDOR / "jszip.min.js").write_bytes(js)
    print(f"jszip.min.js            {len(js)/1024:.0f} KB")

    # 2. Oxanium fonts: parse Google's css2 response, keep the latin block per weight
    css = fetch("https://fonts.googleapis.com/css2?family=Oxanium:wght@400;500;600;700&display=swap").decode()
    out_css, seen = [], {}
    for block in css.split("@font-face")[1:]:
        m_w = re.search(r"font-weight:\s*(\d+)", block)
        m_u = re.search(r"url\((https://[^)]+\.woff2)\)", block)
        # 'U+0000' marks the basic-latin unicode-range block — the one we want
        if not m_w or not m_u or "U+0000" not in block or m_w.group(1) in seen:
            continue
        seen[m_w.group(1)] = m_u.group(1)
    for weight, url in sorted(seen.items()):
        data = fetch(url)
        fname = f"oxanium-{weight}.woff2"
        (FONTS / fname).write_bytes(data)
        out_css.append(
            "@font-face{font-family:'Oxanium';font-style:normal;font-weight:%s;"
            "font-display:swap;src:url('fonts/%s') format('woff2');}" % (weight, fname))
        print(f"oxanium-{weight}.woff2      {len(data)/1024:.0f} KB")
    (VENDOR / "oxanium.css").write_text("\n".join(out_css) + "\n")
    print("oxanium.css written —", len(seen), "weights")
    print("\nDone. The app now works without internet (fonts + folder upload).")


if __name__ == "__main__":
    main()
