"""Evidence-backed typed-slot resolution for Local question plans."""
from __future__ import annotations

import ast
import re

from .knowledge import EvidenceStore, data_engineering_expansion


_CONTEXT_LABELS = {
    "architecture": "project architecture",
    "api": "integration",
    "data_flow": "data workflow",
    "project_logic": "implementation logic",
    "database": "data modelling",
    "security": "security",
    "testing": "testing",
    "complexity": "complexity",
    "oop": "object collaboration",
}
_INSTRUCTION_PREFIX_RE = re.compile(
    r"^(?:explain|describe|identify|analyse|analyze|evaluate|demonstrate|"
    r"implement|create|build|use|apply)\s+(?:how\s+|why\s+|whether\s+)?",
    re.I,
)
_CALL_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\s*\("
)
_ARROW_RE = re.compile(r"\s*(?:->|→)\s*")
_CODE_KINDS = frozenset({"function", "notebook_cell", "source"})
_CONTEXT_STOPWORDS = frozenset({
    "about", "assessment", "behavior", "correctly", "describe", "explain",
    "project", "requirement", "statement", "the", "this", "within",
})


def template_query(topic: dict, template: dict, extra_focus: str) -> str:
    return " ".join(
        part for part in (topic["query"], template["query"], extra_focus) if part
    )


def _is_relational_chunk(chunk: dict) -> bool:
    return (
        chunk["kind"] in {"flow", "callgraph", "import_graph", "api_discovery"}
        or (chunk["kind"] == "module_graph" and "->" in chunk["text"])
    )


def template_bundle(evidence_store: EvidenceStore, topic: dict, template: dict,
                    extra_focus: str, variant: int = 0) -> tuple[list[dict], list[str]]:
    query = template_query(topic, template, extra_focus)
    expansion = data_engineering_expansion(
        " ".join(part for part in (topic["name"], topic["query"], extra_focus) if part)
    )
    topic_types = set(topic["evidence_types"])

    def narrow(group: dict) -> dict:
        shared = [
            evidence_type
            for evidence_type in group["types"]
            if evidence_type in topic_types
        ]
        return {**group, "types": shared or group["types"]}

    evidence_spec = {
        **template["evidence"],
        "required": [narrow(group) for group in template["evidence"]["required"]],
        "optional": [narrow(group) for group in template["evidence"]["optional"]],
    }
    evidence, missing = evidence_store.retrieve_bundle(
        query,
        evidence_spec,
        fallback_evidence_types=tuple(topic["evidence_types"]),
        expansion_terms=expansion,
        variant=variant,
    )
    if topic["id"] == "architecture" and not missing:
        relational = [chunk for chunk in evidence if _is_relational_chunk(chunk)]
        if not relational:
            relational = [
                chunk
                for chunk in evidence_store.retrieve(
                    query + " call flow dependency API module relationship",
                    k=evidence_spec["max_chunks"] * 2,
                    kinds=(
                        "flow", "callgraph", "import_graph",
                        "api_discovery", "module_graph",
                    ),
                    evidence_types=(
                        "call_graph", "dependency_graph",
                        "api_discovery", "module_graph",
                    ),
                    expansion_terms=expansion,
                )
                if _is_relational_chunk(chunk)
            ]
        if not relational:
            missing.append("relational architecture evidence")
        else:
            unique_evidence = []
            seen_ids = set()
            for chunk in relational + evidence:
                if chunk["id"] in seen_ids:
                    continue
                seen_ids.add(chunk["id"])
                unique_evidence.append(chunk)
            evidence = unique_evidence[:evidence_spec["max_chunks"]]
    return evidence, missing


def _chunk_code(chunk: dict) -> str:
    text = chunk["text"]
    if "\nCode:\n" in text:
        return text.split("\nCode:\n", 1)[1].strip()
    if chunk["kind"] == "notebook_cell" and "\n" in text:
        return text.split("\n", 1)[1].strip()
    match = re.search(r"\nContent \(lines [^)]+\):\n(.*)", text, re.S)
    return (match.group(1) if match else text).strip()


