"""FastAPI application: creator API, taker API, print view, static UI."""
import hashlib
import hmac
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from . import config, db
from .analyzer import analyze_project, prune_non_source
from .generator import generate_questions
from .ingest import IngestError, clone_github, delete_project_files, extract_upload, raw_project_files
from .knowledge import available_evidence_types, build_chunks
from .scoring import score_attempt
from .strategies import public_catalog
from .validator import normalize_answer, validate_maq

app = FastAPI(title="RepoProof", version="0.1.0")
db.init()

STATIC_DIR = Path(__file__).parent / "static"
COOKIE_NAME = "repoproof_creator"
_SESSION_SECRET = config.SESSION_SECRET or secrets.token_urlsafe(32)


def _session_token() -> str:
    """Stateless session: the cookie value is HMAC(secret, constant), so it is
    the SAME for every login and stays valid until the secret changes. No
    server-side session store is needed, but note two consequences: (1) the
    cookie can't be revoked per-user — rotate REPOPROOF_SESSION_SECRET to kill
    all sessions; (2) max_age only expires it client-side. Fine for a
    single-creator prototype; use per-session tokens with expiry for multi-user."""
    return hmac.new(_SESSION_SECRET.encode(), b"creator-access", hashlib.sha256).hexdigest()


def _authenticated(request: Request) -> bool:
    supplied = request.cookies.get(COOKIE_NAME, "")
    # compare_digest = constant-time comparison; a plain `==` would leak how
    # many leading characters match through response-timing differences.
    return bool(supplied) and secrets.compare_digest(supplied, _session_token())


def _requires_creator_auth(path: str) -> bool:
    return path == "/creator" or path.startswith((
        "/api/meta",
        "/api/projects",
        "/api/questions",
        "/api/assessments",
        "/print/",
        "/docs",
        "/redoc",
        "/openapi.json",
    ))


@app.middleware("http")
async def protect_creator_routes(request: Request, call_next):
    if _requires_creator_auth(request.url.path) and not _authenticated(request):
        if request.url.path == "/creator":
            return RedirectResponse("/?login=required", status_code=303)
        return JSONResponse({"detail": "Creator authentication required."}, status_code=401)
    return await call_next(request)


# ---------- pages ----------

@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/creator", response_class=HTMLResponse)
def creator_page():
    return FileResponse(STATIC_DIR / "creator.html")


@app.get("/demo", response_class=HTMLResponse)
@app.get("/demo/", response_class=HTMLResponse)
@app.get("/demo.html", response_class=HTMLResponse)
def demo_page():
    return FileResponse(STATIC_DIR / "demo.html")


@app.get("/a/{token}", response_class=HTMLResponse)
def assess_page(token: str):
    return FileResponse(STATIC_DIR / "assess.html")


# ---------- creator access ----------

class LoginRequest(BaseModel):
    password: str


@app.post("/api/login")
def login(req: LoginRequest, request: Request):
    if not config.ACCESS_PASSWORD:
        raise HTTPException(503, "Creator access is not configured on this server.")
    if not secrets.compare_digest(req.password, config.ACCESS_PASSWORD):
        raise HTTPException(401, "Incorrect password.")
    response = JSONResponse({"ok": True})
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    response.set_cookie(
        COOKIE_NAME,
        _session_token(),
        max_age=8 * 60 * 60,
        httponly=True,
        secure=request.url.scheme == "https" or forwarded_proto == "https",
        samesite="lax",
    )
    return response


