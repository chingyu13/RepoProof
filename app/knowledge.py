"""Evidence chunks with provenance, plus BM25 keyword retrieval.

Embeddings are deliberately absent from the prototype: BM25 over
structured chunks is enough to ground MAQ generation, and it needs no
API key. Hybrid (dense + sparse) retrieval is a design-doc feature for
the integral version.
"""
import re

from rank_bm25 import BM25Okapi

MAX_CHUNKS = 800


def build_chunks(analysis: dict, snapshot_id: str) -> list[dict]:
    chunks: list[dict] = []

    def add(kind: str, title: str, text: str, file: str = "", start: int = 0, end: int = 0):
        chunks.append({
            "id": f"c{len(chunks)}",
            "kind": kind,
            "title": title,
            "text": text.strip(),
            "file": file,
            "start_line": start,
            "end_line": end,
            "snapshot": snapshot_id,
        })

    if analysis.get("readme"):
        add("readme", "README", analysis["readme"])

    if analysis.get("dependencies"):
        add("dependencies", "Declared dependencies",
            "The project declares these dependencies:\n" + "\n".join(analysis["dependencies"]))

    if analysis.get("files"):
        rows = []
        for entry in analysis["files"][:300]:
            rel, lang = entry if isinstance(entry, (list, tuple)) else (entry, "Python")
            rows.append(f"{rel}  [{lang}]")
        add("structure", "Project file structure",
            "Source files in the project (path [language]):\n" + "\n".join(rows))

    for rel, mods in list(analysis.get("file_imports", {}).items())[:150]:
        add("imports", f"Imports in {rel}",
            f"The module {rel} imports: {', '.join(mods)}", file=rel)

    for cls in analysis.get("classes", [])[:200]:
        text = (
            f"Class {cls['qualname']} in {cls['file']} "
            f"(lines {cls['start_line']}-{cls['end_line']}).\n"
            f"Bases: {', '.join(cls['bases']) or 'none'}. "
            f"Methods: {', '.join(cls['methods']) or 'none'}.\n"
            f"Docstring: {cls['docstring'] or '(none)'}"
        )
        add("class", f"Class {cls['qualname']}", text,
            file=cls["file"], start=cls["start_line"], end=cls["end_line"])

    for fn in analysis.get("functions", []):
        if len(chunks) >= MAX_CHUNKS:
            break
        text = (
            f"{'Async function' if fn['is_async'] else 'Function'} {fn['qualname']} "
            f"in {fn['file']} (lines {fn['start_line']}-{fn['end_line']}).\n"
            f"Parameters: {', '.join(fn['args']) or 'none'}.\n"
            f"Docstring: {fn['docstring'] or '(none)'}\n"
            f"Code:\n{fn['code']}"
        )
        add("function", f"Function {fn['qualname']} ({fn['file']})", text,
            file=fn["file"], start=fn["start_line"], end=fn["end_line"])

    # Jupyter notebook cells (one chunk per non-trivial cell)
    for nb in analysis.get("notebooks", []):
        for cell in nb["cells"]:
            if len(chunks) >= MAX_CHUNKS:
                break
            add("notebook_cell",
                f"{nb['file']} — cell {cell['index']} ({cell['type']}, {nb['language']})",
                f"Notebook {nb['file']}, cell {cell['index']} ({cell['type']}):\n{cell['source']}",
                file=nb["file"], start=cell["index"], end=cell["index"])

    # Generic source files (R, Java, JS, HTML, CSS, SQL, ...): split into line segments
    SEG_LINES = 60
    for f in analysis.get("other_files", []):
        if len(chunks) >= MAX_CHUNKS:
            break
        decls = f", declarations: {', '.join(f['declarations'])}" if f["declarations"] else ""
        lines = f["text"].splitlines()
        segments = [lines[i:i + SEG_LINES] for i in range(0, len(lines), SEG_LINES)][:4]
        for si, seg in enumerate(segments):
            start = si * SEG_LINES + 1
            end = min(start + SEG_LINES - 1, f["line_count"])
            add("source",
                f"{f['language']} file {f['file']} (lines {start}-{end})",
                f"{f['language']} file {f['file']} ({f['line_count']} lines{decls}).\n"
                f"Content (lines {start}-{end}):\n" + "\n".join(seg),
                file=f["file"], start=start, end=end)

    calls = analysis.get("calls", [])
    if calls:
        edges = "\n".join(f"{caller} -> {callee}" for caller, callee in calls[:400])
        add("callgraph", "Approximate call graph", "Approximate call edges (caller -> callee):\n" + edges)

    return chunks


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+|\d+")


def _tokenize(text: str) -> list[str]:
    tokens = []
    for tok in _TOKEN_RE.findall(text.lower()):
        tokens.append(tok)
        # split snake_case into parts too
        tokens.extend(p for p in tok.split("_") if len(p) > 2 and p != tok)
    return tokens


class ChunkIndex:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        corpus = [_tokenize(c["title"] + " " + c["text"]) for c in chunks] or [["empty"]]
        self.bm25 = BM25Okapi(corpus)

    def retrieve(self, query: str, k: int = 6, kinds: tuple[str, ...] = ()) -> list[dict]:
        scores = self.bm25.get_scores(_tokenize(query))
        ranked = sorted(range(len(self.chunks)), key=lambda i: scores[i], reverse=True)
        out = []
        for i in ranked:
            c = self.chunks[i]
            if kinds and c["kind"] not in kinds:
                continue
            out.append(c)
            if len(out) >= k:
                break
        return out
