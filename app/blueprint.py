"""Evidence-based assessment blueprint planning (PRD phases 1-2).

Sits between the Question Framework and question generation. Given the
assignment targets, the creator's Focus weights and framework settings, and the
project's evidence, it produces a *deterministic, LLM-free* blueprint: N planned
question slots, each bound to one or more Assessment Points, a Template, a
subject, and concrete evidence, with an expected difficulty band and a score
breakdown.

Pipeline (PRD §1):

    assignment targets      -> assessment-point distribution
    assessment points      -> template distribution
    point set x template x evidence
                            -> eligible candidates (hard gates)
                            -> scored + de-duplicated
                            -> N selected slots + unsupported report

Determinism: for the same snapshot, catalog hash, framework and seed the output
is identical. No question-generation LLM call happens here (PRD §12).
"""
from __future__ import annotations

import hashlib
import json
import random

from .assessment_catalog import (
    ASSESSMENT_POINT_BY_ID,
    ASSESSMENT_POINTS,
    TEMPLATE_BY_ID,
    TEMPLATES,
    TOPIC_BY_ID,
    catalog_hash,
    focus_point_fit,
    point_template_fit,
)
from .knowledge import EvidenceStore, expand_concepts, retrieval_tokens
from .question_planner import render_question_plan, template_bundle

# A rubric criterion worth many marks must not drown out technical coverage.
MARK_WEIGHT_CAP = 2.0
# Point weights below this are dropped from the distribution.
POINT_WEIGHT_FLOOR = 0.08
# Explicit target wording remains viable even when the selected Focus has no
# catalog fit, so cross-disciplinary requirements are ranked rather than erased.
FOCUS_LEXICAL_FLOOR = 0.35
# Soft diversity targets for a normal five-question run (PRD §7.8).
MIN_DISTINCT_POINTS = 3
MIN_DISTINCT_TEMPLATES = 2
MAX_POINTS_PER_SLOT = 2

# A balanced run aims for roughly half code and half conceptual questions.
BALANCED_CODE_SHARE = 0.5
# Penalty applied when a candidate's code class has already filled its quota.
CODE_QUOTA_PENALTY = 0.55


# --------------------------------------------------------------------------
# §7.1 assignment information -> assessment point distribution
# --------------------------------------------------------------------------

def _tokens(text: str) -> set[str]:
    return {t for t in retrieval_tokens(text) if len(t) > 2}


def _point_tokens(point: dict) -> set[str]:
    parts = [point.get("name", ""), point.get("description", ""), point.get("query", "")]
    parts.extend(str(v) for v in (point.get("difficulty_anchors") or {}).values())
    return _tokens(" ".join(parts))


def _target_tokens(target: dict) -> set[str]:
    text = f"{target.get('label', '')} {target.get('description', '')}"
    return _tokens(text + " " + " ".join(expand_concepts(text)))


def assessment_point_distribution(targets: list[dict],
                                  focus_areas: list[dict] | None = None) -> dict[str, float]:
    """Normalized Assessment Point weights implied by the assignment targets.

    Deterministic and local — no LLM (PRD §7.1). When no targets are supplied,
    falls back to a low-confidence prior derived from the selected Focus Areas
    (PRD §10.1).
    """
    scores: dict[str, float] = {}
    focus_weights = _normalized_focus_weights(focus_areas)
    for target in targets or []:
        t_tokens = _target_tokens(target)
        if not t_tokens:
            continue
        weight = min(float(target.get("weight", 1.0) or 1.0), MARK_WEIGHT_CAP)
        for point in ASSESSMENT_POINTS:
            overlap = len(t_tokens & _point_tokens(point))
            if overlap:
                if focus_weights:
                    focus_support = sum(
                        focus_weight * focus_point_fit(focus_id, point["id"])
                        for focus_id, focus_weight in focus_weights.items()
                    )
                    focus_factor = (
                        FOCUS_LEXICAL_FLOOR
                        + (1.0 - FOCUS_LEXICAL_FLOOR) * focus_support
                    )
                else:
                    focus_factor = 1.0
                scores[point["id"]] = (
                    scores.get(point["id"], 0.0)
                    + overlap * weight * focus_factor
                )

    if not scores:
        return _focus_prior(focus_areas)

    top = max(scores.values())
    return {
        pid: round(value / top, 4)
        for pid, value in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        if value / top >= POINT_WEIGHT_FLOOR
    }


