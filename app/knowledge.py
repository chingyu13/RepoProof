"""Static-analysis evidence and BM25 retrieval."""
import re

from rank_bm25 import BM25Okapi

MAX_CHUNKS = 800

CONCEPT_LEXICON = {
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
    "architecture": {
        "triggers": ("architecture", "component", "module", "layer", "separation of concerns"),
        "aliases": ("module", "package", "component", "dependency", "import", "boundary", "layer", "call"),
    },
    "integration_api": {
        "triggers": ("integration", "api", "endpoint", "external service", "message queue"),
        "aliases": ("api", "endpoint", "request", "response", "client", "route", "publish", "subscribe", "mqtt"),
    },
    "workflow": {
        "triggers": ("workflow", "data flow", "control flow", "pipeline", "process"),
        "aliases": ("flow", "pipeline", "input", "output", "call", "stage", "process", "return"),
    },
    "testing": {
        "triggers": ("testing", "test", "test case", "assertion", "expected behavior"),
        "aliases": ("test", "assert", "fixture", "mock", "expected", "boundary", "failure"),
    },
    "security": {
        "triggers": ("security", "authentication", "authorization", "access control", "privacy"),
        "aliases": ("auth", "token", "permission", "validate", "sanitize", "secret", "session", "access"),
    },
    "database": {
        "triggers": ("database", "data model", "data modelling", "schema", "persistence"),
        "aliases": ("database", "table", "schema", "column", "key", "constraint", "query", "sql", "persist"),
    },
    "complexity": {
        "triggers": ("complexity", "performance", "optimization", "efficiency", "big o"),
        "aliases": ("complexity", "performance", "optimize", "loop", "branch", "time", "memory", "cache"),
    },
    "object_orientation": {
        "triggers": ("oop", "object oriented", "object-oriented", "inheritance", "polymorphism"),
        "aliases": ("class", "method", "object", "inherit", "interface", "encapsulation", "polymorphism"),
    },
}


def expand_concepts(text: str, direction: str = "curriculum_to_code") -> list[str]:
    normalized = " ".join(_tokenize(text))
    terms: list[str] = []
    for concept in CONCEPT_LEXICON.values():
        if any(trigger in normalized for trigger in concept["triggers"]):
            terms.extend(concept["aliases"])
    return list(dict.fromkeys(terms))


def data_engineering_expansion(text: str) -> list[str]:
    return expand_concepts(text)


