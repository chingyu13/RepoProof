"""SQLite storage. JSON columns keep the prototype schema flexible;
migrate to PostgreSQL + pgvector when the project graduates from prototype."""
import json
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,          -- 'git' | 'upload'
    source TEXT NOT NULL,               -- URL or original filename
    snapshot_id TEXT NOT NULL,          -- commit SHA prefix or archive checksum
    stats_json TEXT NOT NULL DEFAULT '{}',
    chunks_json TEXT NOT NULL DEFAULT '[]',
    consent_json TEXT NOT NULL DEFAULT '{}',   -- {acknowledged, share_data, consent_version, at}
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    slot TEXT NOT NULL,
    stem TEXT NOT NULL,
    options_json TEXT NOT NULL,         -- [{key, text}]
    answer_json TEXT NOT NULL,          -- ["A","C"]
    justifications_json TEXT NOT NULL DEFAULT '{}',  -- {key: why correct/incorrect}
    evidence_json TEXT NOT NULL DEFAULT '[]',        -- [{chunk_id, title, file, lines}]
    difficulty INTEGER NOT NULL DEFAULT 1,
    focus_areas_json TEXT NOT NULL DEFAULT '[]',
    explanation TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',            -- draft | approved | rejected
    generator TEXT NOT NULL DEFAULT '',              -- model id or 'mock' or 'manual'
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    title TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    question_ids_json TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'published',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id INTEGER NOT NULL REFERENCES assessments(id),
    taker_name TEXT NOT NULL DEFAULT '',
    responses_json TEXT NOT NULL,       -- {question_id: ["A","B"]}
    score_json TEXT NOT NULL,
    submitted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Operational telemetry for the MLOps loop. Holds derived metadata only
-- (model/config, human review actions, outcomes) — never raw project code.
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,                 -- nullable: some events are global
    kind TEXT NOT NULL,                 -- e.g. project_created | generation_run | question_review | publish
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Columns added after the initial release: (table, column, definition).
# Applied idempotently on init() so existing SQLite files pick them up.
_MIGRATIONS = [
    ("projects", "consent_json", "TEXT NOT NULL DEFAULT '{}'"),
]


def init() -> None:
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    config.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript(SCHEMA)
        for table, column, ddl in _MIGRATIONS:
            cols = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def log_event(kind: str, data: dict, project_id: int | None = None) -> None:
    """Record an operational telemetry event. Best-effort: never breaks the request."""
    try:
        insert("events", {"project_id": project_id, "kind": kind, "data_json": data})
    except Exception:
        pass


@contextmanager
def connect():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in list(d):
        if key.endswith("_json"):
            d[key[:-5]] = json.loads(d.pop(key))
    return d


def insert(table: str, values: dict) -> int:
    cols, params = [], []
    for k, v in values.items():
        if k.endswith("_json") and not isinstance(v, str):
            v = json.dumps(v, ensure_ascii=False)
        cols.append(k)
        params.append(v)
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
    with connect() as con:
        cur = con.execute(sql, params)
        return cur.lastrowid


def update(table: str, row_id: int, values: dict) -> None:
    cols, params = [], []
    for k, v in values.items():
        if k.endswith("_json") and not isinstance(v, str):
            v = json.dumps(v, ensure_ascii=False)
        cols.append(f"{k}=?")
        params.append(v)
    params.append(row_id)
    with connect() as con:
        con.execute(f"UPDATE {table} SET {','.join(cols)} WHERE id=?", params)


def get(table: str, row_id: int) -> dict | None:
    with connect() as con:
        row = con.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_where(table: str, where: str, params: tuple) -> dict | None:
    with connect() as con:
        row = con.execute(f"SELECT * FROM {table} WHERE {where}", params).fetchone()
    return _row_to_dict(row) if row else None


def list_where(table: str, where: str = "1=1", params: tuple = (), order: str = "id DESC") -> list[dict]:
    with connect() as con:
        rows = con.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY {order}", params).fetchall()
    return [_row_to_dict(r) for r in rows]
