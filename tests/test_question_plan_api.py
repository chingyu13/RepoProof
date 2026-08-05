"""Phase-3 tests: blueprint preview API and plan freezing (PRD §9, AC 4-8, 11-12)."""
import json
import os

import pytest

os.environ.setdefault("REPOPROOF_ACCESS_PASSWORD", "test-password-for-plan-api")

from fastapi.testclient import TestClient      # noqa: E402

from app import blueprint, db                  # noqa: E402
from app.main import app                       # noqa: E402

FRAMEWORK = {
    "num_questions": 5,
    "choice_count": 4,
    "correct_mode": "exact",
    "correct_exact": 1,
    "difficulty_min": 1,
    "difficulty_max": 4,
    "focus_areas": [{"id": "api", "weight": 5}, {"id": "data_flow", "weight": 4}],
    "seed": 42,
}
SCOPE = ("Retrieve OpenElectricity data from a REST API, combine power and emissions, "
         "save a CSV cache, publish ordered MQTT messages and update a dashboard.")


TEST_PASSWORD = "test-password-for-plan-api"


@pytest.fixture(scope="module")
def client():
    """Authenticated creator client — these routes are creator-only.

    config.ACCESS_PASSWORD is read at import time, so set the attribute
    directly: another test module may already have imported app.config.
    """
    from app import config
    config.ACCESS_PASSWORD = TEST_PASSWORD
    db.init()
    c = TestClient(app)
    r = c.post("/api/login", json={"password": TEST_PASSWORD})
    assert r.status_code == 200, r.text
    return c


def test_question_plan_routes_require_creator_auth():
    anon = TestClient(app)
    assert anon.get("/api/question-plans/anything").status_code == 401


@pytest.fixture(scope="module")
def project():
    """A project whose evidence chunks come from a real analysed repository."""
    from pathlib import Path

    from app import analyzer, knowledge
    db.init()
    # Committed synthetic fixture: keeps the suite deterministic and runnable on
    # a fresh clone. Real student projects live in the gitignored data/ dir and
    # must never be a test dependency.
    target = Path(__file__).parent / "fixtures" / "sample_project"
    chunks = knowledge.build_chunks(analyzer.analyze_project(target), "snapA")
    pid = db.insert("projects", {
        "name": "plan-api-fixture", "source_type": "upload", "source": "fixture.zip",
        "snapshot_id": "snapA", "chunks_json": chunks, "stats_json": {},
    })
    return pid


def _preview(client, pid, **over):
    fw = {**FRAMEWORK, **over}
    return client.post(f"/api/projects/{pid}/question-plans",
                       data={"config_json": json.dumps(fw), "project_scope": SCOPE})


# --- AC 5: preview without generation ---------------------------------------

def test_preview_returns_blueprint(client, project):
    r = _preview(client, project)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] and body["status"] == "preview"
    for key in ("requested", "assessment_point_distribution", "template_distribution",
                "planned", "unsupported", "warnings", "plot", "catalog"):
        assert key in body


def test_preview_is_persisted_and_fetchable(client, project):
    plan_id = _preview(client, project).json()["id"]
    got = client.get(f"/api/question-plans/{plan_id}")
    assert got.status_code == 200
    assert got.json()["status"] == "preview"


def test_preview_requires_a_focus_area(client, project):
    r = _preview(client, project, focus_areas=[])
    assert r.status_code == 400


def test_unknown_project_is_404(client):
    r = _preview(client, 999999)
    assert r.status_code == 404


# --- AC 8: determinism ------------------------------------------------------

def test_same_inputs_and_seed_produce_same_preview(client, project):
    a = _preview(client, project).json()
    b = _preview(client, project).json()
    assert [s["plan_key"] for s in a["planned"]] == [s["plan_key"] for s in b["planned"]]
    assert a["assessment_point_distribution"] == b["assessment_point_distribution"]


# --- AC 11: confirming freezes the blueprint --------------------------------

def test_confirm_freezes_plan(client, project):
    body = _preview(client, project).json()
    if not body["planned"]:
        pytest.skip("fixture produced no evidence-supported plans")
    r = client.post(f"/api/question-plans/{body['id']}/confirm")
    assert r.status_code == 200
    assert client.get(f"/api/question-plans/{body['id']}").json()["status"] == "confirmed"


def test_only_the_latest_preview_is_kept(client, project):
    """A new preview supersedes the previous one, which is deleted.

    Plan rows carry slot text derived from the student's code, so stale previews
    are removed rather than accumulating.
    """
    first = _preview(client, project).json()["id"]
    second = _preview(client, project).json()
    assert second["id"] != first
    assert client.get(f"/api/question-plans/{first}").status_code == 404
    assert client.get(f"/api/question-plans/{second['id']}").status_code == 200


def test_confirmed_plans_survive_a_later_preview(client, project):
    """Generation still references a confirmed plan, so it must not be pruned."""
    confirmed = _preview(client, project).json()
    if not confirmed["planned"]:
        pytest.skip("fixture produced no evidence-supported plans")
    client.post(f"/api/question-plans/{confirmed['id']}/confirm")
    _preview(client, project)
    got = client.get(f"/api/question-plans/{confirmed['id']}")
    assert got.status_code == 200
    assert got.json()["status"] == "confirmed"


