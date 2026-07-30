"""Validated assessment catalog for focus-driven Local LLM generation."""
from __future__ import annotations

import hashlib
import json
import os
import string
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PATH = _ROOT / "assessment_catalog.json"
_CATALOG_PATH = Path(os.environ.get("REPOPROOF_ASSESSMENT_CATALOG", str(_DEFAULT_PATH)))

SLOT_SOURCES = frozenset({
    "target_or_topic",
    "evidence_entity",
    "relation_source",
    "relation_target",
    "code_condition",
    "code_mutation",
    "target_or_requirement",
})
ENTITY_TYPES = frozenset({
    "imported_library",
    "api_method",
    "component",
    "function",
    "class",
    "data_store",
    "state",
})
CODE_MODES = frozenset({"none", "required", "insertion"})


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


def _normalize_slot(raw: object, *, owner: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"{owner} must be an object")
    source = _clean_id(raw.get("source"), "slot source")
    if source not in SLOT_SOURCES:
        raise ValueError(f"{owner} has unknown source {source!r}")
    entity_types = [
        _clean_id(value, "entity type") for value in raw.get("types", [])
    ]
    unknown = sorted(set(entity_types) - ENTITY_TYPES)
    if unknown:
        raise ValueError(f"{owner} references unknown entity types: {unknown}")
    if source in {"evidence_entity", "relation_source", "relation_target"} and not entity_types:
        raise ValueError(f"{owner} needs at least one entity type")
    return {
        "source": source,
        "types": list(dict.fromkeys(entity_types)),
        "related_to": str(raw.get("related_to", "")).strip(),
    }


def _normalize_assessment_point(raw: dict, evidence_ids: tuple[str, ...]) -> dict:
    _required(
        raw,
        (
            "id", "name", "description", "difficulty_range",
            "difficulty_anchors", "query", "evidence_types",
        ),
        "assessment point",
    )
    difficulty_range = raw["difficulty_range"]
    if (
        not isinstance(difficulty_range, list)
        or len(difficulty_range) != 2
        or not all(isinstance(value, int) for value in difficulty_range)
    ):
        raise ValueError(
            f"assessment point {raw['id']!r} difficulty_range must be [min, max]"
        )
    minimum, maximum = difficulty_range
    if not 1 <= minimum <= maximum <= 5:
        raise ValueError(
            f"assessment point {raw['id']!r} difficulty_range must stay within 1-5"
        )
    anchors = raw["difficulty_anchors"]
    if not isinstance(anchors, dict):
        raise ValueError(
            f"assessment point {raw['id']!r} difficulty_anchors must be an object"
        )
    expected_levels = {str(level) for level in range(minimum, maximum + 1)}
    if set(anchors) != expected_levels:
        raise ValueError(
            f"assessment point {raw['id']!r} difficulty_anchors must define "
            f"exactly levels {sorted(expected_levels)}"
        )
    requested = [
        _clean_id(value, "assessment point evidence type")
        for value in raw["evidence_types"]
    ]
    if not requested:
        raise ValueError(
            f"assessment point {raw['id']!r} needs at least one evidence type"
        )
    unknown = sorted(set(requested) - set(evidence_ids))
    if unknown:
        raise ValueError(
            f"assessment point {raw['id']!r} references unknown evidence types: {unknown}"
        )
    return {
        "id": _clean_id(raw["id"], "assessment point"),
        "name": str(raw["name"]).strip(),
        "description": str(raw["description"]).strip(),
        "difficulty_range": [minimum, maximum],
        "difficulty_anchors": {
            str(level): str(anchors[str(level)]).strip()
            for level in range(minimum, maximum + 1)
        },
        "query": str(raw["query"]).strip(),
        "evidence_types": list(dict.fromkeys(requested)),
    }