def build_chunks(analysis: dict, snapshot_id: str) -> list[dict]:
    chunks: list[dict] = []

    def add(kind: str, title: str, text: str, file: str = "", start: int = 0, end: int = 0,
            evidence_types: tuple[str, ...] = ()):
        if len(chunks) >= MAX_CHUNKS:
            return
        chunks.append({
            "id": f"c{len(chunks)}",
            "kind": kind,
            "title": title,
            "text": text.strip(),
            "file": file,
            "start_line": start,
            "end_line": end,
            "snapshot": snapshot_id,
            "evidence_types": list(dict.fromkeys(evidence_types)),
        })

    if analysis.get("readme"):
        add("readme", "README", analysis["readme"])

    if analysis.get("dependencies"):
        add("dependencies", "Declared dependencies",
            "The project declares these dependencies:\n" + "\n".join(analysis["dependencies"]),
            evidence_types=("dependency_graph",))

    if analysis.get("files"):
        rows = []
        for entry in analysis["files"][:300]:
            rel, lang = entry if isinstance(entry, (list, tuple)) else (entry, "Python")
            rows.append(f"{rel}  [{lang}]")
        add("structure", "Project file structure",
            "Source files in the project (path [language]):\n" + "\n".join(rows),
            evidence_types=("module_graph",))

    for rel, mods in list(analysis.get("file_imports", {}).items())[:150]:
        add("imports", f"Imports in {rel}",
            f"The module {rel} imports: {', '.join(mods)}", file=rel,
            evidence_types=("dependency_graph",))

    import_edges = analysis.get("import_edges") or []
    if import_edges:
        rows = []
        for src, dst, names in import_edges[:200]:
            what = f" ({', '.join(names)})" if names else ""
            rows.append(f"{src} -> {dst}{what}")
        add("import_graph", "Internal import graph",
            "Repo-internal import dependencies (importer -> imported file (symbols)):\n"
            + "\n".join(rows), evidence_types=("module_graph", "dependency_graph"))

    for mv in analysis.get("module_vars", [])[:200]:
        names = ", ".join(mv["names"])
        text = (
            f"Module-level constant(s) {names} in {mv['file']} "
            f"(lines {mv['start_line']}-{mv['end_line']}).\nCode:\n{mv['code']}"
        )
        add("module_var", f"Constant {names} ({mv['file']})", text,
            file=mv["file"], start=mv["start_line"], end=mv["end_line"],
            evidence_types=("symbol_table",))

    for cls in analysis.get("classes", [])[:200]:
        text = (
            f"Class {cls['qualname']} in {cls['file']} "
            f"(lines {cls['start_line']}-{cls['end_line']}).\n"
            f"Bases: {', '.join(cls['bases']) or 'none'}. "
            f"Methods: {', '.join(cls['methods']) or 'none'}.\n"
            f"Docstring: {cls['docstring'] or '(none)'}"
        )
        add("class", f"Class {cls['qualname']}", text,
            file=cls["file"], start=cls["start_line"], end=cls["end_line"],
            evidence_types=("symbol_table",))

    for fn in analysis.get("functions", []):
        if len(chunks) >= MAX_CHUNKS:
            break
        location = (
            f"cell {fn['cell_index']}"
            if "cell_index" in fn
            else f"lines {fn['start_line']}-{fn['end_line']}"
        )
        text = (
            f"{'Async function' if fn['is_async'] else 'Function'} {fn['qualname']} "
            f"in {fn['file']} ({location}).\n"
            f"Parameters: {', '.join(fn['args']) or 'none'}.\n"
            f"Docstring: {fn['docstring'] or '(none)'}\n"
            f"Code:\n{fn['code']}"
        )
        title_location = f", cell {fn['cell_index']}" if "cell_index" in fn else ""
        add("function", f"Function {fn['qualname']} ({fn['file']}{title_location})", text,
            file=fn["file"], start=fn["start_line"], end=fn["end_line"],
            evidence_types=("symbol_table", "data_flow_graph", "control_flow_graph"))

    # Jupyter notebook code cells (one chunk per non-trivial, comment-cleaned cell)
    for nb in analysis.get("notebooks", []):
        for cell in nb["cells"]:
            if len(chunks) >= MAX_CHUNKS:
                break
            cell_evidence_types = ("data_flow_graph", "control_flow_graph")
            if cell["type"] == "code":
                cell_evidence_types += ("symbol_table",)
            add("notebook_cell",
                f"{nb['file']} — cell {cell['index']} ({cell['type']}, {nb['language']})",
                f"Notebook {nb['file']}, cell {cell['index']} ({cell['type']}):\n{cell['source']}",
                file=nb["file"], start=cell["index"], end=cell["index"],
                evidence_types=cell_evidence_types)

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
                file=f["file"], start=start, end=end,
                evidence_types=(
                    ("sql_analysis",)
                    if f["language"].lower() == "sql"
                    else ("symbol_table", "data_flow_graph", "control_flow_graph")
                ))

    for tree in _build_call_flow(analysis.get("functions", []), analysis.get("calls", []),
                                 analysis.get("imported_symbols")):
        if len(chunks) >= MAX_CHUNKS:
            break
        entry = tree["entry"]
        add("flow",
            f"Call flow from {entry['qualname']} ({entry['file']})",
            f"Approximate execution flow starting at {entry['qualname']} — likely an entry "
            f"point, since no other analyzed function calls it:\n{tree['text']}",
            file=entry["file"], start=entry["start_line"], end=entry["end_line"],
            evidence_types=("call_graph", "data_flow_graph", "control_flow_graph"))

    calls = analysis.get("calls", [])
    if calls:
        edges = "\n".join(f"{caller} -> {callee}" for caller, callee in calls[:400])
        add("callgraph", "Approximate call graph", "Approximate call edges (caller -> callee):\n" + edges,
            evidence_types=("call_graph",))

    _add_evidence_summaries(add, analysis)

    return chunks


