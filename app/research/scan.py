"""Fail-closed privacy scanner for research exports (Phase 1).

Contract:
  * A value/record is safe to export ONLY if ``scan()`` returns an empty list.
  * The scanner NEVER returns, raises, or logs the offending substring — only
    the *category* of the problem. This is required so that privacy-validation
    failures can be recorded without writing the sensitive value anywhere.
  * When in doubt it errs towards flagging (false positives are acceptable;
    silently letting a sensitive value through is not).

This is the secondary safety net. The primary defence is the strict allowlist
(``allowlist.py`` / ``validate.py``): exports are BUILT from allowed fields,
never by copying an operational record and deleting keys.
"""
from __future__ import annotations

import math
import re
from collections import Counter

# --- regex detectors -------------------------------------------------------
# 9-digit student number, not embedded in a longer digit run.
_SID = re.compile(r"(?<!\d)\d{9}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"\b(?:https?://|ftp://|git@|ssh://|www\.)\S+", re.I)
_WIN_PATH = re.compile(r"[A-Za-z]:\\[\\\w .+-]+")
# Absolute unix-style path with at least two segments (/a/b...).
_ABS_PATH = re.compile(r"(?:^|(?<=[\s\"'(=:]))/(?:[\w.+-]+/)+[\w.+-]*")
# A token that ends in a source/config file extension.
_FILE_EXT = re.compile(
    r"\b[\w./+-]+\.(?:py|ipynb|js|jsx|ts|tsx|java|c|cc|cpp|h|hpp|go|rb|rs|php|"
    r"sql|md|txt|csv|tsv|json|ya?ml|toml|cfg|ini|env|pem|key|sh|bat)\b",
    re.I,
)
_AWS_KEY = re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA)[0-9A-Z]{16}\b")
_GH_TOKEN = re.compile(
    r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{22,}\b"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")
_SECRET_KW = re.compile(
    r"\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|"
    r"bearer|client[_-]?secret|private[_-]?key)\b\s*[:=]",
    re.I,
)
# ISO-8601-ish exact timestamp (research outputs must use bands, never this).
_TIMESTAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?")

_REGEX_DETECTORS = [
    ("student_id", _SID),
    ("email", _EMAIL),
    ("url", _URL),
    ("windows_path", _WIN_PATH),
    ("filesystem_path", _ABS_PATH),
    ("filename", _FILE_EXT),
    ("aws_key", _AWS_KEY),
    ("github_token", _GH_TOKEN),
    ("private_key", _PRIVATE_KEY),
    ("secret_assignment", _SECRET_KW),
    ("exact_timestamp", _TIMESTAMP),
]

# --- high-entropy (likely secret/hash) detection ---------------------------
_TOKEN = re.compile(r"[A-Za-z0-9+/_=-]{20,}")


def _shannon_bits(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in Counter(s).values())


def _has_high_entropy_token(value: str) -> bool:
    for tok in _TOKEN.findall(value):
        if (
            len(tok) >= 24
            and _shannon_bits(tok) >= 3.5
            and re.search(r"[A-Za-z]", tok)
            and re.search(r"\d", tok)
        ):
            return True
    return False


def find_disallowed(value, forbidden_terms=frozenset()) -> set[str]:
    """Return the set of sensitive *categories* found in a single value.

    Never returns the offending substring. ``forbidden_terms`` is a set of
    known project-specific identifiers (function/class/variable/module names,
    repo name, personal names) that must not appear verbatim in an export.
    """
    if not isinstance(value, str):
        return set()
    found: set[str] = set()
    for category, rx in _REGEX_DETECTORS:
        if rx.search(value):
            found.add(category)
    if _has_high_entropy_token(value):
        found.add("high_entropy_secret")
    if forbidden_terms:
        low = value.lower()
        for term in forbidden_terms:
            t = (term or "").strip().lower()
            if len(t) >= 3 and re.search(r"(?<![\w])" + re.escape(t) + r"(?![\w])", low):
                found.add("project_identifier")
                break
    return found


def scan(obj, forbidden_terms=frozenset()) -> list[str]:
    """Recursively scan a JSON-like structure (dict/list/str/scalars).

    Dict *keys* are scanned as well — a leaked identifier could hide in a key.
    Returns a sorted, de-duplicated list of category names. An empty list means
    the structure is clean.
    """
    categories: set[str] = set()

    def walk(o):
        if isinstance(o, str):
            categories.update(find_disallowed(o, forbidden_terms))
        elif isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str):
                    categories.update(find_disallowed(k, forbidden_terms))
                walk(v)
        elif isinstance(o, (list, tuple, set, frozenset)):
            for v in o:
                walk(v)
        # numbers / bool / None: nothing to scan

    walk(obj)
    return sorted(categories)


class PrivacyValidationError(Exception):
    """Raised when a value/record fails privacy validation.

    The message and ``categories`` contain ONLY category names, never the
    detected sensitive value.
    """

    def __init__(self, categories):
        self.categories = list(categories)
        super().__init__("privacy validation failed: " + ", ".join(self.categories))


def assert_clean(obj, forbidden_terms=frozenset()):
    """Fail closed: raise ``PrivacyValidationError`` if anything is detected."""
    categories = scan(obj, forbidden_terms)
    if categories:
        raise PrivacyValidationError(categories)
    return True
