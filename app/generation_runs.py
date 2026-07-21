"""Persistent store for background generation runs.

Replaces the old in-process `_GENERATION_RUNS` dict in main.py, which had two
failure modes: a server restart made in-flight runs vanish (the frontend then
polls a 404 forever), and with more than one uvicorn worker the POST and the
GET could land in different processes. Runs now live in SQLite: status is
readable from any process and an interrupted run is explicitly failed at the
next startup instead of disappearing.
"""
import json
from datetime import datetime

from . import db

KEEP_FINISHED = 100


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _row_to_run(row) -> dict:
    run = json.loads(row["data_json"])
    run.update({
        "id": row["id"],
        "project_id": row["project_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    })
    return run


def create_run(run_id: str, project_id: int, total: int) -> dict:
    prune()
    data = {
        "progress": {"stage": "queued", "current": 0, "total": total,
                     "message": "Generation queued."},
        "context": {},
        "result": None,
        "error": "",
    }
    with db.connect() as con:
        con.execute(
            "INSERT INTO generation_runs (id, project_id, status, data_json, created_at, updated_at) "
            "VALUES (?, ?, 'queued', ?, ?, ?)",
            (run_id, project_id, json.dumps(data, ensure_ascii=False), _now(), _now()),
        )
    return get_run(run_id)


def get_run(run_id: str) -> dict | None:
    with db.connect() as con:
        row = con.execute("SELECT * FROM generation_runs WHERE id=?", (run_id,)).fetchone()
    return _row_to_run(row) if row else None


def update_run(run_id: str, **values) -> None:
    """Merge `values` into the run. `status` maps to its own column; everything
    else (progress/context/result/error) merges into the JSON payload."""
    with db.connect() as con:
        row = con.execute("SELECT * FROM generation_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return
        data = json.loads(row["data_json"])
        status = values.pop("status", row["status"])
        data.update(values)
        con.execute(
            "UPDATE generation_runs SET status=?, data_json=?, updated_at=? WHERE id=?",
            (status, json.dumps(data, ensure_ascii=False), _now(), run_id),
        )


def prune(keep_finished: int = KEEP_FINISHED) -> None:
    """Drop the oldest finished runs beyond `keep_finished` (running ones stay)."""
    with db.connect() as con:
        con.execute(
            "DELETE FROM generation_runs WHERE status IN ('complete','failed') AND id NOT IN ("
            "  SELECT id FROM generation_runs WHERE status IN ('complete','failed')"
            "  ORDER BY created_at DESC LIMIT ?)",
            (keep_finished,),
        )


def fail_stale_running(reason: str) -> int:
    """Startup hook: any run still queued/running belonged to a previous server
    process and can never finish — fail it explicitly so pollers see the truth."""
    with db.connect() as con:
        rows = con.execute(
            "SELECT * FROM generation_runs WHERE status IN ('queued','running')").fetchall()
        for row in rows:
            data = json.loads(row["data_json"])
            data["error"] = reason
            data["progress"] = {**data.get("progress", {}), "stage": "failed", "message": reason}
            con.execute(
                "UPDATE generation_runs SET status='failed', data_json=?, updated_at=? WHERE id=?",
                (json.dumps(data, ensure_ascii=False), _now(), row["id"]),
            )
    return len(rows)
