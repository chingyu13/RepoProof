"""Phase-1 tests for the research de-identification primitives.

Fixtures deliberately contain sensitive values; the tests prove those values
never pass validation and never leak into logs/errors.
"""
import pytest

from app.research import aggregate, bands, manifest, optout
from app.research.allowlist import (
    SchemaValidationError,
    enforce_allowlist,
    new_study_record_id,
)
from app.research.scan import (
    PrivacyValidationError,
    assert_clean,
    find_disallowed,
    scan,
)
from app.research.validate import validate_dataset_a_record


# --- §4 / §12 privacy scanner: sensitive fixtures must always be flagged ----

SENSITIVE_CASES = {
    "student_id": "the student 540791765 wrote this",
    "email": "contact jane.doe@example.com for help",
    "url": "see https://github.com/someuser/bank-project",
    "filesystem_path": 'opened "/Users/jane/projects/bank/app.py"',
    "windows_path": r"loaded C:\Users\jane\bank\app.py",
    "filename": "the file bank_service.py failed",
    "aws_key": "AKIAIOSFODNN7EXAMPLE was hardcoded",
    "github_token": "token ghp_012345678901234567890123456789abcdef",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIhole\n",
    "exact_timestamp": "submitted 2026-07-29T14:03:41",
}


@pytest.mark.parametrize("category,text", list(SENSITIVE_CASES.items()))
def test_scanner_flags_each_sensitive_category(category, text):
    found = find_disallowed(text)
    assert found, f"{category!r} was not flagged"
    assert category in found


def test_scanner_flags_project_identifiers():
    # SID in a comment, name in a filename, student-defined symbols.
    forbidden = {"calc_interest", "Account", "MAX_DAILY_TRANSFER", "jane_doe"}
    snippet = "def calc_interest(Account):  # by jane_doe\n    return MAX_DAILY_TRANSFER"
    assert "project_identifier" in find_disallowed(snippet, forbidden)


def test_scanner_flags_high_entropy_secret():
    assert "high_entropy_secret" in find_disallowed("key=Zx9Kd3Lm82Qp7Wv1Ns6Bt4Rf0Yg5Hc")


def test_scan_recurses_into_keys_and_values():
    obj = {"nested": {"note": "email me at a@b.co"}, "list": ["clean", "540791765"]}
    cats = scan(obj)
    assert "email" in cats and "student_id" in cats


def test_clean_record_passes():
    clean = {"question_topic": "recursion", "selected_response": "A", "correct": True}
    assert scan(clean) == []
    assert assert_clean(clean) is True


def test_assert_clean_raises_categories_only_never_the_value():
    secret = "AKIAIOSFODNN7EXAMPLE"
    with pytest.raises(PrivacyValidationError) as ei:
        assert_clean({"leak": secret})
    # The error must name the category but never echo the sensitive value.
    assert "aws_key" in ei.value.categories
    assert secret not in str(ei.value)


# --- §2 / §6 allowlist + record validation ---------------------------------

def test_unknown_fields_are_rejected():
    with pytest.raises(SchemaValidationError):
        enforce_allowlist({"question_topic": "loops", "repo_id": "sjdivn"})


def test_forbidden_operational_key_rejected_before_export():
    row = {"study_record_id": new_study_record_id(), "repo_id": "sjdivn"}
    with pytest.raises(PrivacyValidationError) as ei:
        validate_dataset_a_record(row)
    assert any(c.startswith("forbidden_key:") for c in ei.value.categories)


def test_valid_dataset_a_row_passes():
    row = {
        "study_record_id": new_study_record_id(),
        "semester": "2026S2",
        "assignment": "A1",
        "question_topic": "recursion",
        "selected_response": "B",
        "correct": False,
        "duration_band": bands.duration_band(72),
        "completion_period": "early",
        "structure_counts": {"functions": 6, "classes": 2},
        "complexity_band": "low",
        "review_outcome": "approved",
        "consent_version": "c1",
        "deid_rule_version": "0.1.0-phase1",
    }
    assert validate_dataset_a_record(row) == row