def _focus_prior(focus_areas: list[dict] | None) -> dict[str, float]:
    """Low-confidence point prior from Focus weights alone (no assignment info)."""
    weights = _normalized_focus_weights(focus_areas)
    scores: dict[str, float] = {}
    for focus_id, focus_weight in weights.items():
        for point in ASSESSMENT_POINTS:
            fit = focus_point_fit(focus_id, point["id"])
            if fit > 0:
                scores[point["id"]] = scores.get(point["id"], 0.0) + focus_weight * fit
    if not scores:
        return {}
    top = max(scores.values())
    return {
        pid: round(v / top, 4)
        for pid, v in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        if v / top >= POINT_WEIGHT_FLOOR
    }


def _normalized_focus_weights(focus_areas: list[dict] | None) -> dict[str, float]:
    raw: dict[str, float] = {}
    for item in focus_areas or []:
        fid = str(item.get("id") or "")
        if fid in TOPIC_BY_ID:
            raw[fid] = max(0.0, float(item.get("weight", 1) or 0))
    total = sum(raw.values())
    if not total:
        return {}
    return {k: v / total for k, v in sorted(raw.items())}


# --------------------------------------------------------------------------
# §7.2 / §7.3 focus + template distributions
# --------------------------------------------------------------------------

def focus_contributions(point_id: str, focus_areas: list[dict] | None) -> list[tuple[str, float]]:
    """Selected Focus Areas contributing to a point, strongest first."""
    weights = _normalized_focus_weights(focus_areas)
    scored = [
        (fid, round(w * focus_point_fit(fid, point_id), 6))
        for fid, w in weights.items()
        if focus_point_fit(fid, point_id) > 0
    ]
    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return [item for item in scored if item[1] > 0]


def split_focus(point_id: str, focus_areas: list[dict] | None) -> tuple[str, list[str]]:
    """Primary Focus plus secondaries (>=50% of the primary contribution, PRD §7.2)."""
    contributions = focus_contributions(point_id, focus_areas)
    if not contributions:
        return "", []
    primary, top = contributions[0]
    secondary = [fid for fid, score in contributions[1:] if score >= 0.5 * top]
    return primary, secondary


def template_distribution(point_weights: dict[str, float]) -> dict[str, float]:
    """Normalized Template weights from Assessment Point compatibility."""
    scores: dict[str, float] = {}
    for template in TEMPLATES:
        point_part = sum(
            weight * point_template_fit(point_id, template["id"])
            for point_id, weight in point_weights.items()
        )
        if point_part > 0:
            scores[template["id"]] = point_part
    if not scores:
        return {}
    top = max(scores.values())
    return {
        tid: round(v / top, 4)
        for tid, v in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    }


# --------------------------------------------------------------------------
# §7.7 expected difficulty band
# --------------------------------------------------------------------------

