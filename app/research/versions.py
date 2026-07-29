"""Central version constants for research outputs.

Every export must record these so a reviewer can audit exactly which rules and
band definitions produced a given dataset. Bump the relevant version whenever a
rule or band boundary changes; never change a boundary silently.
"""

# Overall export format.
EXPORT_VERSION = "0.1.0-phase1"

# De-identification rule set (allowlist + forbidden keys + scanner categories).
DEID_RULE_VERSION = "0.1.0-phase1"

# Time/measurement band boundaries (see bands.py). Deterministic + documented.
BAND_DEFINITION_VERSION = "1.0.0"

# Per-dataset output schema versions.
_SCHEMA = {
    "A_individual": "0.1.0",
    "B_cohort": "0.1.0",
}


def schema_version(dataset: str) -> str:
    return _SCHEMA.get(dataset, "unknown")
