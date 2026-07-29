"""RepoProof research de-identification & aggregation (Phase 1).

Isolated, offline tooling that turns *operational* data into privacy-minimised
*research* outputs. It is deliberately decoupled from the live request path and
the question-generation / local-LLM code, so it can be iterated without
touching the product.

Phase 1 (this package) provides the schema-independent, pure, tested
primitives only:

    versions   — export / schema / de-id-rule / band version constants
    scan       — fail-closed privacy scanner (values never logged)
    bands      — deterministic, versioned time/measurement bands
    aggregate  — small-cell (n<5) suppression + complementary-cell defence
    optout     — independent-CARE opt-out import (counts-only audit)
    allowlist  — strict dataset-A field allowlist + study_record_id
    validate   — fail-closed per-record validator for dataset A
    manifest   — non-identifying export manifest + checksums

NOT yet implemented (Phase 2, binds to the operational/analysis schema that is
still being tuned): the real dataset-A field mapping and export, code-derived
structural-feature extraction, dataset-B concrete aggregate computation, and
live destructive deletion. Do NOT claim full de-identification is implemented
until Phase 2 lands and all required tests pass.
"""
