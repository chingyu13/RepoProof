"""Publishing stage for the ingestion pipeline.

Committed test fixture; never executed by the app.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path("cache/readings.db")
MAX_BATCH = 500


class CacheStore:
    """Persists combined readings and forwards them to subscribers."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.subscribers: list = []

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS readings ("
            "region TEXT NOT NULL, ts TEXT NOT NULL, power REAL, emissions REAL,"
            "PRIMARY KEY (region, ts))"
        )
        return connection

    def save(self, rows: list[dict]) -> int:
        if len(rows) > MAX_BATCH:
            raise ValueError(f"batch of {len(rows)} exceeds the {MAX_BATCH} row limit")
        with self.connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO readings VALUES (?,?,?,?)",
                [(r["region"], r["ts"], r.get("power"), r.get("emissions")) for r in rows],
            )
        return len(rows)

    def publish(self, rows: list[dict]) -> None:
        """Save first, then notify subscribers in registration order."""
        self.save(rows)
        for subscriber in self.subscribers:
            subscriber(rows)