def display_code(evidence: list[dict], template_id: str = "",
                 query: str = "") -> tuple[str, str, str] | None:
    candidates = []
    for chunk in evidence:
        if chunk["kind"] not in _CODE_KINDS:
            continue
        code = _chunk_code(chunk)
        suffix = chunk["file"].rsplit(".", 1)[-1].lower() if "." in chunk["file"] else ""
        snippets = []
        if suffix in {"py", "ipynb"}:
            lines = code.splitlines()
            tree = None
            parsed_source = ""
            for end in range(len(lines), 0, -1):
                parsed_source = "\n".join(lines[:end])
                try:
                    tree = ast.parse(parsed_source)
                    break
                except SyntaxError:
                    continue
            if tree:
                if template_id == "condition_outcome":
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.If, ast.Try, ast.Match)):
                            snippet = ast.get_source_segment(parsed_source, node)
                            if snippet:
                                snippets.append(snippet)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        snippet = ast.get_source_segment(parsed_source, node)
                        if snippet:
                            snippets.append(snippet)
        snippets.append(code)
        for snippet in dict.fromkeys(snippets):
            line_count = len(snippet.splitlines())
            if snippet and line_count <= 12:
                candidates.append((chunk, snippet, line_count))
    if not candidates:
        return None

    query_tokens = _tokens(query)
    candidates.sort(
        key=lambda item: (
            -int(
                template_id == "condition_outcome"
                and re.match(r"^(?:if\b|try:|match\b)", item[1].lstrip()) is not None
            ),
            -len(_tokens(item[1]).intersection(query_tokens)),
            item[2],
            item[0]["id"],
        )
    )
    chunk, code, _ = candidates[0]
    suffix = chunk["file"].rsplit(".", 1)[-1].lower() if "." in chunk["file"] else ""
    language = {
        "py": "python",
        "ipynb": "python",
        "js": "javascript",
        "ts": "typescript",
        "cpp": "cpp",
        "cc": "cpp",
        "cs": "csharp",
    }.get(suffix, suffix or "text")
    return code, language, chunk["id"]


def _tokens(value: str) -> set[str]:
    result = set()
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.-]*", value.casefold()):
        result.add(token)
        result.update(
            part for part in re.split(r"[_.-]", token)
            if len(part) >= 3
        )
    return result


def _context_tokens(value: str) -> set[str]:
    expanded = data_engineering_expansion(value)
    return (
        _tokens(value + " " + " ".join(expanded))
        - _CONTEXT_STOPWORDS
    )


def _target_evidence_ids(target: dict | None) -> set[str]:
    if not target or target.get("kind") != "project_scope":
        return set()
    return {
        str(item.get("chunk_id"))
        for item in target.get("evidence", [])
        if item.get("chunk_id")
    }


def _compact_context(target: dict | None, topic: dict) -> str:
    fallback = _CONTEXT_LABELS.get(topic["id"], topic["name"].casefold())
    if not target:
        return fallback
    value = " ".join(
        str(target.get("label") or target.get("description") or "").split()
    )
    value = re.sub(r"[*_#>`]", "", value)
    value = _INSTRUCTION_PREFIX_RE.sub("", value).strip(" .:;-")
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_./+-]*", value)
    if (
        not value
        or len(value) > 64
        or len(words) > 8
        or re.match(r"^(?:this|the)\s+assignment\b", value, re.I)
        or re.search(r"\b(?:marks?|points?|bonus|capped|total)\b", value, re.I)
    ):
        return fallback
    return value


def _display_entity(entity_type: str, value: str) -> str:
    clean = value.strip(" `\"'")
    if entity_type == "imported_library":
        return f"the `{clean}` package"
    if entity_type == "api_method":
        return f"`{clean.removesuffix('()')}()`"
    if entity_type == "component":
        label = "module" if "." in clean else "component"
        return f"the `{clean}` {label}"
    if entity_type == "function":
        return f"`{clean.removesuffix('()')}()`"
    if entity_type == "class":
        return f"the `{clean}` class"
    if entity_type == "data_store":
        return f"the `{clean}` data store"
    if entity_type == "state":
        return f"the `{clean}` state"
    return f"`{clean}`"


