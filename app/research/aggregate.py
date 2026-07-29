"""Small-cell suppression for cohort aggregates — dataset B (§7).

Enforces the n >= MIN_CELL rule and blocks complementary-cell disclosure, where
a single suppressed cell could be recovered by subtracting the released cells
from a published total.
"""
from __future__ import annotations

MIN_CELL = 5


def suppress_distribution(counts: dict, min_cell: int = MIN_CELL) -> dict:
    """Apply small-cell suppression to a single categorical distribution.

    ``counts`` maps category -> integer count.

    Rules:
      * Primary: any cell with ``count < min_cell`` is suppressed. Zero cells
        are suppressed too — publishing an empty category also leaks.
      * Secondary: if exactly ONE cell ends up suppressed, it could be
        recovered as ``n_total - sum(released)``. So the smallest released cell
        is suppressed as well, until at least two cells are hidden (or none
        remain).
      * ``group_reportable`` is False when the whole group is below ``min_cell``
        — the caller must not publish such a group at all (not even its total).

    Returns a dict with ``released`` (safe cells), ``suppressed`` (hidden
    category keys), ``n_total``, ``min_cell`` and ``group_reportable``.
    """
    counts = {k: int(v) for k, v in counts.items()}
    total = sum(counts.values())

    suppressed = {k for k, n in counts.items() if n < min_cell}
    released = {k: n for k, n in counts.items() if k not in suppressed}

    if len(suppressed) == 1 and released:
        victim = min(released, key=lambda k: (released[k], k))
        suppressed.add(victim)
        released.pop(victim)

    return {
        "released": dict(sorted(released.items())),
        "suppressed": sorted(suppressed),
        "n_total": total,
        "min_cell": min_cell,
        "group_reportable": total >= min_cell,
    }
