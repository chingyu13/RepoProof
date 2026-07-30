"""Tests for model question confidence (ERD_QUESTION_CONFIDENCE §7)."""
import json
import sqlite3

import pytest

from fastapi.testclient import TestClient          # noqa: E402

from app import db                                 # noqa: E402
from app.generator import _clean_confidence        # noqa: E402
from app.main import app                           # noqa: E402

TEST_PASSWORD = "test-password-for-confidence"


@pytest.fixture(scope="module")
def client():
    from app import config
    config.ACCESS_PASSWORD = TEST_PASSWORD
    db.init()
    c = TestClient(app)
    assert c.post("/api/login", json={"password": TEST_PASSWORD}).status_code == 200
    return c


@pytest.fixture
def question():
    db.init()
    pid = db.insert("projects", {
        "name": "confidence-fixture", "source_type": "upload", "source": "x.zip",
        "snapshot_id": "snapC", "chunks_json": [], "stats_json": {}})
    # A realistic, approvable MAQ so the approval gate does not mask the
    # behaviour under test.
    qid = db.insert("questions", {
        "project_id": pid, "slot": "api:contextual_use",
        "stem": "Within the ingestion stage, what happens when the upstream request fails?",
        "options_json": [
            {"key": "A", "text": "The failure is raised and the pipeline stops before writing."},
            {"key": "B", "text": "The partial response is written to the cache unchanged."},
            {"key": "C", "text": "The request is retried forever without any backoff."},
            {"key": "D", "text": "The failure is ignored and an empty frame is published."},
        ],
        "answer_json": ["A"],
        "justifications_json": {
            "A": "The handler re-raises before the write step runs.",
            "B": "Nothing is written when the request raises.",
            "C": "There is no retry loop in the handler.",
            "D": "No empty frame is published on failure.",
        },
        "evidence_json": [{"chunk_id": "c1", "title": "Function ingest (main.py)",
                           "file": "main.py", "lines": "10-24"}],
        "difficulty": 3, "focus_areas_json": ["api"],
        "explanation": "The request error propagates before persistence, so nothing is written.",
        "generator": "local:test", "confidence": 8})
    return pid, qid


# --- AC 1/3: column contract ------------------------------------------------

def test_confidence_column_is_nullable_integer():
    db.init()
    con = sqlite3.connect(db.config.DB_PATH)
    col = [r for r in con.execute("PRAGMA table_info(questions)") if r[1] == "confidence"]
    assert col, "questions.confidence is missing"
    _cid, _name, coltype, notnull, default, _pk = col[0]
    assert coltype.upper() == "INTEGER"
    assert not notnull, "confidence must be nullable"
    assert default is None, "confidence must not have a fabricated default"


def test_existing_rows_migrate_without_a_score(question):
    """AC 4: a row written without confidence stays NULL."""
    pid, _qid = question
    qid = db.insert("questions", {
        "project_id": pid, "slot": "s", "stem": "x",
        "options_json": [], "answer_json": [], "justifications_json": {},
        "evidence_json": [], "difficulty": 1, "focus_areas_json": [],
        "explanation": "", "generator": "manual"})
    assert db.get("questions", qid)["confidence"] is None


# --- AC 1/2: value cleaning -------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (8, 8), (1, 1), (10, 10), ("7", 7), (8.0, 8),
    (0, None), (11, None), (-3, None), (None, None),
    (True, None), (False, None), (7.5, None), ("high", None), ("7.5", None), ("", None),
])
def test_clean_confidence(value, expected):
    assert _clean_confidence(value) == expected


def test_invalid_confidence_is_not_defaulted():
    """Invalid advisory metadata stays absent; it never invents a score."""
    assert _clean_confidence("nonsense") is None
    assert _clean_confidence(99) is None


# --- AC 5: API exposes it ---------------------------------------------------

def test_question_list_api_returns_confidence(client, question):
    pid, qid = question
    body = client.get(f"/api/projects/{pid}/questions").json()
    row = next(q for q in body if q["id"] == qid)
    assert row["confidence"] == 8


# --- AC 8: editing content clears it ---------------------------------------

def _patch(client, qid, **payload):
    return client.put(f"/api/questions/{qid}", json=payload)


def test_editing_the_stem_clears_confidence(client, question):
    _pid, qid = question
    assert _patch(client, qid, stem="A different stem?").status_code == 200
    assert db.get("questions", qid)["confidence"] is None


def test_editing_the_answer_clears_confidence(client, question):
    _pid, qid = question
    assert _patch(client, qid, answer=["B"]).status_code == 200
    assert db.get("questions", qid)["confidence"] is None


def test_editing_the_explanation_clears_confidence(client, question):
    _pid, qid = question
    assert _patch(client, qid, explanation="new reasoning").status_code == 200
    assert db.get("questions", qid)["confidence"] is None


def test_changing_difficulty_keeps_confidence(client, question):
    _pid, qid = question
    assert _patch(client, qid, difficulty=5).status_code == 200
    assert db.get("questions", qid)["confidence"] == 8


def test_changing_focus_or_status_keeps_confidence(client, question):
    _pid, qid = question
    assert _patch(client, qid, focus_areas=["data_flow"]).status_code == 200
    assert _patch(client, qid, status="approved").status_code == 200
    assert db.get("questions", qid)["confidence"] == 8


def test_review_event_records_confidence(client, question):
    pid, qid = question
    _patch(client, qid, stem="Edited stem?")
    events = [e for e in db.list_where("events", "project_id=? AND kind=?",
                                       (pid, "question_review"))]
    assert events, "no question_review event recorded"
    data = events[0]["data"]
    assert data["confidence"] == 8
    assert data["confidence_invalidated"] is True


def test_review_event_marks_confidence_not_invalidated(client, question):
    pid, qid = question
    _patch(client, qid, difficulty=4)
    data = db.list_where("events", "project_id=? AND kind=?", (pid, "question_review"))[0]["data"]
    assert data["confidence_invalidated"] is False


# --- AC 10: never reaches the taker ----------------------------------------

def test_confidence_is_absent_from_the_taker_payload(client, question):
    pid, qid = question
    _patch(client, qid, status="approved")
    published = client.post(f"/api/projects/{pid}/assessments", json={
        "title": "t", "question_ids": [qid]})
    assert published.status_code == 200, published.text
    token = published.json()["token"]
    payload = client.get(f"/api/take/{token}").json()
    blob = json.dumps(payload)
    assert "confidence" not in blob
    for item in payload["questions"]:
        assert "confidence" not in item
