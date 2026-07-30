"""Phase-1 tests for the blueprint-planning catalog (PRD §13 AC 1-3, 9).

Covers: catalog counts, matrix validation at load, missing entries defaulting to
zero, unknown IDs failing startup, code-mode gating, and catalog hashing.
"""
import json

import pytest

from app import assessment_catalog as ac


# --- AC 1: catalog validates the expected object counts --------------------

def test_catalog_counts():
    assert len(ac.ASSESSMENT_POINTS) == 20
    assert len(ac.TEMPLATES) == 13
    assert len(ac.TOPICS) == 9
    assert len(ac.EVIDENCE_TYPES) == 10


# --- AC 2: both matrices are validated and complete enough to plan with -----

def test_every_focus_has_point_weights():
    for topic in ac.TOPICS:
        row = ac.FOCUS_POINT_WEIGHTS.get(topic["id"])
        assert row, f"focus {topic['id']} has no assessment-point weights"
        assert any(w > 0 for w in row.values())


def test_every_point_has_at_least_one_usable_template():
    for point in ac.ASSESSMENT_POINTS:
        row = ac.POINT_TEMPLATE_WEIGHTS.get(point["id"])
        assert row, f"assessment point {point['id']} has no template weights"
        assert any(w > 0 for w in row.values())


def test_every_template_is_reachable_from_some_point():
    usable = {t for row in ac.POINT_TEMPLATE_WEIGHTS.values()
              for t, w in row.items() if w > 0}
    assert usable == {t["id"] for t in ac.TEMPLATES}


def test_every_point_is_reachable_from_some_focus():
    reachable = {p for row in ac.FOCUS_POINT_WEIGHTS.values()
                 for p, w in row.items() if w > 0}
    assert reachable == {p["id"] for p in ac.ASSESSMENT_POINTS}


def test_weights_within_unit_range():
    for matrix in (ac.FOCUS_POINT_WEIGHTS, ac.POINT_TEMPLATE_WEIGHTS):
        for row in matrix.values():
            for weight in row.values():
                assert 0.0 < weight <= 1.0


# --- AC 3: missing entries default to zero; unknown IDs fail ---------------

def test_missing_entries_default_to_zero():
    # api Focus has nothing to do with the testing point; not stored, reads 0.0
    assert "testing_quality_verification" not in ac.FOCUS_POINT_WEIGHTS["api"]
    assert ac.focus_point_fit("api", "testing_quality_verification") == 0.0
    assert ac.point_template_fit("package_purpose", "fault_correction") == 0.0
    # unknown ids are simply zero at read time (they cannot be stored)
    assert ac.focus_point_fit("nope", "package_purpose") == 0.0
    assert ac.point_template_fit("package_purpose", "nope") == 0.0


def _catalog_with(tmp_path, **overrides):
    data = json.loads(ac._catalog_path().read_text(encoding="utf-8"))
    data.update(overrides)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_unknown_focus_id_fails_startup(tmp_path):
    bad = dict(ac.FOCUS_POINT_WEIGHTS, not_a_focus={"package_purpose": 1.0})
    with pytest.raises(ValueError, match="unknown focus id"):
        ac.load_catalog(_catalog_with(tmp_path, focus_point_weights=bad))


def test_unknown_point_id_in_matrix_fails_startup(tmp_path):
    bad = json.loads(json.dumps(ac.FOCUS_POINT_WEIGHTS))
    bad["api"]["not_a_point"] = 0.5
    with pytest.raises(ValueError, match="unknown assessment point id"):
        ac.load_catalog(_catalog_with(tmp_path, focus_point_weights=bad))


def test_unknown_template_id_in_matrix_fails_startup(tmp_path):
    bad = json.loads(json.dumps(ac.POINT_TEMPLATE_WEIGHTS))
    bad["package_purpose"]["not_a_template"] = 0.5
    with pytest.raises(ValueError, match="unknown template id"):
        ac.load_catalog(_catalog_with(tmp_path, point_template_weights=bad))


def test_out_of_range_weight_fails_startup(tmp_path):
    bad = json.loads(json.dumps(ac.POINT_TEMPLATE_WEIGHTS))
    bad["package_purpose"]["contextual_use"] = 1.4
    with pytest.raises(ValueError, match="within 0.0-1.0"):
        ac.load_catalog(_catalog_with(tmp_path, point_template_weights=bad))


def test_missing_matrix_fails_startup(tmp_path):
    path = tmp_path / "c.json"
    data = json.loads(ac._catalog_path().read_text(encoding="utf-8"))
    data.pop("focus_point_weights")
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="focus_point_weights"):
        ac.load_catalog(path)


def test_framework_policy_requires_all_code_modes(tmp_path):
    bad = {"emphasis_fit": {"balanced": {"none": 1.0}}}
    with pytest.raises(ValueError, match="missing code modes"):
        ac.load_catalog(_catalog_with(tmp_path, framework_template_policy=bad))


# --- AC 9: code-disabled frameworks never schedule code templates ----------

def test_code_templates_prohibited_when_code_disallowed():
    for template in ac.TEMPLATES:
        fit = ac.framework_template_fit(template, allow_code=False)
        if template["code_mode"] != "none":
            assert fit == 0.0, f"{template['id']} must be gated off"
        else:
            assert fit > 0.0


def test_emphasis_shifts_template_preference():
    code_t = ac.TEMPLATE_BY_ID["code_explain"]
    concept_t = ac.TEMPLATE_BY_ID["contextual_use"]
    assert (ac.framework_template_fit(code_t, emphasis="mostly_code")
            > ac.framework_template_fit(code_t, emphasis="mostly_concepts"))
    assert (ac.framework_template_fit(concept_t, emphasis="mostly_concepts")
            >= ac.framework_template_fit(concept_t, emphasis="mostly_code"))


def test_unknown_emphasis_falls_back_to_balanced():
    t = ac.TEMPLATE_BY_ID["contextual_use"]
    assert ac.framework_template_fit(t, emphasis="???") == \
        ac.framework_template_fit(t, emphasis="balanced")


# --- catalog hash (PRD 10.4) ----------------------------------------------

def test_catalog_hash_is_stable_and_short():
    h = ac.catalog_hash()
    assert h == ac.catalog_hash()
    assert len(h) == 16 and all(c in "0123456789abcdef" for c in h)
