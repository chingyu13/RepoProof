"""Cleaning and aggregation helpers for the ingestion pipeline.

Committed test fixture; never executed by the app.
"""
from __future__ import annotations

from collections import defaultdict

REQUIRED_FIELDS = ("region", "ts", "power")


def drop_incomplete(rows: list[dict]) -> list[dict]:
    """Remove rows missing a required field or carrying a null power value."""
    kept = []
    for row in rows:
        if any(row.get(field) in (None, "") for field in REQUIRED_FIELDS):
            continue
        if row.get("power") is None:
            continue
        kept.append(row)
    return kept


def combine_readings(rows: list[dict]) -> list[dict]:
    """Sum power and emissions per (region, timestamp) pair."""
    totals: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"power": 0.0, "emissions": 0.0})
    for row in rows:
        key = (str(row["region"]), str(row["ts"]))
        totals[key]["power"] += float(row.get("power") or 0)
        totals[key]["emissions"] += float(row.get("emissions") or 0)
    return [
        {"region": region, "ts": ts, "power": value["power"], "emissions": value["emissions"]}
        for (region, ts), value in sorted(totals.items())
    ]


def to_hourly(rows: list[dict]) -> list[dict]:
    """Coarsen timestamps to the hour so the dashboard shows stable buckets."""
    return [{**row, "ts": str(row["ts"])[:13]} for row in rows]