def _add_evidence_summaries(add, analysis: dict) -> None:
    """Add compact static summaries without passing a raw project to an LLM."""
    files = analysis.get("files", [])
    functions = analysis.get("functions", [])
    classes = analysis.get("classes", [])
    module_vars = analysis.get("module_vars", [])

    # Module graph inventory is useful even when a project has no resolvable
    # internal imports (for example, a single-file notebook assignment).
    module_rows = []
    for entry in files[:300]:
        rel, language = entry if isinstance(entry, (list, tuple)) else (entry, "Unknown")
        module_rows.append(f"{rel} [{language}]")
    for src, dst, _ in (analysis.get("import_edges") or [])[:200]:
        module_rows.append(f"{src} -> {dst}")
    if module_rows:
        add("module_graph", "Module graph summary",
            "Static module inventory and internal relationships:\n" + "\n".join(module_rows),
            evidence_types=("module_graph",))

    symbols = []
    symbols.extend(f"module variable {', '.join(item['names'])} — {item['file']}"
                   for item in module_vars[:160])
    symbols.extend(f"class {item['qualname']} — {item['file']} (methods: {', '.join(item['methods']) or 'none'})"
                   for item in classes[:160])
    symbols.extend(f"function {item['qualname']}({', '.join(item['args'])}) — {item['file']}"
                   for item in functions[:300])
    if symbols:
        add("symbol_table", "Symbol table summary",
            "Statically discovered project symbols:\n" + "\n".join(symbols),
            evidence_types=("symbol_table",))

    complexity_rows = []
    branch_re = re.compile(r"\b(if|elif|else|case|except|catch|switch)\b")
    loop_re = re.compile(r"\b(for|while|do)\b")
    call_re = re.compile(r"\w+\s*\(")
    for fn in functions[:300]:
        code = fn.get("code", "")
        complexity_rows.append(
            f"{fn['qualname']} ({fn['file']} lines {fn['start_line']}-{fn['end_line']}): "
            f"{len(code.splitlines())} code lines; {len(loop_re.findall(code))} loop keyword(s); "
            f"{len(branch_re.findall(code))} branch keyword(s); {len(call_re.findall(code))} call-like expression(s)."
        )
    if complexity_rows:
        add("complexity", "Static complexity indicators",
            "Heuristic indicators only — not a formal Big-O proof:\n" + "\n".join(complexity_rows),
            evidence_types=("complexity_analysis",))

    test_rows = []
    for entry in files[:300]:
        rel = entry[0] if isinstance(entry, (list, tuple)) else entry
        name = rel.rsplit("/", 1)[-1].lower()
        if name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{rel.lower()}":
            test_rows.append(f"test-like file: {rel}")
    for fn in functions[:300]:
        if fn["name"].lower().startswith("test"):
            test_rows.append(f"test-like function: {fn['qualname']} ({fn['file']})")
    if test_rows:
        add("test_discovery", "Test discovery summary",
            "Statically discovered test artefacts:\n" + "\n".join(dict.fromkeys(test_rows)),
            evidence_types=("test_discovery",))

    api_rows = []
    route_re = re.compile(
        r"@(app|router|blueprint|bp)\.(get|post|put|patch|delete|route)\b|"
        r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_./{}:-]+)", re.I
    )
    for fn in functions[:300]:
        if route_re.search(fn.get("code", "")):
            api_rows.append(f"route/endpoint indicator: {fn['qualname']} ({fn['file']} lines {fn['start_line']}-{fn['end_line']})")
    for source in analysis.get("other_files", [])[:150]:
        for line_no, line in enumerate(source.get("text", "").splitlines(), start=1):
            if route_re.search(line):
                api_rows.append(f"route/endpoint indicator: {source['file']} line {line_no}: {line.strip()[:160]}")
    if api_rows:
        add("api_discovery", "API discovery summary",
            "Statically discovered API/route indicators:\n" + "\n".join(list(dict.fromkeys(api_rows))[:200]),
            evidence_types=("api_discovery",))

    sql_rows = []
    sql_re = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE\s+TABLE|ALTER\s+TABLE|FROM|JOIN)\b", re.I)
    for source in analysis.get("other_files", [])[:150]:
        if source.get("language", "").lower() == "sql":
            sql_rows.append(f"SQL source file: {source['file']} ({source['line_count']} lines)")
        elif sql_re.search(source.get("text", "")):
            sql_rows.append(f"SQL-like statement detected in: {source['file']}")
    for fn in functions[:300]:
        if sql_re.search(fn.get("code", "")):
            sql_rows.append(f"SQL-like statement detected in function: {fn['qualname']} ({fn['file']})")
    if sql_rows:
        add("sql_analysis", "SQL analysis summary",
            "Statically discovered SQL artefacts:\n" + "\n".join(dict.fromkeys(sql_rows)),
            evidence_types=("sql_analysis",))


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


