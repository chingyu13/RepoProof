"""Evidence chunks with provenance, plus BM25 keyword retrieval.

Embeddings are deliberately absent from the prototype: BM25 over
structured chunks is enough to ground MAQ generation, and it needs no
API key. Hybrid (dense + sparse) retrieval is a design-doc feature for
the integral version.

The raw (caller, callee) call graph is a flat, unordered edge list that
would otherwise leave "what's the high-level flow here" entirely up to the
LLM to reassemble at generation time. _build_call_flow() groups it into one
call tree per likely entry point — Python and the tree-sitter pilot
languages (Java/JS/TS/C/C++) alike, since analyzer.py now extracts calls for
both — so a "flow" chunk reads as an ordered trace instead of a bag of
edges. Both the grouped trees and the raw edge list are kept as separate
chunk kinds.
"""
import re

from rank_bm25 import BM25Okapi

MAX_CHUNKS = 800

# Domain lexicon for the Python data-engineering focus.  This is deliberately
# query-side expansion: source chunks keep their original identifiers, while a
# natural-language focus such as "data ingestion" can also find load_csv() or
# read_parquet().  Aliases are scored below the words the user actually wrote.
DATA_ENGINEERING_CONCEPTS = {
    "data_ingestion": {
        "triggers": ("data ingestion", "ingestion", "ingest", "extract load", "etl", "elt"),
        "aliases": ("ingest", "extract", "fetch", "download", "import", "read", "load", "source", "raw"),
    },
    "data_transformation": {
        "triggers": ("data transformation", "transformation", "transform", "data cleaning", "cleaning"),
        "aliases": ("transform", "clean", "normalize", "standardize", "enrich", "aggregate", "groupby", "join", "merge"),
    },
    "data_validation": {
        "triggers": ("data validation", "validation", "data quality", "quality check", "schema validation"),
        "aliases": ("validate", "validation", "check", "assert", "schema", "contract", "quality", "null", "duplicate"),
    },
    "data_storage": {
        "triggers": ("data storage", "storage", "data warehouse", "warehouse", "persist data"),
        "aliases": ("write", "save", "persist", "export", "parquet", "csv", "json", "database", "table", "warehouse"),
    },
    "orchestration": {
        "triggers": ("orchestration", "workflow orchestration", "data pipeline", "airflow", "dag", "scheduling"),
        "aliases": ("pipeline", "dag", "airflow", "schedule", "task", "orchestrate", "run", "retry"),
    },
}


def data_engineering_expansion(text: str) -> list[str]:
    """Return domain aliases for concepts explicitly present in a focus text.

    The original words are intentionally not rewritten or merged. Callers use
    this list as a lower-weighted second BM25 query, preserving exact matches
    while making an assignment description more useful for retrieval.
    """
    normalized = " ".join(_tokenize(text))
    terms: list[str] = []
    for concept in DATA_ENGINEERING_CONCEPTS.values():
        if any(trigger in normalized for trigger in concept["triggers"]):
            terms.extend(concept["aliases"])
    return list(dict.fromkeys(terms))


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

    # Repo-internal import graph (which file depends on which) — resolved by
    # analyzer._resolve_import_graph, so stdlib/third-party edges never appear.
    import_edges = analysis.get("import_edges") or []
    if import_edges:
        rows = []
        for src, dst, names in import_edges[:200]:
            what = f" ({', '.join(names)})" if names else ""
            rows.append(f"{src} -> {dst}{what}")
        add("import_graph", "Internal import graph",
            "Repo-internal import dependencies (importer -> imported file (symbols)):\n"
            + "\n".join(rows))

    for mv in analysis.get("module_vars", [])[:200]:
        names = ", ".join(mv["names"])
        text = (
            f"Module-level constant(s) {names} in {mv['file']} "
            f"(lines {mv['start_line']}-{mv['end_line']}).\nCode:\n{mv['code']}"
        )
        add("module_var", f"Constant {names} ({mv['file']})", text,
            file=mv["file"], start=mv["start_line"], end=mv["end_line"])

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

    # Jupyter notebook code cells (one chunk per non-trivial, comment-cleaned cell)
    for nb in analysis.get("notebooks", []):
        for cell in nb["cells"]:
            if len(chunks) >= MAX_CHUNKS:
                break
            add("notebook_cell",
                f"{nb['file']} — cell {cell['index']} ({cell['type']}, {nb['language']})",
                f"Notebook {nb['file']}, cell {cell['index']} ({cell['type']}):\n{cell['source']}",
                file=nb["file"], start=cell["index"], end=cell["index"])

    # Generic source files (R, Java, JS, HTML, CSS, SQL, ...): split non-empty,
    # comment-cleaned lines into segments. Empty former-comment lines do not
    # spend the evidence budget, while provenance keeps the original line range.
    SEG_LINES = 60
    for f in analysis.get("other_files", []):
        if len(chunks) >= MAX_CHUNKS:
            break
        decls = f", declarations: {', '.join(f['declarations'])}" if f["declarations"] else ""
        code_lines = [(i, line) for i, line in enumerate(f["text"].splitlines(), start=1) if line.strip()]
        segments = [code_lines[i:i + SEG_LINES] for i in range(0, len(code_lines), SEG_LINES)][:4]
        for seg in segments:
            start, end = seg[0][0], seg[-1][0]
            add("source",
                f"{f['language']} file {f['file']} (lines {start}-{end})",
                f"{f['language']} file {f['file']} ({f['line_count']} lines{decls}).\n"
                f"Content (lines {start}-{end}):\n" + "\n".join(line for _, line in seg),
                file=f["file"], start=start, end=end)

    for tree in _build_call_flow(analysis.get("functions", []), analysis.get("calls", []),
                                 analysis.get("imported_symbols")):
        if len(chunks) >= MAX_CHUNKS:
            break
        entry = tree["entry"]
        add("flow",
            f"Call flow from {entry['qualname']} ({entry['file']})",
            f"Approximate execution flow starting at {entry['qualname']} — likely an entry "
            f"point, since no other analyzed function calls it:\n{tree['text']}",
            file=entry["file"], start=entry["start_line"], end=entry["end_line"])

    calls = analysis.get("calls", [])
    if calls:
        edges = "\n".join(f"{caller} -> {callee}" for caller, callee in calls[:400])
        add("callgraph", "Approximate call graph", "Approximate call edges (caller -> callee):\n" + edges)

    return chunks