def test_dataset_a_row_with_hidden_code_snippet_is_rejected():
    row = {
        "study_record_id": new_study_record_id(),
        "question_topic": "def transfer(self, amount):  # student code",
    }
    with pytest.raises(PrivacyValidationError):
        validate_dataset_a_record(row, forbidden_terms={"transfer"})


def test_study_record_id_is_random_and_not_operational():
    a, b = new_study_record_id(), new_study_record_id()
    assert a != b and a.startswith("sr_") and len(a) > 20


# --- §5 bands ---------------------------------------------------------------

@pytest.mark.parametrize("seconds,expected", [
    (0, "under_30s"), (29, "under_30s"), (30, "30_to_90s"), (89, "30_to_90s"),
    (90, "90_to_180s"), (180, "3_to_5min"), (299, "3_to_5min"), (300, "over_5min"),
    (-1, "unknown"), (None, "unknown"), ("x", "unknown"),
])
def test_duration_bands(seconds, expected):
    assert bands.duration_band(seconds) == expected


def test_completion_period_thirds():
    assert bands.completion_period(10, 0, 90) == "early"
    assert bands.completion_period(45, 0, 90) == "middle"
    assert bands.completion_period(80, 0, 90) == "late"
    assert bands.completion_period(200, 0, 90) == "unknown"   # outside window
    assert bands.completion_period(5, 10, 10) == "unknown"    # degenerate window


# --- §7 aggregate suppression ----------------------------------------------

def test_small_cells_suppressed():
    out = aggregate.suppress_distribution({"A": 12, "B": 3, "C": 8})
    # B (n=3) is suppressed; because only one would be, a second is too.
    assert "B" in out["suppressed"]
    assert len(out["suppressed"]) >= 2
    assert "B" not in out["released"]


def test_complementary_cell_disclosure_prevented():
    # One small cell + a known total would let B be recovered by subtraction.
    out = aggregate.suppress_distribution({"A": 10, "B": 3, "C": 12})
    assert len(out["suppressed"]) >= 2  # secondary suppression kicked in


def test_all_large_cells_released():
    out = aggregate.suppress_distribution({"A": 10, "B": 8})
    assert out["suppressed"] == [] and out["released"] == {"A": 10, "B": 8}


def test_zero_cell_is_suppressed():
    out = aggregate.suppress_distribution({"A": 20, "B": 0, "C": 15})
    assert "B" in out["suppressed"]


def test_whole_small_group_not_reportable():
    out = aggregate.suppress_distribution({"A": 2, "B": 1})
    assert out["group_reportable"] is False
    assert out["released"] == {}


# --- §8 opt-out handling ----------------------------------------------------

def test_optout_validation_dedup_and_counts():
    excluded, audit = optout.process_exclusions(
        optout_raw="sjdivn\nsjdivn\nejhud\n999999999\nbad id!\n",
        attempt_repo_ids=["sjdivn", "cjudfc", "sjdivn", "wjdui"],
    )
    assert excluded == {"sjdivn"}
    assert audit["excluded_attempt_count"] == 2         # two attempts by sjdivn
    assert audit["unmatched_repo_id_count"] == 1        # ejhud not in attempts
    assert audit["invalid_entry_count"] == 2            # SID-like + "bad id!"
    assert audit["processed_by_role"] == "independent_care_staff"


def test_optout_audit_contains_no_repo_ids():
    excluded, audit = optout.process_exclusions(
        optout_raw=["sjdivn", "ejhud"], attempt_repo_ids=["sjdivn"]
    )
    blob = repr(audit)
    assert "sjdivn" not in blob and "ejhud" not in blob


# --- §9 manifest ------------------------------------------------------------

def test_manifest_has_versions_and_no_identifiers():
    m = manifest.build_manifest(
        dataset="B_cohort", semester="2026S2", assignment="A1",
        source_record_count=120, included_opt_in_count=0,
        excluded_opt_out_count=4, suppressed_group_count=2,
        privacy_failure_count=0, file_checksums={"cohort.json": "abc123"},
    )
    assert m["deidentification_rule_version"]
    assert m["band_definition_version"]
    for identifier in ("repo_id", "sjdivn", "sid", "540791765"):
        assert identifier not in repr(m)


def test_manifest_checksum_stable():
    assert manifest.sha256_bytes(b"hello") == manifest.sha256_bytes(b"hello")