def retrieval_tokens(text: str) -> list[str]:
    return _tokenize(text)


def evidence_types_for_chunk(chunk: dict) -> tuple[str, ...]:
    return tuple(chunk.get("evidence_types") or ())


class EvidenceStore:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        corpus = [_tokenize(c["title"] + " " + c["text"]) for c in chunks] or [["empty"]]
        self.bm25 = BM25Okapi(corpus)

    def retrieve(self, query: str, k: int = 6, kinds: tuple[str, ...] = (),
                 evidence_types: tuple[str, ...] = (),
                 expansion_terms: list[str] | tuple[str, ...] = (),
                 exclude_ids: set[str] | frozenset[str] = frozenset()) -> list[dict]:
        return [
            item["chunk"]
            for item in self.retrieve_scored(
                query,
                k=k,
                kinds=kinds,
                evidence_types=evidence_types,
                expansion_terms=expansion_terms,
                exclude_ids=exclude_ids,
            )
        ]

    def retrieve_scored(self, query: str, k: int = 6, kinds: tuple[str, ...] = (),
                        evidence_types: tuple[str, ...] = (),
                        expansion_terms: list[str] | tuple[str, ...] = (),
                        exclude_ids: set[str] | frozenset[str] = frozenset()) -> list[dict]:
        scores = self.bm25.get_scores(_tokenize(query))
        if expansion_terms:
            scores = scores + 0.35 * self.bm25.get_scores(_tokenize(" ".join(expansion_terms)))
        ranked = sorted(range(len(self.chunks)), key=lambda i: scores[i], reverse=True)
        out = []
        for i in ranked:
            c = self.chunks[i]
            if c["id"] in exclude_ids:
                continue
            if kinds and c["kind"] not in kinds:
                continue
            if evidence_types and not set(evidence_types_for_chunk(c)).intersection(evidence_types):
                continue
            out.append({"chunk": c, "score": float(scores[i])})
            if len(out) >= k:
                break
        return out

    def retrieve_bundle(self, query: str, evidence_spec: dict, *,
                        fallback_evidence_types: tuple[str, ...] = (),
                        expansion_terms: list[str] | tuple[str, ...] = (),
                        variant: int = 0) -> tuple[list[dict], list[str]]:
        max_chunks = evidence_spec["max_chunks"]
        selected: list[dict] = []
        selected_ids: set[str] = set()
        missing: list[str] = []

        def add_group(group: dict, required: bool) -> None:
            group_query = " ".join(part for part in (query, group["query"]) if part)
            candidates = self.retrieve(
                group_query,
                k=max(8, max_chunks * 4),
                kinds=tuple(group["kinds"]),
                evidence_types=tuple(group["types"]),
                expansion_terms=expansion_terms,
            )
            if candidates:
                start = variant % len(candidates)
                candidates = candidates[start:] + candidates[:start]
            added = 0
            for chunk in candidates:
                if chunk["id"] in selected_ids:
                    continue
                selected.append(chunk)
                selected_ids.add(chunk["id"])
                added += 1
                if added >= group["count"] or len(selected) >= max_chunks:
                    break
            if required and added < group["count"]:
                missing.append(group["label"])

        for group in evidence_spec["required"]:
            add_group(group, True)
        if missing:
            return selected, missing

        for group in evidence_spec["optional"]:
            if len(selected) >= max_chunks:
                break
            add_group(group, False)

        if len(selected) < max_chunks:
            fill = self.retrieve(
                query,
                k=max_chunks * 4,
                evidence_types=fallback_evidence_types,
                expansion_terms=expansion_terms,
                exclude_ids=frozenset(selected_ids),
            )
            if fill:
                start = variant % len(fill)
                fill = fill[start:] + fill[:start]
            selected.extend(fill[:max_chunks - len(selected)])
        return selected[:max_chunks], []


ChunkIndex = EvidenceStore