def _normalize_template(raw: dict, evidence_ids: tuple[str, ...]) -> dict:
    _required(
        raw,
        (
            "id", "name", "reasoning_prompt", "stem_frames", "option_task",
            "slots", "code_mode", "query", "evidence",
        ),
        "template",
    )
    frames = [
        str(frame).strip()
        for frame in raw["stem_frames"]
        if str(frame).strip()
    ] if isinstance(raw["stem_frames"], list) else []
    if not frames:
        raise ValueError(f"template {raw['id']!r} needs at least one stem frame")
    raw_slots = raw["slots"]
    if not isinstance(raw_slots, dict) or not raw_slots:
        raise ValueError(f"template {raw['id']!r} needs typed slots")
    slots = {
        _clean_id(name, "slot name"): _normalize_slot(
            value, owner=f"template {raw['id']!r} slot {name!r}"
        )
        for name, value in raw_slots.items()
    }
    for name, slot in slots.items():
        related_to = slot["related_to"]
        if related_to and related_to not in slots:
            raise ValueError(
                f"template {raw['id']!r} slot {name!r} relates to unknown slot "
                f"{related_to!r}"
            )
    for frame in frames:
        fields = {
            field_name
            for _, field_name, _, _ in string.Formatter().parse(frame)
            if field_name
        }
        unknown_fields = sorted(fields - set(slots))
        if unknown_fields:
            raise ValueError(
                f"template {raw['id']!r} frame references unknown slots: {unknown_fields}"
            )
    code_mode = str(raw["code_mode"]).strip()
    if code_mode not in CODE_MODES:
        raise ValueError(
            f"template {raw['id']!r} code_mode must be one of {sorted(CODE_MODES)}"
        )
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
        "reasoning_prompt": str(raw["reasoning_prompt"]).strip(),
        "stem_frames": frames,
        "option_task": str(raw["option_task"]).strip(),
        "slots": slots,
        "code_mode": code_mode,
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
    raw_templates = data.get("templates")
    raw_evidence_types = data.get("evidence_types")
    raw_assessment_points = data.get("assessment_points")
    raw_topics = data.get("topics")
    if not isinstance(raw_templates, list) or not raw_templates:
        raise ValueError(f"{catalog} must contain a non-empty 'templates' list")
    if not isinstance(raw_evidence_types, list) or not raw_evidence_types:
        raise ValueError(f"{catalog} must contain a non-empty 'evidence_types' list")
    if not isinstance(raw_assessment_points, list) or not raw_assessment_points:
        raise ValueError(f"{catalog} must contain a non-empty 'assessment_points' list")
    if not isinstance(raw_topics, list) or not raw_topics:
        raise ValueError(f"{catalog} must contain a non-empty 'topics' list")

    evidence_types = [_normalize_evidence_type(item) for item in raw_evidence_types]
    _unique(evidence_types, "evidence type")
    evidence_ids = tuple(item["id"] for item in evidence_types)

    assessment_points = [
        _normalize_assessment_point(item, evidence_ids)
        for item in raw_assessment_points
    ]
    _unique(assessment_points, "assessment point")

    templates = [
        _normalize_template(item, evidence_ids) for item in raw_templates
    ]
    _unique(templates, "template")
    template_ids = tuple(item["id"] for item in templates)

    topics = [
        _normalize_topic(item, evidence_ids, template_ids) for item in raw_topics
    ]
    _unique(topics, "topic")

    point_ids = tuple(item["id"] for item in assessment_points)
    topic_ids = tuple(item["id"] for item in topics)
    focus_point = _normalize_matrix(
        data.get("focus_point_weights"), topic_ids, point_ids,
        owner="focus_point_weights", row_kind="focus", col_kind="assessment point")
    point_template = _normalize_matrix(
        data.get("point_template_weights"), point_ids, template_ids,
        owner="point_template_weights", row_kind="assessment point", col_kind="template")
    policy = _normalize_framework_policy(data.get("framework_template_policy"))
    return (templates, evidence_types, assessment_points, topics,
            focus_point, point_template, policy)


def _normalize_matrix(raw: object, row_ids: tuple[str, ...], col_ids: tuple[str, ...],
                      *, owner: str, row_kind: str, col_kind: str) -> dict[str, dict[str, float]]:
    """Validate a sparse compatibility matrix.

    Unknown row/column IDs fail startup (PRD AC 3). Missing entries are simply
    absent and are read as 0.0 by the accessors below — 0.0 means "prohibited",
    not "low score" (PRD 7.5).
    """
    if raw is None:
        raise ValueError(f"catalog must contain '{owner}'")
    if not isinstance(raw, dict):
        raise ValueError(f"'{owner}' must be an object")
    rows, cols = set(row_ids), set(col_ids)
    out: dict[str, dict[str, float]] = {}
    for row_id, row in raw.items():
        if row_id not in rows:
            raise ValueError(f"'{owner}' has unknown {row_kind} id {row_id!r}")
        if not isinstance(row, dict):
            raise ValueError(f"'{owner}[{row_id}]' must be an object")
        clean: dict[str, float] = {}
        for col_id, weight in row.items():
            if col_id not in cols:
                raise ValueError(f"'{owner}[{row_id}]' has unknown {col_kind} id {col_id!r}")
            try:
                value = float(weight)
            except (TypeError, ValueError):
                raise ValueError(f"'{owner}[{row_id}][{col_id}]' must be a number") from None
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"'{owner}[{row_id}][{col_id}]' must be within 0.0-1.0")
            if value > 0:
                clean[col_id] = value
        out[row_id] = clean
    return out