def _build_call_flow(functions: list[dict], calls: list[tuple[str, str]],
                     imported_symbols: dict | None = None) -> list[dict]:
    """Group the flat (caller, callee) edge list into one call tree per likely
    entry point, instead of leaving the LLM to reassemble a "flowchart" from
    an unordered edge list itself. An entry point here just means: a function
    that has at least one resolvable outgoing call, but that nothing else we
    analyzed calls — approximate, same spirit as the call graph itself
    (name-level matching, no type inference, so ambiguous/unresolved callees
    — stdlib calls, overloaded method names — are simply dropped as edges).
    """
    if not calls:
        return []

    by_key = {f"{fn['file']}::{fn['qualname']}": fn for fn in functions}
    # Keyed per FILE, not globally: calls resolve within their own file's
    # analyzed functions, since `calls` never crosses files/languages to begin
    # with, and a global name index would let e.g. bank.py's `deposit` collide
    # with an unrelated `deposit` method in some other analyzed file.
    by_name_in_file: dict[str, dict[str, list[str]]] = {}
    for key, fn in by_key.items():
        by_name_in_file.setdefault(fn["file"], {}).setdefault(fn["name"], []).append(key)

    edges: dict[str, list[str]] = {}
    callees_seen: set[str] = set()
    imported_symbols = imported_symbols or {}
    for caller, callee in calls:
        caller_fn = by_key.get(caller)
        if caller_fn is None:
            continue
        matches = by_name_in_file.get(caller_fn["file"], {}).get(callee, [])
        if not matches:
            # Cross-file step: if the caller's file imported this name
            # (`from src.storage import load_tasks`), the analyzer's shallow
            # symbol table tells us the defining file + original name — so the
            # flow tree can follow the call across module boundaries.
            sym = imported_symbols.get(caller_fn["file"], {}).get(callee)
            if sym:
                dst_file, original = sym
                matches = by_name_in_file.get(dst_file, {}).get(original, [])
        if len(matches) == 1:  # skip ambiguous/unresolved callees (stdlib, overloads, ...)
            target = matches[0]
            edges.setdefault(caller, []).append(target)
            callees_seen.add(target)

    entry_points = sorted(k for k in edges if k not in callees_seen)

    MAX_NODES = 60
    trees = []
    for entry in entry_points[:20]:
        lines: list[str] = []
        count = 0

        def walk(key: str, depth: int, path: frozenset):
            nonlocal count
            if count >= MAX_NODES:
                return
            fn = by_key[key]
            lines.append(f"{'  ' * depth}{fn['qualname']} ({fn['file']} lines {fn['start_line']}-{fn['end_line']})")
            count += 1
            if key in path:
                lines.append(f"{'  ' * (depth + 1)}(recursion — already on this path, stopping)")
                return
            for target in edges.get(key, []):
                if count >= MAX_NODES:
                    lines.append(f"{'  ' * (depth + 1)}... (truncated)")
                    break
                walk(target, depth + 1, path | {key})

        walk(entry, 0, frozenset())
        trees.append({"entry": by_key[entry], "text": "\n".join(lines)})
    return trees


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+|\d+")


def _tokenize(text: str) -> list[str]:
    """Tokenizer for BM25. Each identifier is indexed twice: whole and in
    snake_case pieces — so a query for "tasks" still matches `save_tasks`.
    (The whole token is kept as well because exact identifier queries like
    `save_tasks` should rank highest.)"""
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

    def retrieve(self, query: str, k: int = 6, kinds: tuple[str, ...] = (),
                 expansion_terms: list[str] | tuple[str, ...] = ()) -> list[dict]:
        # BM25 scores every chunk against the query terms (rewarding rare
        # terms, damping very long chunks), then we take the top k. `kinds`
        # optionally restricts results to chunk types, e.g. only functions.
        scores = self.bm25.get_scores(_tokenize(query))
        if expansion_terms:
            # An alias match is useful but must not outweigh the user's own
            # wording.  BM25 has no semantic model; this fixed, transparent
            # bonus is the domain knowledge supplied by the lexicon above.
            scores = scores + 0.35 * self.bm25.get_scores(_tokenize(" ".join(expansion_terms)))
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