def test_confirm_rejects_empty_plan(client, project):
    body = _preview(client, project, focus_areas=[{"id": "security", "weight": 5}],
                    num_questions=5).json()
    if body["planned"]:
        pytest.skip("this focus produced plans; nothing to assert")
    assert client.post(f"/api/question-plans/{body['id']}/confirm").status_code == 400


def test_confirm_rejects_stale_catalog(client, project, monkeypatch):
    body = _preview(client, project).json()
    if not body["planned"]:
        pytest.skip("fixture produced no evidence-supported plans")
    monkeypatch.setattr(blueprint, "catalog_hash", lambda: "0" * 16)
    r = client.post(f"/api/question-plans/{body['id']}/confirm")
    assert r.status_code == 409


def test_confirm_unknown_plan_is_404(client):
    assert client.post("/api/question-plans/nope/confirm").status_code == 404


# --- AC 12: generation must reference a confirmed plan ----------------------

def test_generation_rejects_unconfirmed_plan(client, project):
    body = _preview(client, project).json()
    fw = {**FRAMEWORK, "provider": "mock", "question_plan_id": body["id"]}
    r = client.post(f"/api/projects/{project}/generation-runs",
                    data={"config_json": json.dumps(fw)})
    assert r.status_code == 400
    assert "confirm" in r.text.lower()


def test_openai_generation_also_requires_a_confirmed_plan(client, project):
    fw = {**FRAMEWORK, "provider": "openai", "question_plan_id": ""}
    r = client.post(f"/api/projects/{project}/generation-runs",
                    data={"config_json": json.dumps(fw)})
    assert r.status_code == 400
    assert "confirm" in r.text.lower()


def test_generation_rejects_unknown_plan(client, project):
    fw = {**FRAMEWORK, "provider": "mock", "question_plan_id": "does-not-exist"}
    r = client.post(f"/api/projects/{project}/generation-runs",
                    data={"config_json": json.dumps(fw)})
    assert r.status_code == 404


def test_generation_rejects_plan_from_another_project(client, project):
    body = _preview(client, project).json()
    if not body["planned"]:
        pytest.skip("fixture produced no evidence-supported plans")
    client.post(f"/api/question-plans/{body['id']}/confirm")
    other = db.insert("projects", {
        "name": "other", "source_type": "upload", "source": "x.zip",
        "snapshot_id": "snapB", "chunks_json": [], "stats_json": {}})
    fw = {**FRAMEWORK, "provider": "mock", "question_plan_id": body["id"]}
    r = client.post(f"/api/projects/{other}/generation-runs",
                    data={"config_json": json.dumps(fw)})
    assert r.status_code == 400


def test_local_generation_is_handed_to_the_creator_browser(client, project):
    preview = _preview(
        client,
        project,
        num_questions=1,
        focus_areas=[{"id": "api", "weight": 5}],
    ).json()
    if not preview["planned"]:
        pytest.skip("fixture produced no evidence-supported local plan")
    assert client.post(f"/api/question-plans/{preview['id']}/confirm").status_code == 200
    framework = {
        **FRAMEWORK,
        "num_questions": 1,
        "focus_areas": [{"id": "api", "weight": 5}],
        "provider": "local",
        "model": "qwen3.5:9b",
        "question_plan_id": preview["id"],
    }
    started = client.post(
        f"/api/projects/{project}/generation-runs",
        data={"config_json": json.dumps(framework)},
    )
    assert started.status_code == 200, started.text
    run = client.get(f"/api/generation-runs/{started.json()['id']}").json()
    assert run["status"] == "awaiting_client"
    assert "_local_state" not in run
    batch = run["local_batch"]
    assert batch["model"] == "qwen3.5:9b"
    assert batch["think"] is False
    outputs = []
    for task in batch["tasks"]:
        content = json.dumps({
            "correct_options": [{
                "text": "The operation uses the integration shown by the project evidence.",
                "justification": "The supplied evidence shows this integration.",
            }],
            "incorrect_options": [{
                "text": f"The operation performs unrelated behavior {index}.",
                "justification": "That behavior conflicts with the supplied evidence.",
            } for index in range(3)],
            "explanation": "The answer follows from the supplied project evidence.",
            "confidence": 8,
        })
        outputs.append({
            "task_index": task["task_index"],
            "attempt": task["attempt"],
            "content": content,
            "duration_seconds": 1.0,
        })
    completed = client.post(
        f"/api/generation-runs/{run['id']}/local-completions",
        json={"batch_id": batch["batch_id"], "outputs": outputs},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "complete"
    assert len(completed.json()["result"]["created"]) == 1
    stored = client.get(f"/api/projects/{project}/questions").json()[0]
    assert stored["assessment_point_ids"] == preview["planned"][0]["assessment_point_ids"]