@app.post("/api/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME)
    return response


# ---------- meta ----------

@app.get("/api/meta")
def meta():
    local_up = config.local_llm_available()
    assessment_catalog = public_catalog()
    return {
        "mock_mode": config.mock_mode(),
        "model": config.OPENAI_MODEL,
        "providers": {
            "default": config.default_provider(),
            "openai": {"available": bool(config.openai_api_key()), "model": config.OPENAI_MODEL},
            "local": {"available": local_up, "model": config.LOCAL_LLM_MODEL, "url": config.LOCAL_LLM_URL},
        },
        "strategies": assessment_catalog["strategies"],
        "topics": assessment_catalog["topics"],
        "templates": assessment_catalog["templates"],
        "evidence_types": assessment_catalog["evidence_types"],
        "max_project_mb": config.MAX_PROJECT_MB,
        "consent_text": config.CONSENT_TEXT,
        "data_sharing_text": config.DATA_SHARING_TEXT,
        "consent_version": config.CONSENT_VERSION,
        "pro_contact": config.PRO_CONTACT,
    }


# ---------- projects ----------

def _truthy(v: str) -> bool:
    return str(v).lower() in ("true", "on", "1", "yes")


@app.post("/api/projects")
async def create_project(
    github_url: str = Form(""),
    consent: str = Form(""),           # required acknowledgment (kept name for compat)
    acknowledge: str = Form(""),       # required acknowledgment (preferred)
    share_data: str = Form(""),        # optional de-identified data-sharing opt-in
    file: UploadFile | None = File(None),
):
    acknowledged = _truthy(acknowledge) or _truthy(consent)
    if not acknowledged:
        raise HTTPException(400, "You must accept the required acknowledgment to submit a project.")
    share = _truthy(share_data)
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

    # After the size gate, strip non-programming files (images, media, fonts,
    # archives, binaries) and noise dirs so only code/text is analyzed and stored.
    prune = prune_non_source(root)
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
    consent_record = {
        "acknowledged": True,
        "share_data": share,
        "consent_version": config.CONSENT_VERSION,
        "at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    project_id = db.insert("projects", {
        "name": name,
        "source_type": source_type,
        "source": source,
        "project_path": str(root.resolve()),
        "snapshot_id": snapshot,
        "stats_json": analysis["stats"],
        "chunks_json": chunks,
        "consent_json": consent_record,
    })
    db.log_event("project_created", {
        "source_type": source_type,
        "source_files": analysis["stats"].get("source_files"),
        "chunks": len(chunks),
        "pruned_files": prune["removed"],
        "pruned_mb": prune["removed_mb"],
        "share_data": share,
        "consent_version": config.CONSENT_VERSION,
    }, project_id=project_id)
    return {"id": project_id, "name": name, "snapshot_id": snapshot,
            "stats": analysis["stats"], "chunks": len(chunks),
            "pruned": prune,
            "share_data": share,
            "parse_errors": analysis["errors"][:10]}


@app.get("/api/projects")
def list_projects():
    rows = db.list_where("projects")
    return [{k: r[k] for k in ("id", "name", "source_type", "source", "snapshot_id", "stats", "created_at")}
            for r in rows if _project_root(r) is not None]


@app.get("/api/projects/{project_id}")
def get_project(project_id: int):
    p = db.get("projects", project_id)
    if not p or _project_root(p) is None:
        raise HTTPException(404, "Project not found")
    p["evidence_types"] = available_evidence_types(p["chunks"])
    p["chunk_count"] = len(p.pop("chunks"))
    return p


# ---------- question generation & review ----------

class GenerateConfig(BaseModel):
    num_questions: int = 5
    choice_count: int = 4
    correct_mode: str = "exact"
    correct_exact: int = 1
    correct_min: int = 1
    correct_max: int = 3
    difficulty: int = 3
    focus: str = ""
    topic: str = ""
    focus_areas: list[dict] = []
    template: str = ""
    areas: list[dict] = []
    provider: str = ""
    keep_approved: bool = False