def expected_difficulty(point: dict, template: dict, evidence: list[dict],
                        *, difficulty_min: int = 1, difficulty_max: int = 5,
                        project_specific: bool = True) -> dict:
    """Estimate a difficulty band from the plan, clamped to the point's range.

    Never copies a single creator-entered number onto every slot (PRD §7.7,
    AC 13). Returns ``{"min": int, "max": int}``, or an empty dict when the
    point's allowed range and the requested range do not overlap.
    """
    low, high = (point.get("difficulty_range") or [1, 5])[:2]
    low, high = int(low), int(high)

    # Signals that place the question within the point's own range. Each is
    # normalized to 0..1 and blended, so slots differ instead of collapsing onto
    # one band (PRD §7.7).
    hops = len({str(c.get("kind", "")) for c in evidence})
    reasoning = len(template.get("evidence_groups") or ()) or 1
    signal = (
        0.20 * (1.0 if project_specific else 0.0)
        + 0.25 * min(hops, 4) / 4
        + 0.20 * (1.0 if template.get("code_mode") != "none" else 0.0)
        + 0.20 * min(len(evidence), 6) / 6
        + 0.15 * min(reasoning, 3) / 3
    )
    span = max(0, high - low)
    est_low = low + int(round(span * signal))
    est_low = min(est_low, high)
    est_high = min(high, est_low + (1 if span else 0))

    # Intersect with the creator's requested target range.
    lo = max(est_low, int(difficulty_min))
    hi = min(est_high, int(difficulty_max))
    if lo > hi:
        # Requested range may still overlap the point's allowed range.
        lo = max(low, int(difficulty_min))
        hi = min(high, int(difficulty_max))
        if lo > hi:
            return {}
    return {"min": lo, "max": hi}


def expected_difficulty_for_points(points: list[dict], template: dict,
                                   evidence: list[dict], *, difficulty_min: int,
                                   difficulty_max: int) -> dict:
    """Return the common difficulty band for every Point covered by a slot."""
    bands = [
        expected_difficulty(
            point, template, evidence,
            difficulty_min=difficulty_min,
            difficulty_max=difficulty_max,
        )
        for point in points
    ]
    if not bands:
        return {}
    if any(not band for band in bands):
        return {}
    low = max(int(band["min"]) for band in bands)
    high = min(int(band["max"]) for band in bands)
    return {"min": low, "max": high} if low <= high else {}


# --------------------------------------------------------------------------
# §7.4 - §7.6 candidate enumeration with hard gates
# --------------------------------------------------------------------------

