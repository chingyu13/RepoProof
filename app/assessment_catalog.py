"""Validated assessment catalog for focus-driven Local LLM generation."""
from __future__ import annotations

import json
import os
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PATH = _ROOT / "assessment_catalog.json"
_CATALOG_PATH = Path(os.environ.get("REPOPROOF_ASSESSMENT_CATALOG", str(_DEFAULT_PATH)))

BUILT_IN_STRATEGY_IDS = (
    "explain",
    "execution",
    "prediction",
    "debugging",
    "modification",
)


def _catalog_path() -> Path:
    if _CATALOG_PATH.is_file():
        return _CATALOG_PATH
    raise FileNotFoundError(f"No assessment catalog found. Expected {_CATALOG_PATH}.")


def _required(raw: dict, keys: tuple[str, ...], kind: str) -> None:
    missing = [key for key in keys if key not in raw]
    if missing:
        raise ValueError(f"{kind} {raw.get('id')!r} missing keys: {missing}")


def _clean_id(value: object, kind: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{kind} needs a non-empty id")
    return result


def _normalize_weights(raw: object, ids: tuple[str, ...], *, owner: str) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise ValueError(f"{owner} template weights must be an object")
    unknown = sorted(set(raw) - set(ids))
    if unknown:
        raise ValueError(f"{owner} references unknown templates: {unknown}")
    weights = {}
    for template_id in ids:
        try:
            value = float(raw.get(template_id, 0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{owner} has a non-numeric weight for {template_id!r}") from exc
        if not 0 <= value <= 1:
            raise ValueError(f"{owner} weight for {template_id!r} must be between 0 and 1")
        weights[template_id] = value
    return weights


def _normalize_strategy(raw: dict) -> dict:
    _required(raw, ("id", "name", "prefix"), "strategy")
    return {
        "id": _clean_id(raw["id"], "strategy"),
        "name": str(raw["name"]).strip(),
        "prefix": str(raw["prefix"]).strip(),
    }


def _normalize_evidence_type(raw: dict) -> dict:
    _required(raw, ("id", "name", "description"), "evidence type")
    return {
        "id": _clean_id(raw["id"], "evidence type"),
        "name": str(raw["name"]).strip(),
        "description": str(raw["description"]).strip(),
    }


def _normalize_evidence_group(raw: dict, evidence_ids: tuple[str, ...],
                              *, owner: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"{owner} evidence group must be an object")
    evidence_types = [_clean_id(value, "evidence type") for value in raw.get("types", [])]
    unknown = sorted(set(evidence_types) - set(evidence_ids))
    if unknown:
        raise ValueError(f"{owner} references unknown evidence types: {unknown}")
    kinds = [_clean_id(value, "chunk kind") for value in raw.get("kinds", [])]
    if not evidence_types and not kinds:
        raise ValueError(f"{owner} evidence group needs types or kinds")
    count = int(raw.get("count", 1))
    if not 1 <= count <= 4:
        raise ValueError(f"{owner} evidence count must be between 1 and 4")
    return {
        "types": list(dict.fromkeys(evidence_types)),
        "kinds": list(dict.fromkeys(kinds)),
        "count": count,
        "query": str(raw.get("query", "")).strip(),
        "label": str(raw.get("label", "")).strip() or owner,
    }


def _normalize_template(raw: dict, strategy_ids: tuple[str, ...],
                        evidence_ids: tuple[str, ...]) -> dict:
    _required(raw, ("id", "name", "strategy", "pattern", "query", "evidence"), "template")
    strategy_id = _clean_id(raw["strategy"], "template strategy")
    if strategy_id not in strategy_ids:
        raise ValueError(f"template {raw['id']!r} references unknown strategy {strategy_id!r}")
    evidence = raw["evidence"]
    if not isinstance(evidence, dict):
        raise ValueError(f"template {raw['id']!r} evidence must be an object")
    required_groups = [
        _normalize_evidence_group(group, evidence_ids, owner=f"template {raw['id']!r} required")
        for group in evidence.get("required", [])
    ]
    if not required_groups:
        raise ValueError(f"template {raw['id']!r} needs at least one required evidence group")
    optional_groups = [
        _normalize_evidence_group(group, evidence_ids, owner=f"template {raw['id']!r} optional")
        for group in evidence.get("optional", [])
    ]
    max_chunks = int(evidence.get("max_chunks", 4))
    evidence_chars = int(evidence.get("chars_per_chunk", 1800))
    if not 1 <= max_chunks <= 6:
        raise ValueError(f"template {raw['id']!r} max_chunks must be between 1 and 6")
    if not 500 <= evidence_chars <= 5000:
        raise ValueError(f"template {raw['id']!r} chars_per_chunk must be between 500 and 5000")
    return {
        "id": _clean_id(raw["id"], "template"),
        "name": str(raw["name"]).strip(),
        "strategy": strategy_id,
        "pattern": str(raw["pattern"]).strip(),
        "query": str(raw["query"]).strip(),
        "evidence": {
            "required": required_groups,
            "optional": optional_groups,
            "max_chunks": max_chunks,
            "chars_per_chunk": evidence_chars,
        },
    }


def _normalize_topic(raw: dict, evidence_ids: tuple[str, ...],
                     template_ids: tuple[str, ...]) -> dict:
    _required(raw, ("id", "name", "query", "evidence_types", "template_weights"), "topic")
    requested = [_clean_id(value, "topic evidence type") for value in raw["evidence_types"]]
    if not requested:
        raise ValueError(f"topic {raw['id']!r} needs at least one evidence type")
    unknown = sorted(set(requested) - set(evidence_ids))
    if unknown:
        raise ValueError(f"topic {raw['id']!r} references unknown evidence types: {unknown}")
    return {
        "id": _clean_id(raw["id"], "topic"),
        "name": str(raw["name"]).strip(),
        "query": str(raw["query"]).strip(),
        "description": str(raw.get("description", "")).strip(),
        "evidence_types": list(dict.fromkeys(requested)),
        "template_weights": _normalize_weights(
            raw["template_weights"], template_ids, owner=f"topic {raw['id']!r}"
        ),
    }


def _unique(items: list[dict], kind: str) -> None:
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate {kind} ids in catalog")


def load_catalog(path: Path | None = None) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    catalog = path or _catalog_path()
    data = json.loads(catalog.read_text(encoding="utf-8"))
    raw_strategies = data.get("strategies")
    raw_templates = data.get("templates")
    raw_evidence_types = data.get("evidence_types")
    raw_topics = data.get("topics")
    if not isinstance(raw_strategies, list):
        raise ValueError(f"{catalog} must contain a 'strategies' list")
    if not isinstance(raw_templates, list) or not raw_templates:
        raise ValueError(f"{catalog} must contain a non-empty 'templates' list")
    if not isinstance(raw_evidence_types, list) or not raw_evidence_types:
        raise ValueError(f"{catalog} must contain a non-empty 'evidence_types' list")
    if not isinstance(raw_topics, list) or not raw_topics:
        raise ValueError(f"{catalog} must contain a non-empty 'topics' list")

    strategies = [_normalize_strategy(item) for item in raw_strategies]
    _unique(strategies, "strategy")
    strategy_ids = tuple(item["id"] for item in strategies)
    if set(strategy_ids) != set(BUILT_IN_STRATEGY_IDS):
        raise ValueError(
            "catalog strategies must contain exactly: " + ", ".join(BUILT_IN_STRATEGY_IDS)
        )
    by_strategy_id = {item["id"]: item for item in strategies}
    strategies = [by_strategy_id[strategy_id] for strategy_id in BUILT_IN_STRATEGY_IDS]

    evidence_types = [_normalize_evidence_type(item) for item in raw_evidence_types]
    _unique(evidence_types, "evidence type")
    evidence_ids = tuple(item["id"] for item in evidence_types)

    templates = [
        _normalize_template(item, strategy_ids, evidence_ids) for item in raw_templates
    ]
    _unique(templates, "template")
    template_ids = tuple(item["id"] for item in templates)

    topics = [
        _normalize_topic(item, evidence_ids, template_ids) for item in raw_topics
    ]
    _unique(topics, "topic")
    return strategies, templates, evidence_types, topics


STRATEGIES, TEMPLATES, EVIDENCE_TYPES, TOPICS = load_catalog()
STRATEGY_BY_ID = {item["id"]: item for item in STRATEGIES}
TEMPLATE_BY_ID = {item["id"]: item for item in TEMPLATES}
EVIDENCE_TYPE_BY_ID = {item["id"]: item for item in EVIDENCE_TYPES}
TOPIC_BY_ID = {item["id"]: item for item in TOPICS}


def weighted_template_schedule(topic: dict, count: int,
                               available_template_ids: set[str] | None = None) -> list[dict]:
    candidates = [
        template for template in TEMPLATES
        if topic["template_weights"][template["id"]] > 0
        and (available_template_ids is None or template["id"] in available_template_ids)
    ]
    if count <= 0 or not candidates:
        return []

    weights = [topic["template_weights"][template["id"]] for template in candidates]
    total = sum(weights)
    raw_allocations = [count * weight / total for weight in weights]
    allocations = [int(value) for value in raw_allocations]
    remaining = count - sum(allocations)
    order = sorted(
        range(len(candidates)),
        key=lambda i: (-(raw_allocations[i] - allocations[i]), -weights[i], i),
    )
    for index in order[:remaining]:
        allocations[index] += 1

    ranked = sorted(range(len(candidates)), key=lambda i: (-weights[i], i))
    schedule = []
    while any(allocations):
        for index in ranked:
            if allocations[index]:
                schedule.append(candidates[index])
                allocations[index] -= 1
    return schedule


def public_topics() -> list[dict]:
    return [
        {
            "id": topic["id"],
            "name": topic["name"],
            "description": topic["description"],
        }
        for topic in TOPICS
    ]