def _entity_candidates(evidence: list[dict], allowed: list[str],
                       context: str, target: dict | None) -> list[dict]:
    candidates: list[dict] = []
    allowed_set = set(allowed)
    all_text = "\n".join(chunk["text"] for chunk in evidence)

    def add(entity_type: str, value: str, chunk: dict) -> None:
        value = value.strip(" `\"'.,:;")
        if entity_type not in allowed_set or len(value) < 2:
            return
        candidates.append({
            "type": entity_type,
            "value": value,
            "display": _display_entity(entity_type, value),
            "chunk_id": chunk["id"],
            "text": chunk["text"],
        })

    for chunk in evidence:
        title, text = chunk["title"], chunk["text"]
        if chunk["kind"] == "function":
            match = re.match(r"Function\s+([A-Za-z_][A-Za-z0-9_.]*)", title)
            if match:
                add("function", match.group(1), chunk)
        if chunk["kind"] == "class":
            match = re.match(r"Class\s+([A-Za-z_][A-Za-z0-9_.]*)", title)
            if match:
                add("class", match.group(1), chunk)
        if chunk["kind"] == "module_var":
            match = re.search(r"constant\(s\)\s+(.+?)\s+in\s+", text, re.I)
            if match:
                for name in match.group(1).split(","):
                    add("state", name, chunk)
        if chunk["kind"] in {"dependencies", "imports"}:
            payload = text.split(":", 1)[-1]
            for line in re.split(r"[,\n]", payload):
                match = re.match(r"\s*([A-Za-z][A-Za-z0-9_.-]+)", line)
                if not match:
                    continue
                package = match.group(1)
                package_tokens = _tokens(package)
                other_text = all_text.replace(chunk["text"], "", 1)
                if package_tokens.intersection(_tokens(other_text)):
                    add("imported_library", package, chunk)
        for call in _CALL_RE.findall(text):
            if call.rsplit(".", 1)[-1] not in {"get", "set", "items", "values", "append"}:
                add("api_method", call + "()", chunk)
        for table in re.findall(
            r"\b(?:CREATE\s+TABLE|FROM|JOIN|INTO|UPDATE)\s+([A-Za-z_][A-Za-z0-9_]*)",
            text,
            re.I,
        ):
            add("data_store", table, chunk)
        if _is_relational_chunk(chunk):
            for relation in _relation_candidates([chunk]):
                add("component", relation["source"], chunk)
                add("component", relation["target"], chunk)

    context_tokens = _context_tokens(context)
    target_evidence_ids = _target_evidence_ids(target)
    type_order = {entity_type: index for index, entity_type in enumerate(allowed)}
    unique = {}
    for candidate in candidates:
        key = (candidate["type"], candidate["value"].casefold())
        score = (
            3 * len(context_tokens.intersection(_tokens(candidate["text"])))
            + len(context_tokens.intersection(_tokens(candidate["value"])))
        )
        ranked = (score, -type_order.get(candidate["type"], 99))
        if key not in unique or ranked > unique[key][0]:
            unique[key] = (ranked, candidate)
    ranked = [
        item[1]
        for item in sorted(
            unique.values(),
            key=lambda item: (-item[0][0], -item[0][1], item[1]["value"].casefold()),
        )
    ]
    if target and target.get("kind") == "project_scope":
        ranked = [
            candidate
            for candidate in ranked
            if (
                candidate["chunk_id"] in target_evidence_ids
                or context_tokens.intersection(
                    _tokens(candidate["value"] + " " + candidate["text"])
                )
            )
        ]
    return ranked


def _clean_endpoint(value: str) -> str:
    value = re.sub(r"\s+\([^)]*(?:lines?|symbols?)[^)]*\)\s*$", "", value.strip())
    value = value.split(";", 1)[0]
    value = value.strip(" `\"'.,:;")
    return value[:100]


def _relation_candidates(evidence: list[dict]) -> list[dict]:
    relations = []
    for chunk in evidence:
        for line in chunk["text"].splitlines():
            if "->" not in line and "→" not in line:
                continue
            parts = [_clean_endpoint(part) for part in _ARROW_RE.split(line)]
            parts = [part for part in parts if part]
            relations.extend({
                "source": source,
                "target": destination,
                "chunk_id": chunk["id"],
                "text": line,
            } for source, destination in zip(parts, parts[1:]))
    unique = {}
    for relation in relations:
        key = (
            relation["source"].casefold(),
            relation["target"].casefold(),
            relation["chunk_id"],
        )
        unique.setdefault(key, relation)
    return list(unique.values())


def _code_condition(code: str) -> str | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        tree = None
    if tree:
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                return f"`{ast.unparse(node.test)}`"
            if isinstance(node, ast.Try):
                return "an exception is raised inside the shown `try` block"
            if isinstance(node, ast.Match):
                return f"`{ast.unparse(node.subject)}` reaches the shown match branch"
    match = re.search(r"\bif\s*\((.*?)\)", code)
    return f"`{match.group(1).strip()}`" if match else None


def _code_mutation(code: str) -> str | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        tree = None
    if tree:
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                return f"negate the condition `{ast.unparse(node.test)}`"
        for node in ast.walk(tree):
            if isinstance(node, ast.Return):
                return f"remove the statement `{ast.unparse(node)}`"
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                return f"remove the call `{ast.unparse(node.value)}`"
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("return "):
            return f"remove the statement `{stripped}`"
    return None


