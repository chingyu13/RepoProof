"""Deterministic, versioned time/measurement bands (§5).

Research outputs must NEVER contain an exact timestamp or exact duration. All
time is reduced to these coarse, documented, versioned bands. Boundaries are
inclusive-low / exclusive-high and are intentionally wide enough that no band
singles out an individual.
"""
from __future__ import annotations

from .versions import BAND_DEFINITION_VERSION

__all__ = ("BAND_DEFINITION_VERSION", "duration_band", "completion_period")

# Answer-duration bands, in seconds.
_DURATION_BANDS = [
    (0, 30, "under_30s"),
    (30, 90, "30_to_90s"),
    (90, 180, "90_to_180s"),
    (180, 300, "3_to_5min"),
    (300, float("inf"), "over_5min"),
]


def duration_band(seconds) -> str:
    """Map an exact answer duration (seconds) to an approved band label.

    Returns ``"unknown"`` for missing/negative/unparseable input rather than
    guessing.
    """
    if seconds is None:
        return "unknown"
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "unknown"
    if s < 0:
        return "unknown"
    for lo, hi, label in _DURATION_BANDS:
        if lo <= s < hi:
            return label
    return "unknown"


def completion_period(submitted_at, opened_at, deadline) -> str:
    """Where in the assessment window the student submitted: early/middle/late.

    Inputs are comparable numerics (e.g. epoch seconds). The window is
    ``[opened_at, deadline]`` split into equal thirds. Anything missing,
    degenerate, or outside the window returns ``"unknown"`` (never guessed).
    """
    try:
        start = float(opened_at)
        end = float(deadline)
        t = float(submitted_at)
    except (TypeError, ValueError):
        return "unknown"
    if end <= start:
        return "unknown"
    frac = (t - start) / (end - start)
    if frac < 0 or frac > 1:
        return "unknown"
    if frac < 1 / 3:
        return "early"
    if frac < 2 / 3:
        return "middle"
    return "late"
