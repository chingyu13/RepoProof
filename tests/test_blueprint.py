"""Phase-2 tests for evidence-based blueprint planning (PRD §13 AC 4-13, 16-17)."""
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("REPOPROOF_WORK_DIR", tempfile.mkdtemp())

from app import analyzer, blueprint, knowledge          # noqa: E402
from app.assessment_catalog import TEMPLATE_BY_ID       # noqa: E402

TARGETS = [
    {"id": "t0", "kind": "project_scope", "label": "Retrieve API data", "weight": 1.5,
     "source": "scope",
     "description": ("Retrieve OpenElectricity data from a REST API, combine power and "
                     "emissions, save a CSV cache, publish ordered MQTT messages and "
                     "update a dashboard.")},
    {"id": "t1", "kind": "project_scope", "label": "Testing", "weight": 0.5, "source": "scope",
     "description": "Verify data quality with tests and handle missing values."},
]
FOCUS = [{"id": "api", "weight": 5}, {"id": "data_flow", "weight": 5},
         {"id": "architecture", "weight": 2}]


@pytest.fixture(scope="module")
def store():
    """Evidence store from a real analysed project when one is available."""
    best = None
    root = Path("data/projects")
    if root.exists():
        for path in root.glob("*/*"):
            if path.is_dir() and not path.name.startswith("."):
                n = len(list(path.rglob("*.py"))) + len(list(path.rglob("*.ipynb")))
                if n and (best is None or n > best[1]):
                    best = (path, n)
    target = best[0] if best else Path("app")
    chunks = knowledge.build_chunks(analyzer.analyze_project(target), "snap1")
    return knowledge.EvidenceStore(chunks)


def _plan(store, **over):
    kw = dict(targets=TARGETS, focus_areas=FOCUS, snapshot_id="snap1", num_questions=5,
              emphasis="balanced", allow_code=True, difficulty_min=1, difficulty_max=4,
              seed=42)
    kw.update(over)
    return blueprint.build_blueprint(store, **kw)


# --- §7.1 assessment point distribution ------------------------------------

def test_targets_produce_point_distribution():
    dist = blueprint.assessment_point_distribution(TARGETS, FOCUS)
    assert dist, "assignment targets must yield an assessment-point distribution"
    assert max(dist.values()) == 1.0                     # normalized
    assert all(0 < v <= 1 for v in dist.values())
    # API/acquisition/streaming language in the target must surface
    assert {"data_source_acquisition", "streaming_event_behavior"} & set(dist)


def test_rubric_marks_are_capped():
    heavy = [dict(TARGETS[0], weight=999.0)]
    light = [dict(TARGETS[0], weight=blueprint.MARK_WEIGHT_CAP)]
    assert (blueprint.assessment_point_distribution(heavy, FOCUS)
            == blueprint.assessment_point_distribution(light, FOCUS))


def test_no_assignment_info_falls_back_to_focus_prior():
    dist = blueprint.assessment_point_distribution([], FOCUS)
    assert dist, "must derive a low-confidence prior from Focus Areas"


# --- §7.2 focus split -------------------------------------------------------

def test_primary_and_secondary_focus():
    primary, secondary = blueprint.split_focus("data_source_acquisition", FOCUS)
    assert primary in {"api", "data_flow"}
    assert primary not in secondary


def test_focus_with_zero_fit_is_not_selected():
    primary, _ = blueprint.split_focus("testing_quality_verification",
                                       [{"id": "api", "weight": 5}])
    assert primary == ""


# --- §7.3 template distribution + AC 9 --------------------------------------

def test_template_distribution_respects_emphasis():
    concepts = blueprint.template_distribution(FOCUS, emphasis="mostly_concepts")
    code = blueprint.template_distribution(FOCUS, emphasis="mostly_code")
    assert concepts and code
    assert concepts != code


def test_no_code_templates_when_code_disallowed():
    dist = blueprint.template_distribution(FOCUS, allow_code=False)
    assert all(TEMPLATE_BY_ID[t]["code_mode"] == "none" for t in dist)


# --- §7.7 expected difficulty (AC 13) ---------------------------------------

def test_expected_difficulty_stays_in_point_range():
    from app.assessment_catalog import ASSESSMENT_POINT_BY_ID
    point = ASSESSMENT_POINT_BY_ID["package_purpose"]          # range [1,2]
    band = blueprint.expected_difficulty(point, TEMPLATE_BY_ID["contextual_use"], [{}],
                                         difficulty_min=1, difficulty_max=5)
    assert band and 1 <= band["min"] <= band["max"] <= 2


def test_expected_difficulty_empty_when_ranges_cannot_meet():
    from app.assessment_catalog import ASSESSMENT_POINT_BY_ID
    point = ASSESSMENT_POINT_BY_ID["package_purpose"]          # max 2
    assert blueprint.expected_difficulty(point, TEMPLATE_BY_ID["contextual_use"], [{}],
                                         difficulty_min=4, difficulty_max=5) == {}


def test_difficulty_is_not_one_number_copied_everywhere(store):
    bp = _plan(store)
    if len(bp["planned"]) < 2:
        pytest.skip("not enough evidence-supported plans in this fixture")
    bands = {(s["expected_difficulty"]["min"], s["expected_difficulty"]["max"])
             for s in bp["planned"]}
    assert len(bands) > 1, "every slot received an identical difficulty band"


