"""Fail-closed per-record validator for dataset A (§6).

A candidate individual research row is exportable only if it passes all three:
  1. strict allowlist (no unknown keys);
  2. no forbidden operational-identifier keys;
  3. recursive text/secret scan (no sensitive values anywhere).

Any failure raises — the record is not exported. Errors carry category names
only, never the offending value.
"""
from __future__ import annotations

from .allowlist import enforce_allowlist
from .scan import PrivacyValidationError, assert_clean

# Operational-identifier keys that must never appear in a research row, even if
# someone forgets to strip them upstream. Checked case-insensitively.
FORBIDDEN_KEYS = frozenset({
    "repo_id", "repoid", "folder_id", "folderid", "sid", "student_id",
    "project_id", "assessment_id", "attempt_id", "question_id",
    "completion_code", "completion", "taker_name", "name",
    "ip", "ip_address", "session_id", "session",
    "submitted_at", "created_at", "updated_at", "timestamp",
    "upload_name", "archive_name", "original_name",
    "repository_url", "repo_url", "url", "file_path", "filesystem_path", "path",
})


def validate_dataset_a_record(record: dict, forbidden_terms=frozenset()) -> dict:
    """Validate one dataset-A row. Returns the record if clean, else raises.

    ``forbidden_terms`` are known project-specific identifiers (function/class/
    variable/module names, repo name, personal names) that must not appear
    verbatim in any value.
    """
    bad_keys = FORBIDDEN_KEYS & {str(k).lower() for k in record}
    if bad_keys:
        raise PrivacyValidationError(["forbidden_key:" + k for k in sorted(bad_keys)])
    enforce_allowlist(record)               # unknown keys -> SchemaValidationError
    # study_record_id is our own cryptographically random, non-identifying token;
    # exclude it from the value scan so it is not mistaken for a leaked secret.
    scan_target = {k: v for k, v in record.items() if k != "study_record_id"}
    assert_clean(scan_target, forbidden_terms)   # sensitive values -> PrivacyValidationError
    return dict(record)