def _normalize_framework_policy(raw: object) -> dict:
    """Validate the Framework x Template emphasis policy (PRD 5.1)."""
    if not isinstance(raw, dict):
        raise ValueError("catalog must contain 'framework_template_policy'")
    fit = raw.get("emphasis_fit")
    if not isinstance(fit, dict) or not fit:
        raise ValueError("'framework_template_policy.emphasis_fit' must be a non-empty object")
    out: dict[str, dict[str, float]] = {}
    for emphasis, modes in fit.items():
        if not isinstance(modes, dict):
            raise ValueError(f"emphasis_fit[{emphasis!r}] must be an object")
        clean: dict[str, float] = {}
        for mode, weight in modes.items():
            if mode not in CODE_MODES:
                raise ValueError(f"emphasis_fit[{emphasis!r}] has unknown code mode {mode!r}")
            value = float(weight)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"emphasis_fit[{emphasis!r}][{mode!r}] must be within 0.0-1.0")
            clean[mode] = value
        missing = CODE_MODES - set(clean)
        if missing:
            raise ValueError(f"emphasis_fit[{emphasis!r}] missing code modes {sorted(missing)}")
        out[emphasis] = clean
    return {"emphasis_fit": out}


(TEMPLATES, EVIDENCE_TYPES, ASSESSMENT_POINTS, TOPICS,
 FOCUS_POINT_WEIGHTS, POINT_TEMPLATE_WEIGHTS, FRAMEWORK_TEMPLATE_POLICY) = load_catalog()
TEMPLATE_BY_ID = {item["id"]: item for item in TEMPLATES}
EVIDENCE_TYPE_BY_ID = {item["id"]: item for item in EVIDENCE_TYPES}
ASSESSMENT_POINT_BY_ID = {item["id"]: item for item in ASSESSMENT_POINTS}
TOPIC_BY_ID = {item["id"]: item for item in TOPICS}
EMPHASIS_MODES = tuple(FRAMEWORK_TEMPLATE_POLICY["emphasis_fit"])


def focus_point_fit(focus_id: str, point_id: str) -> float:
    """Focus x Assessment Point compatibility. 0.0 = not part of this Focus."""
    return FOCUS_POINT_WEIGHTS.get(focus_id, {}).get(point_id, 0.0)


def point_template_fit(point_id: str, template_id: str) -> float:
    """Assessment Point x Template compatibility. 0.0 = must not be used."""
    return POINT_TEMPLATE_WEIGHTS.get(point_id, {}).get(template_id, 0.0)


def framework_template_fit(template: dict, *, emphasis: str = "balanced",
                           allow_code: bool = True) -> float:
    """Framework x Template fit.

    Returns 0.0 (a hard prohibition) when the template needs code but the
    framework disallows it — AC 9. Otherwise scores the emphasis preference.
    """
    mode = template.get("code_mode", "none")
    if not allow_code and mode != "none":
        return 0.0
    table = FRAMEWORK_TEMPLATE_POLICY["emphasis_fit"]
    return table.get(emphasis, table.get("balanced", {})).get(mode, 0.0)


def catalog_hash() -> str:
    """Stable hash of the planning-relevant catalog, for freezing blueprints.

    A change here must invalidate an unconfirmed preview (PRD 10.4).
    """
    payload = {
        "templates": [
            {"id": t["id"], "code_mode": t.get("code_mode", "none")} for t in TEMPLATES
        ],
        "evidence_types": [e["id"] for e in EVIDENCE_TYPES],
        "assessment_points": [
            {"id": p["id"], "difficulty_range": p.get("difficulty_range"),
             "evidence_types": p.get("evidence_types")}
            for p in ASSESSMENT_POINTS
        ],
        "topics": [t["id"] for t in TOPICS],
        "focus_point_weights": FOCUS_POINT_WEIGHTS,
        "point_template_weights": POINT_TEMPLATE_WEIGHTS,
        "framework_template_policy": FRAMEWORK_TEMPLATE_POLICY,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


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