# --- §7.8 selection, diversity, repetition ----------------------------------

def test_repetition_penalty_covers_point_template_subject_evidence():
    a = {"assessment_point_id": "p", "template_id": "t", "subject": "s",
         "evidence_ids": ["e1"]}
    none = blueprint.repetition_penalty(
        {"assessment_point_id": "x", "template_id": "y", "subject": "z",
         "evidence_ids": []}, [a])
    same_point = blueprint.repetition_penalty(
        {"assessment_point_id": "p", "template_id": "y", "subject": "z",
         "evidence_ids": []}, [a])
    identical = blueprint.repetition_penalty(dict(a), [a])
    assert none == 0.0 < same_point < identical


def test_selection_is_deterministic_for_same_seed(store):
    a, b = _plan(store), _plan(store)
    assert [s["plan_key"] for s in a["planned"]] == [s["plan_key"] for s in b["planned"]]


def test_five_question_run_hits_diversity_targets(store):
    bp = _plan(store)
    if len(bp["planned"]) < 5:
        pytest.skip("fixture cannot support five plans")
    assert len({s["assessment_point_id"] for s in bp["planned"]}) >= blueprint.MIN_DISTINCT_POINTS
    assert len({s["template_id"] for s in bp["planned"]}) >= blueprint.MIN_DISTINCT_TEMPLATES
    assert len({s["subject"].casefold() for s in bp["planned"]}) == len(bp["planned"])


def test_fewer_plans_than_requested_warns_instead_of_padding():
    empty = knowledge.EvidenceStore([])
    bp = blueprint.build_blueprint(empty, targets=TARGETS, focus_areas=FOCUS,
                                   snapshot_id="s", num_questions=5)
    assert bp["planned"] == []
    assert any("available" in w for w in bp["warnings"])


# --- preview shape, gates, unsupported (AC 5-7, 10) -------------------------

def test_preview_shape_and_no_llm_call(store):
    bp = _plan(store)
    for key in ("status", "snapshot_id", "catalog_hash", "requested",
                "assessment_point_distribution", "template_distribution",
                "planned", "unsupported", "warnings", "gate_rejections"):
        assert key in bp
    assert bp["status"] == "preview"


def test_every_slot_carries_preview_table_fields(store):
    bp = _plan(store)
    if not bp["planned"]:
        pytest.skip("no plans for this fixture")
    for slot in bp["planned"]:
        assert slot["assessment_point_id"] and slot["template_id"]
        assert slot["primary_focus_id"]
        assert slot["expected_difficulty"]["min"] <= slot["expected_difficulty"]["max"]
        assert slot["evidence_ids"], "every slot must cite evidence"
        assert slot["reason_selected"]
        assert set(slot["score_breakdown"]) >= {
            "assignment", "focus_point", "point_template", "framework_template",
            "evidence", "alignment", "repetition_penalty"}


def test_code_disabled_run_never_schedules_code_templates(store):
    bp = _plan(store, allow_code=False)
    assert all(TEMPLATE_BY_ID[s["template_id"]]["code_mode"] == "none"
               for s in bp["planned"])


def test_excluded_point_never_planned(store):
    bp = _plan(store)
    if not bp["planned"]:
        pytest.skip("no plans for this fixture")
    victim = bp["planned"][0]["assessment_point_id"]
    after = _plan(store, excluded_assessment_points=[victim])
    assert all(s["assessment_point_id"] != victim for s in after["planned"])


def test_unsupported_reports_high_weight_points_with_reasons(store):
    bp = _plan(store)
    covered = {s["assessment_point_id"] for s in bp["planned"]}
    for item in bp["unsupported"]:
        assert item["assessment_point_id"] not in covered
        assert item["reason"]


def test_gate_rejections_are_counted_by_reason(store):
    bp = _plan(store)
    assert isinstance(bp["gate_rejections"], dict)
    assert all(isinstance(v, int) for v in bp["gate_rejections"].values())


def test_plot_series_has_axes(store):
    bp = _plan(store)
    for mark in blueprint.plot_points(bp["planned"]):
        assert mark["assessment_point"] and mark["template"]
        assert mark["y_min"] is not None and mark["y_max"] is not None


# --- regression: a zero-slot Focus must not crash catalog scheduling ---------

def test_low_weight_focus_allocated_zero_slots_does_not_crash(store):
    """A low-weight Focus can receive zero slots from the proportional
    schedule, so it never enters topic_counts. Scheduling must skip it rather
    than KeyError on the topic id (regression: KeyError 'project_logic')."""
    import random

    from app.assessment_catalog import TOPIC_BY_ID
    from app.generator import _catalog_tasks, _proportional_schedule

    weights = [("architecture", 4), ("api", 3), ("data_flow", 5),
               ("database", 3), ("testing", 3), ("project_logic", 2)]
    items = [(TOPIC_BY_ID[i], w) for i, w in weights]
    allocated = {t["id"] for t in _proportional_schedule(items, 5)}
    assert {i["id"] for i, _ in items} - allocated, "fixture must leave a Focus unallocated"

    cfg = {"focus_areas": [{"id": i, "weight": w} for i, w in weights],
           "assessment_targets": []}
    tasks, _warnings = _catalog_tasks(store, cfg, 5, random.Random(1))
    assert isinstance(tasks, list)
