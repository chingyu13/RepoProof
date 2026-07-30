"""Phase-4 tests: generation runs from the confirmed blueprint (PRD §8, AC 12-13)."""
import random

import pytest

from app import blueprint, knowledge                       # noqa: E402
from app.generator import _band_midpoint, _frozen_tasks, generate_questions  # noqa: E402

TARGETS = [{"id": "t0", "kind": "project_scope", "label": "API", "weight": 1.5,
            "source": "scope",
            "description": ("Retrieve OpenElectricity data from a REST API, combine power "
                            "and emissions, save a CSV cache, publish ordered MQTT "
                            "messages and update a dashboard.")}]
FOCUS = [{"id": "api", "weight": 5}, {"id": "data_flow", "weight": 4}]


@pytest.fixture(scope="module")
def store():
    from pathlib import Path

    from app import analyzer
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
    return knowledge.EvidenceStore(chunks), chunks


@pytest.fixture(scope="module")
def frozen(store):
    evidence_store, _chunks = store
    bp = blueprint.build_blueprint(
        evidence_store, targets=TARGETS, focus_areas=FOCUS, snapshot_id="snap1",
        num_questions=5, difficulty_min=2, difficulty_max=4, seed=42)
    if not bp["planned"]:
        pytest.skip("fixture produced no evidence-supported plans")
    return bp["planned"]


def _cfg(frozen_slots, **over):
    cfg = {"num_questions": 5, "choice_count": 4, "correct_mode": "exact",
           "correct_exact": 1, "difficulty": 3, "provider": "mock", "seed": 42,
           "focus_areas": FOCUS, "assessment_targets": TARGETS,
           "frozen_slots": frozen_slots}
    cfg.update(over)
    return cfg


# --- AC 12: generation uses only the frozen slots ---------------------------

def test_frozen_tasks_follow_the_plan(store, frozen):
    evidence_store, _ = store
    tasks, _warnings = _frozen_tasks(evidence_store, _cfg(frozen), random.Random(1))
    assert tasks, "the confirmed plan produced no tasks"
    planned = [(s["assessment_point_id"], s["template_id"]) for s in frozen]
    built = [(t["slot"]["assessment_point_id"], t["slot"]["template_id"]) for t in tasks]
    assert built == planned[:len(built)]


def test_generation_matches_the_planned_templates(store, frozen):
    _es, chunks = store
    questions, _warnings = generate_questions(chunks, _cfg(frozen))
    assert questions
    planned_templates = [s["template_id"] for s in frozen]
    for question in questions:
        template_id = str(question.get("slot", "")).split(":")[-1]
        assert template_id in planned_templates


def test_generation_does_not_reschedule(store, frozen):
    """Without this, the paper could differ from what the creator confirmed."""
    _es, chunks = store
    a, _ = generate_questions(chunks, _cfg(frozen))
    b, _ = generate_questions(chunks, _cfg(frozen))
    assert [q.get("slot") for q in a] == [q.get("slot") for q in b]


def test_no_frozen_slots_falls_back_to_live_scheduling(store):
    _es, chunks = store
    cfg = _cfg([])
    cfg.pop("frozen_slots")
    questions, _warnings = generate_questions(chunks, cfg)
    assert questions, "legacy path must still generate without a blueprint"


def test_missing_template_is_reported_not_silently_dropped(store, frozen):
    evidence_store, _ = store
    broken = [dict(frozen[0], template_id="no_such_template")]
    tasks, warnings = _frozen_tasks(evidence_store, _cfg(broken), random.Random(1))
    assert not tasks
    assert any("no longer in the catalog" in w for w in warnings)


# --- AC 13: per-slot difficulty, not one number copied ---------------------

def test_slot_difficulty_comes_from_its_own_band(store, frozen):
    evidence_store, _ = store
    tasks, _ = _frozen_tasks(evidence_store, _cfg(frozen, difficulty=1), random.Random(1))
    for task, slot in zip(tasks, frozen):
        expected = _band_midpoint(slot["expected_difficulty"])
        assert task["slot"]["requested_difficulty"] == expected
        # and it is not just the framework-wide number
        assert task["slot"]["requested_difficulty"] != 1 or expected == 1


@pytest.mark.parametrize("band,expected", [
    ({"min": 3, "max": 4}, 3), ({"min": 4, "max": 4}, 4), ({"min": 1, "max": 5}, 3),
    ({}, 3), ({"min": 2}, 2), ({"max": 5}, 5),
])
def test_band_midpoint(band, expected):
    assert _band_midpoint(band) == expected