def _project_root(project: dict) -> Path | None:
    stored_value = str(project.get("project_path") or "").strip()
    if not stored_value:
        return None
    stored = Path(stored_value)
    if stored.is_dir():
        return stored
    return None


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int):
    project = db.get("projects", project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    root = _project_root(project)
    if root is not None:
        delete_project_files(root)

    assessment_ids = [row["id"] for row in db.list_where(
        "assessments", "project_id=?", (project_id,), order="id ASC",
    )]
    for assessment_id in assessment_ids:
        db.delete_where("attempts", "assessment_id=?", (assessment_id,))
    db.delete_where("assessments", "project_id=?", (project_id,))
    db.delete_where("questions", "project_id=?", (project_id,))
    db.delete_where("events", "project_id=?", (project_id,))
    db.delete("projects", project_id)
    return {"ok": True}


@app.post("/api/projects/{project_id}/generate")
def generate(project_id: int, cfg: GenerateConfig):
    p = db.get("projects", project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    raw_files = None
    provider = (cfg.provider or config.default_provider()).lower()
    if provider == "openai":
        root = _project_root(p)
        if root is None:
            raise HTTPException(
                409,
                "Raw GPT generation needs the original project files. Re-upload this older project first.",
            )
        try:
            raw_files = raw_project_files(root, config.OPENAI_RAW_MAX_CHARS)
        except IngestError as exc:
            raise HTTPException(400, str(exc)) from exc
    questions, warnings = generate_questions(p["chunks"], cfg.model_dump(), raw_files=raw_files)
    # A fresh generation REPLACES the previous pool so the review list shows
    # exactly the batch just requested. By default everything goes; with
    # keep_approved, approved questions survive. Questions referenced by a
    # published assessment are ALWAYS kept (assessment integrity).
    replaced = 0
    used: set[int] = set()
    if questions:
        for a in db.list_where("assessments", "project_id=?", (project_id,)):
            used.update(a["question_ids"])
        for old in db.list_where("questions", "project_id=?", (project_id,)):
            if cfg.keep_approved and old["status"] == "approved":
                continue
            if old["id"] in used:
                # referenced by a published assessment: the row must survive so old
                # take-links keep working, but ARCHIVE it so it leaves the review
                # pool — it stays visible in the Step-4 assessment history instead.
                if old["status"] != "archived":
                    db.update("questions", old["id"], {"status": "archived"})
                    replaced += 1
                continue
            db.delete("questions", old["id"])
            replaced += 1
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
    provider_used = questions[0]["generator"] if questions else (cfg.provider or config.default_provider())
    db.log_event("generation_run", {
        "model": provider_used,
        "mock_mode": config.mock_mode(),
        "requested": cfg.num_questions,
        "created": len(ids),
        "choice_count": cfg.choice_count,
        "correct_mode": cfg.correct_mode,
        "difficulty": cfg.difficulty,
        "topic": cfg.topic,
        "focus_areas": [
            {"id": area.get("id"), "name": area.get("name"), "weight": area.get("weight")}
            for area in cfg.focus_areas if area.get("id") or area.get("name")
        ],
        "template_selection": "focus_matrix",
        "template_override": cfg.template or None,
        "areas": [a.get("name") for a in cfg.areas if a.get("name")],
        "warnings": len(warnings),
    }, project_id=project_id)
    return {"created": ids, "warnings": warnings, "mock_mode": config.mock_mode(),
            "provider": provider_used, "replaced_drafts": replaced}


@app.get("/api/projects/{project_id}/questions")
def list_questions(project_id: int):
    # Newest first: every generation batch APPENDS to this project's question
    # pool, so ascending order buried fresh questions under old batches and
    # made new settings look like they "did nothing". Archived questions
    # (kept only because a published assessment references them) are hidden —
    # they live in the Step-4 assessment history instead.
    return db.list_where("questions", "project_id=? AND status != 'archived'",
                         (project_id,), order="id DESC")


@app.delete("/api/questions/{question_id}")
def delete_question(question_id: int):
    """Permanently remove a draft — refused if any published assessment uses it."""
    q = db.get("questions", question_id)
    if not q:
        raise HTTPException(404, "Question not found")
    for a in db.list_where("assessments", "project_id=?", (q["project_id"],)):
        if question_id in a["question_ids"]:
            raise HTTPException(400, f"Question {question_id} is part of assessment "
                                     f"“{a['title']}” and cannot be deleted.")
    db.delete("questions", question_id)
    db.log_event("question_review", {
        "question_id": question_id, "action": "deleted",
        "generator": q["generator"], "slot": q["slot"],
    }, project_id=q["project_id"])
    return {"ok": True}


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
    # "Did a human change the model's output?" — compared field by field
    # against the stored row. This flag feeds the human_edit_rate metric:
    # a high rate means generation quality is too low to approve as-is.
    edited = any([
        merged["stem"] != q["stem"],
        merged["options"] != q["options"],
        sorted(set(merged["answer"])) != sorted(set(q["answer"])),
        merged["difficulty"] != q["difficulty"],
        merged["explanation"] != q["explanation"],
    ])
    if status == "approved":
        errs = validate_maq(merged, choice_count=len(merged["options"]))
        if errs:
            db.log_event("question_review", {
                "question_id": question_id, "action": "approve_blocked",
                "generator": q["generator"], "reasons": errs,
            }, project_id=q["project_id"])
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
    db.log_event("question_review", {
        "question_id": question_id,
        "action": status,                 # draft | approved | rejected
        "status_changed": status != q["status"],
        "edited": edited,                 # human corrected model output → training signal
        "generator": q["generator"],
        "slot": q["slot"],
    }, project_id=q["project_id"])
    return db.get("questions", question_id)


# ---------- assessments ----------

class PublishRequest(BaseModel):
    title: str
    question_ids: list[int]
    show_correct_count: bool = False
    adaptive: bool = False             # adaptive ORDER: all questions still asked
    framework: dict = {}               # step-2 settings snapshot, shown in assessment history


@app.post("/api/projects/{project_id}/assessments")
def publish(project_id: int, req: PublishRequest):
    if not db.get("projects", project_id):
        raise HTTPException(404, "Project not found")
    if not req.question_ids:
        raise HTTPException(400, "Select at least one question.")
    # Positions as shown in the review list (newest first, archived hidden) so
    # error messages say "Q4", matching what the creator sees on screen.
    review = db.list_where("questions", "project_id=? AND status != 'archived'",
                           (project_id,), order="id DESC")
    pos = {q["id"]: i + 1 for i, q in enumerate(review)}

    def _label(qid: int) -> str:
        return f"Q{pos[qid]} (ref #{qid})" if qid in pos else f"question ref #{qid}"

    for qid in req.question_ids:
        q = db.get("questions", qid)
        if not q or q["project_id"] != project_id:
            raise HTTPException(400, f"{_label(qid)} no longer exists in this project — "
                                     "it was probably replaced by a newer generation. Reload and reselect.")
        if q["status"] != "approved":
            raise HTTPException(400, f"{_label(qid)} is not approved yet. Approve all questions before publishing.")
    token = secrets.token_urlsafe(8)
    aid = db.insert("assessments", {
        "project_id": project_id,
        "title": req.title.strip() or "Untitled assessment",
        "token": token,
        "question_ids_json": req.question_ids,
        "config_json": {"show_correct_count": req.show_correct_count,
                        "adaptive": req.adaptive,
                        "framework": req.framework},
    })
    db.log_event("publish", {
        "assessment_id": aid, "questions": len(req.question_ids),
        "show_correct_count": req.show_correct_count,
        "adaptive": req.adaptive,
    }, project_id=project_id)
    return {"id": aid, "token": token, "take_url": f"/a/{token}", "print_url": f"/print/{aid}"}


@app.get("/api/projects/{project_id}/metrics")
def project_metrics(project_id: int):
    """Operational MLOps summary for a project, derived from telemetry events."""
    if not db.get("projects", project_id):
        raise HTTPException(404, "Project not found")
    reviews = [e["data"] for e in db.list_where("events", "project_id=? AND kind='question_review'",
                                                 (project_id,))]
    gens = [e["data"] for e in db.list_where("events", "project_id=? AND kind='generation_run'",
                                             (project_id,))]
    decided = [r for r in reviews if r.get("action") in ("approved", "rejected")]
    approved = [r for r in decided if r.get("action") == "approved"]
    edited = [r for r in reviews if r.get("edited")]
    blocked = [r for r in reviews if r.get("action") == "approve_blocked"]
    generated = sum(g.get("created", 0) for g in gens)
    return {
        "generation_runs": len(gens),
        "questions_generated": generated,
        "reviewed": len(decided),
        "approved": len(approved),
        "rejected": len(decided) - len(approved),
        "approval_rate": round(len(approved) / len(decided), 3) if decided else None,
        "human_edit_rate": round(len(edited) / len(reviews), 3) if reviews else None,
        "validator_blocks": len(blocked),
    }


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


@app.get("/api/assessments/{assessment_id}")
def assessment_detail(assessment_id: int):
    """Creator-side history view: the step-2 framework snapshot this assessment
    was generated/published with, plus that version's full question set
    (including answers — this route is behind creator auth)."""
    a = db.get("assessments", assessment_id)
    if not a:
        raise HTTPException(404, "Assessment not found")
    questions = [q for qid in a["question_ids"] if (q := db.get("questions", qid))]
    return {"id": a["id"], "title": a["title"], "created_at": a["created_at"],
            "token": a["token"], "config": a["config"],
            "framework": a["config"].get("framework", {}),
            "questions": questions}


@app.get("/api/assessments/{assessment_id}/attempts")
def list_attempts(assessment_id: int):
    return db.list_where("attempts", "assessment_id=?", (assessment_id,))


# ---------- taking ----------

def _assessment_by_token(token: str) -> dict:
    a = db.get_where("assessments", "token=?", (token,))
    if not a:
        raise HTTPException(404, "Assessment not found")
    return a


def _taker_item(q: dict, show_count: bool) -> dict:
    # SECURITY: build the taker payload by whitelisting fields — answer,
    # justifications, and evidence must never reach the taker's browser.
    item = {"id": q["id"], "stem": q["stem"], "options": q["options"],
            "difficulty": q["difficulty"]}
    if show_count:
        item["correct_count"] = len(q["answer"])
    return item


@app.get("/api/take/{token}")
def take(token: str):
    a = _assessment_by_token(token)
    show_count = a["config"].get("show_correct_count", False)
    adaptive = a["config"].get("adaptive", False)
    # Adaptive assessments deliver questions one at a time via /next, so the
    # full list (which would reveal the ordering pool) is withheld here.
    questions = [] if adaptive else [_taker_item(db.get("questions", qid), show_count)
                                     for qid in a["question_ids"]]
    return {"title": a["title"], "questions": questions,
            "adaptive": adaptive, "total": len(a["question_ids"]),
            "scoring": "Exact match: a question is correct only when your selected set exactly matches the answer key."}


class NextRequest(BaseModel):
    responses: dict[str, list[str]] = {}
    order: list[int] = []              # question ids in the order they were answered


@app.post("/api/take/{token}/next")
def take_next(token: str, req: NextRequest):
    """Adaptive ORDER selection from the pre-approved bank. Every question is
    still asked exactly once (so scoring/comparability are unchanged) — only
    the sequence adapts: answer correctly and the next question is one
    difficulty step harder, miss and it is one step easier. Correctness is
    judged server-side and never returned, so nothing leaks mid-assessment.
    Stateless by design: the client resends its answers-so-far each time."""
    a = _assessment_by_token(token)
    if not a["config"].get("adaptive", False):
        raise HTTPException(400, "This assessment is not adaptive — use GET /api/take/{token}.")
    bank = {qid: db.get("questions", qid) for qid in a["question_ids"]}
    answered = [qid for qid in req.order if qid in bank]
    remaining = [qid for qid in a["question_ids"] if qid not in set(answered)]
    total = len(a["question_ids"])
    if not remaining:
        return {"done": True, "answered": len(answered), "total": total}
    if answered:
        last = bank[answered[-1]]
        correct = normalize_answer(req.responses.get(str(last["id"]), [])) == normalize_answer(last["answer"])
        target = max(1, min(5, last["difficulty"] + (1 if correct else -1)))
    else:
        target = 3   # start mid-difficulty
    next_id = min(remaining, key=lambda qid: (abs(bank[qid]["difficulty"] - target), qid))
    return {"done": False,
            "question": _taker_item(bank[next_id], a["config"].get("show_correct_count", False)),
            "answered": len(answered), "total": total}


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
    # Escape dynamic assessment content before using this route in multi-tenant mode.
    parts = [f"""<!doctype html><html><head><meta charset="utf-8">
<title>{a['title']} — RepoProof</title>
<style>
 body{{font-family:Georgia,serif;max-width:800px;margin:2rem auto;line-height:1.5;color:#111}}
 .q{{margin:1.5rem 0;page-break-inside:avoid}} .q p{{white-space:pre-wrap}}
 .opt{{margin:.25rem 0 .25rem 1.5rem}}
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
