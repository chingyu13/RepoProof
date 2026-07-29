"""Independent-CARE opt-out handling for cohort analytics — dataset B (§8).

An independent CARE staff member supplies the list of RepoIDs that opted out
via the confidential Qualtrics form before the quiz deadline. This module
validates and de-duplicates that list and produces a COUNTS-ONLY audit. RepoIDs
are never logged and never appear in the audit, the analytics report, or the
research export.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

_REPO_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def valid_repo_id(rid: str):
    """Return a cleaned RepoID, or None if it is malformed or looks like an SID."""
    rid = (rid or "").strip()
    if not _REPO_ID.match(rid):
        return None
    if rid.isdigit() and len(rid) >= 7:  # a real student number must never be here
        return None
    return rid


def parse_optout_list(raw):
    """Parse an opt-out list from newline/comma text or an iterable of strings.

    Returns ``(valid_repo_ids: set, invalid_entry_count: int)``.
    """
    if isinstance(raw, str):
        items = re.split(r"[\r\n,]+", raw)
    else:
        items = list(raw or [])
    valid: set[str] = set()
    invalid = 0
    for item in items:
        s = item if isinstance(item, str) else ""
        rid = valid_repo_id(s)
        if rid:
            valid.add(rid)
        elif s.strip():
            invalid += 1
    return valid, invalid


def process_exclusions(optout_raw, attempt_repo_ids, processed_by_role="independent_care_staff"):
    """Compute the set of RepoIDs to exclude before aggregation, plus an audit.

    ``attempt_repo_ids`` is the iterable of RepoIDs on operational attempts (one
    per attempt; duplicates allowed). Returns ``(excluded_repo_ids, audit)``
    where ``excluded_repo_ids`` is used INTERNALLY to filter attempts, and
    ``audit`` contains only counts — no RepoIDs.
    """
    optout, invalid = parse_optout_list(optout_raw)
    attempts_list = [r for r in attempt_repo_ids if r]
    attempts_set = set(attempts_list)

    matched = optout & attempts_set
    unmatched = optout - attempts_set
    excluded_attempt_count = sum(1 for r in attempts_list if r in optout)

    audit = {
        "exclusion_list_received": bool(optout) or bool(invalid),
        "excluded_attempt_count": excluded_attempt_count,
        "unmatched_repo_id_count": len(unmatched),
        "invalid_entry_count": invalid,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "processed_by_role": processed_by_role,
    }
    return matched, audit