def _plan_key(point_ids: tuple[str, ...], template_id: str, subject: str,
              evidence_ids: list[str]) -> str:
    blob = json.dumps([point_ids, template_id, subject.casefold(),
                       sorted(evidence_ids)], sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


_BACKTICK_RE = __import__("re").compile(r"`([^`]+)`")


def _subject_of(plan: dict) -> str:
    """The planned subject: the bound entity/relationship shown in the stem.

    ``render_question_plan`` returns a rendered stem rather than raw slots, so the
    subject is read back from the stem's quoted identifiers — that is exactly the
    project-specific thing the question is about, and what repetition penalties
    must compare.
    """
    stem = str(plan.get("rendered_stem") or "")
    bits = _BACKTICK_RE.findall(stem)
    if bits:
        return " → ".join(b.strip() for b in bits[:2])
    return " ".join(stem.split()[:8])


def _point_groups(ranked_points: list[tuple[str, float]], point_index: int,
                  target_by_point: dict[str, dict],
                  focus_areas: list[dict] | None) -> list[tuple[str, ...]]:
    """Return one- and two-Point claims that share an actual assignment target.

    Points remain independent catalog entries. A pair exists only when this
    assignment maps both Points to the same requirement and both use the same
    primary Focus, so the pair represents a claim the student can genuinely be
    asked to reason about rather than a hand-maintained Point relationship.
    """
    point_id, _weight = ranked_points[point_index]
    primary_focus, _secondary = split_focus(point_id, focus_areas)
    groups = [(point_id,)]
    target = target_by_point.get(point_id)
    if not target or MAX_POINTS_PER_SLOT < 2:
        return groups

    for secondary_id, _secondary_weight in ranked_points[point_index + 1:]:
        secondary_target = target_by_point.get(secondary_id)
        secondary_focus, _unused = split_focus(secondary_id, focus_areas)
        if (
            secondary_target
            and secondary_target.get("id") == target.get("id")
            and secondary_focus == primary_focus
        ):
            groups.append((point_id, secondary_id))
            break
    return groups


def enumerate_candidates(evidence_store: EvidenceStore, *, point_weights: dict[str, float],
                         focus_areas: list[dict] | None, targets: list[dict] | None = None,
                         difficulty_min: int = 1,
                         difficulty_max: int = 5) -> tuple[list[dict], dict]:
    """Build every eligible candidate plan, plus rejection counts by reason.

    Hard gates run before ranking and before any LLM call (PRD §7.4).
    """
    rejects: dict[str, int] = {}

    def reject(reason: str) -> None:
        rejects[reason] = rejects.get(reason, 0) + 1

    target_by_point = _targets_by_point(targets)
    candidates: list[dict] = []
    seen: set[str] = set()

    ranked_points = [
        (point_id, point_weight)
        for point_id, point_weight in sorted(
            point_weights.items(), key=lambda item: (-item[1], item[0])
        )
        if point_id in ASSESSMENT_POINT_BY_ID and point_weight > 0
    ]

    for point_index, (point_id, point_weight) in enumerate(ranked_points):
        point = ASSESSMENT_POINT_BY_ID[point_id]
        if point_weight <= 0:
            reject("zero_point_weight")
            continue
        primary_focus, secondary = split_focus(point_id, focus_areas)
        if not primary_focus:
            reject("focus_point_incompatible")
            continue
        topic = TOPIC_BY_ID[primary_focus]
        target = target_by_point.get(point_id)

        for point_ids in _point_groups(
            ranked_points, point_index, target_by_point, focus_areas
        ):
            points = [ASSESSMENT_POINT_BY_ID[item] for item in point_ids]
            weights = [point_weights[item] for item in point_ids]
            combined_query = " ".join(item.get("query", "") for item in points)

            for template in TEMPLATES:
                pt_fits = [point_template_fit(item, template["id"]) for item in point_ids]
                pt_fit = min(pt_fits)
                if pt_fit <= 0:
                    reject("point_template_incompatible")
                    continue

                evidence, missing = template_bundle(
                    evidence_store, topic, template, combined_query)
                if missing:
                    reject("required_evidence_missing")
                    continue
                if not all(_evidence_types_overlap(item, evidence) for item in points):
                    reject("evidence_type_mismatch")
                    continue

                plan, _why = render_question_plan(template, topic, target, evidence)
                if not plan:
                    reject("variables_unresolved")
                    continue

                band = expected_difficulty_for_points(
                    points, template, evidence,
                    difficulty_min=difficulty_min, difficulty_max=difficulty_max)
                if not band:
                    reject("difficulty_out_of_range")
                    continue

                subject = _subject_of(plan)
                evidence_ids = [str(c.get("id", "")) for c in evidence if c.get("id")]
                # A pair must produce a distinct tested claim. Otherwise it would
                # merely label an existing one-Point question as broader coverage.
                key = _plan_key(point_ids, template["id"], subject, evidence_ids)
                claim = str(plan.get("plan_key") or "")
                if key in seen or (claim and claim in seen):
                    reject("duplicate_plan_key")
                    continue
                seen.add(key)
                if claim:
                    seen.add(claim)

                evidence_fit = sum(
                    _evidence_fit(item, evidence, target) for item in points
                ) / len(points)
                focus_fit = sum(
                    focus_point_fit(primary_focus, item) for item in point_ids
                ) / len(point_ids)
                relevance = (
                    (sum(weights) / len(weights)) * focus_fit * pt_fit
                    * evidence_fit * (1.0 if target else 0.6)
                )
                candidates.append({
                    "assessment_point_id": point_id,
                    "assessment_point_ids": list(point_ids),
                    "template_id": template["id"],
                    "primary_focus_id": primary_focus,
                    "secondary_focus_ids": secondary,
                    "variables": {k: v for k, v in plan.items() if isinstance(v, str)},
                    "subject": subject,
                    "planned_stem": str(plan.get("rendered_stem") or ""),
                    "code_mode": template.get("code_mode", "none"),
                    "shows_code": template.get("code_mode", "none") != "none",
                    "evidence_ids": evidence_ids,
                    "target_ids": [target["id"]] if target else [],
                    "expected_difficulty": band,
                    "relevance": round(relevance, 6),
                    "score_breakdown": {
                        "assignment": round(sum(weights) / len(weights), 4),
                        "focus_point": round(focus_fit, 4),
                        "point_template": round(pt_fit, 4),
                        "evidence": round(evidence_fit, 4),
                        "alignment": 1.0 if target else 0.6,
                    },
                    "reason_selected": _reason(points, target),
                    "plan_key": key,
                })

    candidates.sort(key=lambda c: (-c["relevance"], c["assessment_point_id"], c["template_id"]))
    return candidates, rejects


def _targets_by_point(targets: list[dict] | None) -> dict[str, dict]:
    """Best-matching assignment target per Assessment Point (for explanations)."""
    best: dict[str, tuple[int, dict]] = {}
    for target in targets or []:
        t_tokens = _target_tokens(target)
        for point in ASSESSMENT_POINTS:
            overlap = len(t_tokens & _point_tokens(point))
            if overlap and overlap > best.get(point["id"], (0, None))[0]:
                best[point["id"]] = (overlap, target)
    return {pid: target for pid, (_n, target) in best.items()}


def _evidence_types_overlap(point: dict, evidence: list[dict]) -> bool:
    allowed = set(point.get("evidence_types") or [])
    if not allowed:
        return True
    from .knowledge import evidence_types_for_chunk
    for chunk in evidence:
        if allowed & set(evidence_types_for_chunk(chunk)):
            return True
    return False


def _evidence_fit(point: dict, evidence: list[dict], target: dict | None) -> float:
    """Ranking-only evidence quality in 0..1 (required evidence is a gate)."""
    if not evidence:
        return 0.0
    from .knowledge import evidence_types_for_chunk
    allowed = set(point.get("evidence_types") or [])
    types = set()
    for chunk in evidence:
        types |= set(evidence_types_for_chunk(chunk))
    overlap = len(allowed & types) / len(allowed) if allowed else 0.5
    depth = min(len(evidence), 4) / 4
    linked = 1.0 if (target and _target_tokens(target) & _tokens(
        " ".join(str(c.get("title", "")) for c in evidence))) else 0.7
    return round(max(0.05, 0.5 * overlap + 0.3 * depth + 0.2 * linked), 4)


def _reason(points: list[dict], target: dict | None) -> str:
    if target:
        label = str(target.get("label") or target.get("description") or "").strip()
        return f"Assignment requires: {label[:120]}"
    names = " + ".join(point.get("name", point["id"]) for point in points)
    return f"Selected Focus covers {names}"


# --------------------------------------------------------------------------
# §7.8 selecting N plans with a diversity penalty
# --------------------------------------------------------------------------

def repetition_penalty(candidate: dict, chosen: list[dict]) -> float:
    """Penalty for Points and evidence already covered by selected plans."""
    penalty = 0.0
    candidate_points = set(candidate.get("assessment_point_ids") or [
        candidate["assessment_point_id"]
    ])
    for other in chosen:
        other_points = set(other.get("assessment_point_ids") or [
            other["assessment_point_id"]
        ])
        shared_points = candidate_points & other_points
        same_point = bool(shared_points)
        same_template = candidate["template_id"] == other["template_id"]
        if same_point:
            penalty += 0.35 * len(shared_points)
        if same_template:
            penalty += 0.15
        if same_point and same_template:
            penalty += 0.25
        subject = candidate["subject"].casefold()
        if subject and subject == other["subject"].casefold():
            penalty += 0.40
        shared = set(candidate["evidence_ids"]) & set(other["evidence_ids"])
        if shared:
            penalty += 0.10 * min(len(shared), 3)
    return round(penalty, 4)


def _code_quota(count: int) -> int:
    """How many of the ``count`` questions should show code."""
    return int(round(count * BALANCED_CODE_SHARE))


def interleave_by_code(slots: list[dict]) -> list[dict]:
    """Alternate code and no-code questions so neither kind clusters together.

    Relative order within each kind (i.e. relevance order) is preserved; only the
    interleaving changes. Slot indexes are renumbered to the final order.
    """
    code = [s for s in slots if s.get("shows_code")]
    plain = [s for s in slots if not s.get("shows_code")]
    # Start with whichever kind has more, so the leftovers spread out evenly.
    first, second = (code, plain) if len(code) >= len(plain) else (plain, code)
    out: list[dict] = []
    for i in range(max(len(first), len(second))):
        if i < len(first):
            out.append(first[i])
        if i < len(second):
            out.append(second[i])
    for index, slot in enumerate(out):
        slot["index"] = index
    return out


def select_plans(candidates: list[dict], count: int, *, seed: int = 0) -> tuple[list[dict], list[str]]:
    """Relevance-first greedy selection with diversity and code-mix penalties.

    Returns ``(slots, warnings)``. Soft diversity targets may be relaxed on
    sparse repositories, and every relaxation is reported (PRD §7.8).
    """
    rng = random.Random(seed)
    pool = list(candidates)
    chosen: list[dict] = []
    warnings: list[str] = []
    code_quota = _code_quota(count)
    plain_quota = count - code_quota

    while pool and len(chosen) < count:
        picked_code = sum(1 for c in chosen if c.get("shows_code"))
        picked_plain = len(chosen) - picked_code
        scored = []
        for cand in pool:
            penalty = repetition_penalty(cand, chosen)
            # Soft quota: once one kind has had its share, deprioritise it so the
            # run keeps the requested code/concept mix instead of one kind
            # winning on relevance alone. Still selectable if nothing else fits.
            if cand.get("shows_code") and picked_code >= code_quota:
                penalty += CODE_QUOTA_PENALTY
            elif not cand.get("shows_code") and picked_plain >= plain_quota:
                penalty += CODE_QUOTA_PENALTY
            scored.append((round(cand["relevance"] - penalty, 6), cand))
        best = max(s for s, _c in scored)
        tied = [c for s, c in scored if s == best]
        # deterministic tie-break: stable key, then seeded choice for equal keys
        tied.sort(key=lambda c: (c["assessment_point_id"], c["template_id"], c["plan_key"]))
        pick = tied[0] if len(tied) == 1 else tied[rng.randrange(len(tied))]
        pick = dict(pick)
        pick["index"] = len(chosen)
        pick["repetition_penalty"] = repetition_penalty(pick, chosen)
        pick["score"] = round(pick["relevance"] - pick["repetition_penalty"], 6)
        pick["score_breakdown"] = {**pick["score_breakdown"],
                                   "repetition_penalty": pick["repetition_penalty"]}
        chosen.append(pick)
        pool = [c for c in pool if c["plan_key"] != pick["plan_key"]]

    # Spread code and no-code questions through the paper rather than clustering.
    chosen = interleave_by_code(chosen)

    if len(chosen) < count:
        warnings.append(
            f"only {len(chosen)} evidence-supported plans available (requested {count})")
    if chosen:
        picked_code = sum(1 for c in chosen if c.get("shows_code"))
        if code_quota and not picked_code:
            warnings.append(
                f"no code-based question had sufficient evidence (wanted {code_quota})")
        elif plain_quota and picked_code == len(chosen):
            warnings.append(
                f"every planned question shows code (wanted {plain_quota} without code)")
        points = {
            point_id
            for candidate in chosen
            for point_id in candidate.get("assessment_point_ids", [
                candidate["assessment_point_id"]
            ])
        }
        templates = {c["template_id"] for c in chosen}
        if count >= 5 and len(points) < MIN_DISTINCT_POINTS:
            warnings.append(
                f"diversity relaxed: {len(points)} assessment point(s), "
                f"target {MIN_DISTINCT_POINTS}")
        if count >= 5 and len(templates) < MIN_DISTINCT_TEMPLATES:
            warnings.append(
                f"diversity relaxed: {len(templates)} template(s), "
                f"target {MIN_DISTINCT_TEMPLATES}")
    return chosen, warnings


# --------------------------------------------------------------------------
# top level
# --------------------------------------------------------------------------

def unsupported_points(point_weights: dict[str, float], candidates: list[dict],
                       limit: int = 8) -> list[dict]:
    """High-weight Assessment Points with no eligible plan, with a reason."""
    covered = {
        point_id
        for candidate in candidates
        for point_id in candidate.get("assessment_point_ids", [
            candidate["assessment_point_id"]
        ])
    }
    out = []
    for pid, weight in sorted(point_weights.items(), key=lambda kv: (-kv[1], kv[0])):
        if pid in covered:
            continue
        point = ASSESSMENT_POINT_BY_ID.get(pid)
        if not point:
            continue
        out.append({
            "assessment_point_id": pid,
            "name": point.get("name", pid),
            "weight": round(weight, 4),
            "reason": "no template, variable binding, or project evidence available",
        })
        if len(out) >= limit:
            break
    return out


def build_blueprint(evidence_store: EvidenceStore, *, targets: list[dict] | None,
                    focus_areas: list[dict] | None, snapshot_id: str,
                    num_questions: int = 5, difficulty_min: int = 1,
                    difficulty_max: int = 5,
                    seed: int = 0) -> dict:
    """Produce a full blueprint preview. Deterministic; performs no LLM calls."""
    point_weights = assessment_point_distribution(targets or [], focus_areas)
    templates = template_distribution(point_weights)

    candidates, rejects = enumerate_candidates(
        evidence_store, point_weights=point_weights, focus_areas=focus_areas,
        targets=targets, difficulty_min=difficulty_min,
        difficulty_max=difficulty_max)
    planned, warnings = select_plans(candidates, num_questions, seed=seed)

    if not targets:
        warnings.insert(0, "No assignment scope supplied — Assessment Points inferred "
                           "from Focus Areas only (low confidence)")
    if not templates:
        warnings.append("no template is compatible with the selected framework")

    return {
        "status": "preview",
        "snapshot_id": snapshot_id,
        "catalog_hash": catalog_hash(),
        "requested": {
            "num_questions": num_questions,
            "difficulty_min": difficulty_min,
            "difficulty_max": difficulty_max,
            "focus_areas": focus_areas or [],
            "seed": seed,
        },
        "assessment_point_distribution": point_weights,
        "template_distribution": templates,
        "planned": planned,
        "unsupported": unsupported_points(point_weights, candidates),
        "warnings": warnings,
        "gate_rejections": dict(sorted(rejects.items())),
    }


def plot_points(planned: list[dict]) -> list[dict]:
    """Blueprint plot series: x = Assessment Point, y = difficulty, colour = Template."""
    out = []
    for slot in planned:
        band = slot.get("expected_difficulty") or {}
        point_ids = slot.get("assessment_point_ids") or [slot["assessment_point_id"]]
        point_names = [
            ASSESSMENT_POINT_BY_ID.get(point_id, {}).get("name", point_id)
            for point_id in point_ids
        ]
        template = TEMPLATE_BY_ID.get(slot["template_id"], {})
        out.append({
            "index": slot.get("index", 0),
            "assessment_point_id": " + ".join(point_ids),
            "assessment_point_ids": point_ids,
            "assessment_point": " + ".join(point_names),
            "template_id": slot["template_id"],
            "template": template.get("name", slot["template_id"]),
            "y_min": band.get("min"),
            "y_max": band.get("max"),
        })
    return out
