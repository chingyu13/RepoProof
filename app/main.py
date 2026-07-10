"""FastAPI application: creator API, taker API, print view, static UI."""
import secrets
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db
from .analyzer import analyze_project
from .generator import generate_questions
from .ingest import IngestError, clone_github, extract_upload
from .knowledge import build_chunks
from .scoring import score_attempt
from .validator import validate_maq

app = FastAPI(title="RepoProof", version="0.1.0")
db.init()

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------- pages ----------

@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/a/{token}", response_class=HTMLResponse)
def assess_page(token: str):
    return FileResponse(STATIC_DIR / "assess.html")


# ---------- meta ----------

@app.get("/api/meta")
def meta():
    return {
        "mock_mode": config.mock_mode(),
        "model": config.OPENAI_MODEL,
        "max_project_mb": config.MAX_PROJECT_MB,
        "consent_text": config.CONSENT_TEXT,
        "pro_contact": config.PRO_CONTACT,
    }


# ---------- projects ----------

@app.post("/api/projects")
async def create_project(
    github_url: str = Form(""),
    consent: str = Form(""),
    file: UploadFile | None = File(None),
):
    if consent not in ("true", "on", "1"):
        raise HTTPException(400, "You must accept the consent notice to submit a project.")
    try:
        if github_url.strip():
            root, snapshot, name = clone_github(github_url)
            source_type, source = "git", github_url.strip()
        elif file is not None:
            data = await file.read()
            root, snapshot, name = extract_upload(data, file.filename or "upload.zip")
            source_type, source = "upload", file.filename or "upload.zip"
        else:
            raise HTTPException(400, "Provide a public GitHub URL or upload a .zip archive.")
    except IngestError as exc:
        raise HTTPException(400, str(exc)) from exc

    analysis = analyze_project(root)
    if analysis["stats"]["source_files"] == 0:
        detail = (
            "No supported source files found. Supported types include Python, Jupyter notebooks, "
            "R/R Markdown, Java, JavaScript/TypeScript, HTML, CSS, SQL, C/C++, C#, Go, Rust, Ruby, "
            "PHP, Shell, Kotlin, Swift, and more."
        )
        if analysis["stats"]["skipped_files"]:
            detail += " Skipped because too large: " + ", ".join(analysis["stats"]["skipped_files"])
        if analysis["errors"]:
            detail += " Parse problems: " + "; ".join(analysis["errors"][:5])
        raise HTTPException(400, detail)
    chunks = build_chunks(analysis, snapshot)
    project_id = db.insert("projects", {
        "name": name,
        "source_type": source_type,
        "source": source,
        "snapshot_id": snapshot,
        "stats_json": analysis["stats"],
        "chunks_json": chunks,
    })
    return {"id": project_id, "name": name, "snapshot_id": snapshot,
            "stats": analysis["stats"], "chunks": len(chunks),
            "parse_errors": analysis["errors"][:10]}


@app.get("/api/projects")
def list_projects():
    rows = db.list_where("projects")
    return [{k: r[k] for k in ("id", "name", "source_type", "source", "snapshot_id", "stats", "created_at")}
            for r in rows]


