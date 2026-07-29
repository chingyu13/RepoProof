"""Non-identifying export manifest + checksums (§9).

Every research export ships a manifest that records versions and counts so a
reviewer can audit it. By construction it contains NO participant identifiers.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from . import versions


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_manifest(
    *,
    dataset: str,
    semester: str,
    assignment: str,
    source_record_count: int,
    included_opt_in_count: int,
    excluded_opt_out_count: int,
    suppressed_group_count: int,
    privacy_failure_count: int,
    file_checksums: dict,
) -> dict:
    """Assemble the manifest for one export.

    ``dataset`` is ``"A_individual"`` or ``"B_cohort"``. ``file_checksums`` maps
    exported filename -> sha256 hex. No identifiers are accepted or stored.
    """
    return {
        "export_version": versions.EXPORT_VERSION,
        "schema_version": versions.schema_version(dataset),
        "deidentification_rule_version": versions.DEID_RULE_VERSION,
        "band_definition_version": versions.BAND_DEFINITION_VERSION,
        "dataset": dataset,
        "semester": semester,
        "assignment": assignment,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_record_count": int(source_record_count),
        "included_opt_in_count": int(included_opt_in_count),
        "excluded_opt_out_count": int(excluded_opt_out_count),
        "suppressed_group_count": int(suppressed_group_count),
        "privacy_validation_failure_count": int(privacy_failure_count),
        "file_checksums": dict(file_checksums),
    }
