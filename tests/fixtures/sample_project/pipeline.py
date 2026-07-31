"""Ingestion pipeline: fetch remote readings, clean them, cache, then publish.

Part of the committed test fixture. It exists to give the planner a realistic
shape — cross-module calls, an external interface, a cache stage and a publish
stage — so no-code templates (data flow, stage responsibility, processing mode)
have evidence to bind to. It is never executed by the app.
"""
from __future__ import annotations

import csv
import json
import urllib.request
from pathlib import Path

from storage import CacheStore
from transforms import combine_readings, drop_incomplete

API_ROOT = "https://api.example.org/v1"
CACHE_PATH = Path("cache/readings.csv")
REQUEST_TIMEOUT = 30


def fetch_readings(region: str, since: str) -> list[dict]:
    """Call the readings endpoint and return decoded rows."""
    url = f"{API_ROOT}/readings?region={region}&since={since}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        if response.status != 200:
            raise RuntimeError(f"readings endpoint returned {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("results", [])


def write_cache(rows: list[dict], path: Path = CACHE_PATH) -> Path:
    """Materialise the cleaned rows so a rerun does not refetch."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["region", "ts", "power", "emissions"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def load_cache(path: Path = CACHE_PATH) -> list[dict]:
    """Read the cached rows, or an empty list when no cache exists yet."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def run(region: str, since: str, store: CacheStore) -> int:
    """Fetch, clean, combine, cache and hand rows to the store."""
    cached = load_cache()
    if cached:
        rows = cached
    else:
        raw = fetch_readings(region, since)
        rows = combine_readings(drop_incomplete(raw))
        write_cache(rows)
    store.publish(rows)
    return len(rows)
