"""Strict field allowlist for dataset A (individual opt-in export) — §2, §6.

Exports are BUILT by selecting allowed fields, never by copying an operational
record and deleting keys. Any unknown/extra key is rejected (fail closed). The
allowed *values* (e.g. which structure counts, which band labels) are refined
in Phase 2 when the operational/analysis schema is frozen; the KEY allowlist
and the rejection mechanism are stable and enforced now.
"""
from __future__ import annotations

import secrets

# Approved participant-level keys for dataset A. Everything here is a count,
# category, band, or non-identifying label — never raw code, text, or an
# operational identifier.
DATASET_A_ALLOWED = frozenset({
    "study_record_id",     # cryptographically random, not derived from any operational id
    "semester",            # e.g. "2026S2"
    "assignment",          # approved generic label, e.g. "A1"
    "question_topic",      # from an approved generic catalogue
    "question_template",   # template/category id from an approved catalogue
    "selected_response",   # generic option label, e.g. "A"/"B"/"C"
    "correct",             # boolean
    "duration_band",       # from bands.duration_band
    "completion_period",   # early / middle / late
    "structure_counts",    # approved project-structure counts (dict of ints)
    "complexity_band",     # approved complexity band label
    "review_outcome",      # question review outcome (approved/edited/rejected)
    "consent_version",     # audit metadata, no identifier
    "deid_rule_version",   # audit metadata, no identifier
})


class SchemaValidationError(Exception):
    """Raised when a record contains keys outside the allowlist."""

    def __init__(self, unknown):
        self.unknown = sorted(unknown)
        super().__init__("unknown fields rejected: " + ", ".join(self.unknown))


def enforce_allowlist(record: dict, allowed: frozenset = DATASET_A_ALLOWED) -> dict:
    """Return a shallow copy of ``record`` iff every key is allowlisted.

    Raises ``SchemaValidationError`` on any unknown/extra key.
    """
    unknown = set(record.keys()) - set(allowed)
    if unknown:
        raise SchemaValidationError(unknown)
    return dict(record)


def new_study_record_id() -> str:
    """A cryptographically random dataset-A record id.

    NOT derived from RepoID/FolderID/SID or any operational id. The
    study_record_id <-> RepoID mapping must NEVER be stored inside RepoProof or
    in the export; if withdrawal requires a mapping it is held separately by
    independent CARE staff.
    """
    return "sr_" + secrets.token_hex(16)