def _derived_requirement(target: dict | None, code: str) -> str:
    if target and target.get("kind") == "project_scope":
        description = " ".join(str(target.get("description") or "").split())
        actionable = re.search(
            r"\b(?:implement|add|create|ensure|validate|log|retry|handle|support|must|should)\b",
            description,
            re.I,
        )
        subjective = re.search(
            r"\b(?:best|better|ideal|preferred|recommended|why)\b",
            description,
            re.I,
        )
        if actionable and not subjective:
            return description[:240].rstrip(" .")
    return_line = next(
        (line.strip() for line in code.splitlines() if line.strip().startswith("return ")),
        "",
    )
    if return_line:
        return (
            "record a diagnostic immediately before the function returns, "
            f"without changing `{return_line}`"
        )
    return "record a diagnostic before the final operation without changing existing behavior"


def _insert_marker(code: str, language: str) -> str:
    lines = code.splitlines()
    if len(lines) < 2:
        return code
    insert_at = next(
        (
            index for index in range(len(lines) - 1, 0, -1)
            if lines[index].lstrip().startswith("return ")
        ),
        len(lines) - 1,
    )
    indent = re.match(r"\s*", lines[insert_at]).group(0)
    marker = "-- INSERT HERE" if language == "sql" else (
        "// INSERT HERE"
        if language in {
            "c", "cpp", "csharp", "java", "javascript",
            "typescript", "go", "rust", "swift", "kotlin",
        }
        else "# INSERT HERE"
    )
    lines.insert(insert_at, indent + marker)
    return "\n".join(lines)


def render_question_plan(template: dict, topic: dict, target: dict | None,
                         evidence: list[dict], variant: int = 0,
                         frame_variant: int | None = None) -> tuple[dict | None, str]:
    context = _compact_context(target, topic)
    resolved: dict[str, str] = {"context": context}
    code = language = evidence_id = ""

    if template["code_mode"] != "none":
        displayed = display_code(
            evidence,
            template["id"],
            template_query(topic, template, context),
        )
        if displayed is None:
            return None, "no concise code context"
        code, language, evidence_id = displayed

    relations = _relation_candidates(evidence)
    context_tokens = _context_tokens(context)
    target_evidence_ids = _target_evidence_ids(target)
    if target and target.get("kind") == "project_scope":
        relations = [
            relation
            for relation in relations
            if (
                relation["chunk_id"] in target_evidence_ids
                or context_tokens.intersection(_tokens(relation["text"]))
            )
        ]
    relations.sort(
        key=lambda relation: (
            -int(relation["chunk_id"] in target_evidence_ids),
            -len(context_tokens.intersection(_tokens(relation["text"]))),
            relation["source"].casefold(),
            relation["target"].casefold(),
        )
    )
    selected_relation = relations[variant % len(relations)] if relations else None
    for name, spec in template["slots"].items():
        source = spec["source"]
        if source == "target_or_topic":
            resolved[name] = context
        elif source == "evidence_entity":
            related_context = resolved.get(spec.get("related_to"), context)
            candidates = _entity_candidates(
                evidence,
                spec["types"],
                related_context,
                target,
            )
            if not candidates:
                return None, f"no {name} entity"
            resolved[name] = candidates[variant % len(candidates)]["display"]
        elif source == "relation_source":
            if not selected_relation:
                return None, "no evidenced relationship"
            resolved[name] = _display_entity(
                "component", selected_relation["source"]
            )
        elif source == "relation_target":
            if not selected_relation:
                return None, "no evidenced relationship"
            resolved[name] = _display_entity(
                "component", selected_relation["target"]
            )
        elif source == "code_condition":
            condition = _code_condition(code)
            if not condition:
                return None, "no explicit code condition"
            resolved[name] = condition
        elif source == "code_mutation":
            mutation = _code_mutation(code)
            if not mutation:
                return None, "no safe hypothetical mutation"
            resolved[name] = mutation
        elif source == "target_or_requirement":
            resolved[name] = _derived_requirement(target, code)

    frame_index = (
        frame_variant if frame_variant is not None else variant
    ) % len(template["stem_frames"])
    stem = template["stem_frames"][frame_index].format(**resolved)
    if template["code_mode"] == "insertion":
        code = _insert_marker(code, language)
    plan_key = "|".join([
        template["id"],
        stem.casefold(),
        evidence_id or (evidence[0]["id"] if evidence else ""),
    ])
    plan = {
        "rendered_stem": stem,
        "plan_key": plan_key,
        "code_mode": template["code_mode"],
    }
    if code:
        plan.update({
            "display_code": code,
            "display_language": language,
            "display_evidence_id": evidence_id,
        })
    return plan, ""