@app.get("/api/projects/{project_id}")
def get_project(project_id: int):
    p = db.get("projects", project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    p["chunk_count"] = len(p.pop("chunks"))
    return p


# ---------- question generation & review ----------

class GenerateConfig(BaseModel):
    num_questions: int = 5
    choice_count: int = 5
    correct_mode: str = "dynamic"      # 'exact' | 'dynamic'
    correct_exact: int = 2
    correct_min: int = 1
    correct_max: int = 3
    difficulty: int = 2
    focus: str = ""
    areas: list[dict] = []          # [{name, weight 1-5}] — focus-area radar weights


@app.post("/api/projects/{project_id}/generate")
def generate(project_id: int, cfg: GenerateConfig):
    p = db.get("projects", project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    questions, warnings = generate_questions(p["chunks"], cfg.model_dump())
    ids = []
    for q in questions:
        qid = db.insert("questions", {
            "project_id": project_id,
            "slot": q["slot"],
            "stem": q["stem"],
            "options_json": q["options"],
            "answer_json": q["answer"],
            "justifications_json": q["justifications"],
            "evidence_json": q["evidence"],
            "difficulty": q["difficulty"],
            "focus_areas_json": q["focus_areas"],
            "explanation": q["explanation"],
            "generator": q["generator"],
        })
        ids.append(qid)
    return {"created": ids, "warnings": warnings, "mock_mode": config.mock_mode()}


@app.get("/api/projects/{project_id}/questions")
def list_questions(project_id: int):
    return db.list_where("questions", "project_id=?", (project_id,), order="id ASC")


class QuestionEdit(BaseModel):
    stem: str | None = None
    options: list[dict] | None = None
    answer: list[str] | None = None
    difficulty: int | None = None
    focus_areas: list[str] | None = None
    explanation: str | None = None
    status: str | None = None          # draft | approved | rejected


@app.put("/api/questions/{question_id}")
def edit_question(question_id: int, edit: QuestionEdit):
    q = db.get("questions", question_id)
    if not q:
        raise HTTPException(404, "Question not found")
    merged = {
        "stem": edit.stem if edit.stem is not None else q["stem"],
        "options": edit.options if edit.options is not None else q["options"],
        "answer": edit.answer if edit.answer is not None else q["answer"],
        "difficulty": edit.difficulty if edit.difficulty is not None else q["difficulty"],
        "focus_areas": edit.focus_areas if edit.focus_areas is not None else q["focus_areas"],
        "explanation": edit.explanation if edit.explanation is not None else q["explanation"],
        "evidence": q["evidence"],
    }
    status = edit.status if edit.status is not None else q["status"]
    if status == "approved":
        errs = validate_maq(merged, choice_count=len(merged["options"]))
        if errs:
            raise HTTPException(422, "Cannot approve: " + " ".join(errs))
    db.update("questions", question_id, {
        "stem": merged["stem"],
        "options_json": merged["options"],
        "answer_json": sorted(set(merged["answer"])),
        "difficulty": merged["difficulty"],
        "focus_areas_json": merged["focus_areas"],
        "explanation": merged["explanation"],
        "status": status,
    })
    return db.get("questions", question_id)


# ---------- assessments ----------

class PublishRequest(BaseModel):
    title: str
    question_ids: list[int]
    show_correct_count: bool = False


@app.post("/api/projects/{project_id}/assessments")
def publish(project_id: int, req: PublishRequest):
    if not db.get("projects", project_id):
        raise HTTPException(404, "Project not found")
    if not req.question_ids:
        raise HTTPException(400, "Select at least one question.")
    for qid in req.question_ids:
        q = db.get("questions", qid)
        if not q or q["project_id"] != project_id:
            raise HTTPException(400, f"Question {qid} does not belong to this project.")
        if q["status"] != "approved":
            raise HTTPException(400, f"Question {qid} is not approved yet. Approve all questions before publishing.")
    token = secrets.token_urlsafe(8)
    aid = db.insert("assessments", {
        "project_id": project_id,
        "title": req.title.strip() or "Untitled assessment",
        "token": token,
        "question_ids_json": req.question_ids,
        "config_json": {"show_correct_count": req.show_correct_count},
    })
    return {"id": aid, "token": token, "take_url": f"/a/{token}", "print_url": f"/print/{aid}"}


@app.get("/api/projects/{project_id}/assessments")
def list_assessments(project_id: int):
    rows = db.list_where("assessments", "project_id=?", (project_id,))
    out = []
    for a in rows:
        attempts = db.list_where("attempts", "assessment_id=?", (a["id"],))
        out.append({"id": a["id"], "title": a["title"], "token": a["token"],
                    "created_at": a["created_at"], "questions": len(a["question_ids"]),
                    "attempts": len(attempts)})
    return out


@app.get("/api/assessments/{assessment_id}/attempts")
def list_attempts(assessment_id: int):
    return db.list_where("attempts", "assessment_id=?", (assessment_id,))


# ---------- taking ----------

def _assessment_by_token(token: str) -> dict:
    a = db.get_where("assessments", "token=?", (token,))
    if not a:
        raise HTTPException(404, "Assessment not found")
    return a


@app.get("/api/take/{token}")
def take(token: str):
    a = _assessment_by_token(token)
    show_count = a["config"].get("show_correct_count", False)
    questions = []
    for qid in a["question_ids"]:
        q = db.get("questions", qid)
        item = {"id": q["id"], "stem": q["stem"], "options": q["options"],
                "difficulty": q["difficulty"]}
        if show_count:
            item["correct_count"] = len(q["answer"])
        questions.append(item)
    return {"title": a["title"], "questions": questions,
            "scoring": "Exact match: a question is correct only when your selected set exactly matches the answer key."}


class SubmitRequest(BaseModel):
    taker_name: str = ""
    responses: dict[str, list[str]]


@app.post("/api/take/{token}/submit")
def submit(token: str, req: SubmitRequest):
    a = _assessment_by_token(token)
    questions = [db.get("questions", qid) for qid in a["question_ids"]]
    score = score_attempt(questions, req.responses)
    db.insert("attempts", {
        "assessment_id": a["id"],
        "taker_name": req.taker_name.strip()[:80],
        "responses_json": req.responses,
        "score_json": score,
    })
    return score


# ---------- printable export ----------

@app.get("/print/{assessment_id}", response_class=HTMLResponse)
def print_view(assessment_id: int, key: int = 0):
    a = db.get("assessments", assessment_id)
    if not a:
        raise HTTPException(404, "Assessment not found")
    project = db.get("projects", a["project_id"])
    parts = [f"""<!doctype html><html><head><meta charset="utf-8">
<title>{a['title']} — RepoProof</title>
<style>
 body{{font-family:Georgia,serif;max-width:800px;margin:2rem auto;line-height:1.5;color:#111}}
 .q{{margin:1.5rem 0;page-break-inside:avoid}} .opt{{margin:.25rem 0 .25rem 1.5rem}}
 .meta{{color:#555;font-size:.9rem}} .key{{background:#f6f6f6;padding:.5rem 1rem;border-left:3px solid #888}}
 @media print{{.noprint{{display:none}}}}
</style></head><body>
<p class="noprint"><a href="javascript:window.print()">Print this page</a></p>
<h1>{a['title']}</h1>
<p class="meta">Project: {project['name']} — snapshot {project['snapshot_id']} — RepoProof offline assessment.
Select ALL correct options; a question counts only when your selection matches exactly.</p>"""]
    for i, qid in enumerate(a["question_ids"], 1):
        q = db.get("questions", qid)
        parts.append(f'<div class="q"><p><strong>Q{i}.</strong> {q["stem"]} '
                     f'<span class="meta">(difficulty {q["difficulty"]})</span></p>')
        for opt in q["options"]:
            parts.append(f'<p class="opt">☐ <strong>{opt["key"]}.</strong> {opt["text"]}</p>')
        if key:
            ev = "; ".join(f'{e["title"]}' + (f' ({e["file"]} {e["lines"]})' if e.get("file") else "")
                           for e in q["evidence"]) or "—"
            parts.append(f'<div class="key"><p><strong>Answer:</strong> {", ".join(q["answer"])}</p>'
                         f'<p><strong>Evidence:</strong> {ev}</p>'
                         f'<p>{q["explanation"]}</p></div>')
        parts.append("</div>")
    parts.append(f'<p class="meta noprint">Answer key: append ?key=1 to this URL.</p></body></html>')
    return HTMLResponse("".join(parts))
