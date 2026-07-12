# RepoProof

**Turn a code project into an evidence-grounded understanding assessment.**

RepoProof analyzes a real codebase and generates multi-answer questions grounded in its actual implementation — testing whether someone *understands* a project, not just whether they can produce one with code-generation tools.

### 🔗 Live: **[repoproof.chingyu.site](https://repoproof.chingyu.site/)**

The landing page includes a **public guided demo** (no login needed). The full creator interface sits behind a shared password.

---

## What it is

Point RepoProof at a repository — a public GitHub URL, a `.zip`, or a browser folder selection — and it:

1. Takes an **immutable snapshot** (git commit prefix or archive checksum) and analyzes the code.
2. Builds **provenance-tagged evidence** from that analysis (every fact traces back to a file, line/cell, and snapshot).
3. Uses retrieval + an LLM to generate **multi-answer questions (MAQs)** grounded strictly in that evidence.
4. Lets a human **review, edit, approve** questions, then **publish** a shareable assessment.
5. Scores attempts by **exact match**, with a per-focus-area breakdown.

Because every question is tied to the analyzed snapshot, results are always traceable to a specific version of the code.

**Use cases:** CS education (do students understand what they submitted?), engineering hiring (a project-specific screen before an interview), and self-assessment of a codebase, notebook, or data project.

RepoProof measures *demonstrated understanding*. It does not prove authorship or conclusively detect AI-generated work.

---

## Architecture

RepoProof is a **retrieval-augmented generation (RAG) pipeline** with a human-in-the-loop review stage and an operational-telemetry layer, wrapped in a FastAPI service.

```text
Project intake  (GitHub clone / .zip upload / folder)
        ↓   immutable snapshot: git SHA or archive checksum
Static analysis  (Python AST + multi-language text analysis)
        ↓
Evidence-chunk construction  (file / line / cell / snapshot provenance)
        ↓
BM25 retrieval  (steered by question blueprint + focus-area weights)
        ↓
LLM generation  (strict-JSON, evidence-grounded)  OR  deterministic mock
        ↓
Constraint validation  +  validate-and-retry
        ↓
Human review  (edit / drag-reorder / approve / reject)
        ↓
Publish → Take → Exact-match scoring  (per-focus-area breakdown)
```

### Key techniques

- **RAG grounding.** Analysis is decomposed into evidence chunks; a **BM25** retriever (with a custom tokenizer that splits `snake_case`) selects the relevant chunks per question, and the prompt enforces a "cite only these evidence ids / never invent facts" contract.
- **Static analysis.** Python gets a deep `ast` walk — functions, classes, imports, and an approximate **call graph**. Jupyter notebooks are parsed per cell. 30+ other file types get lightweight declaration extraction.
- **Constrained generation + self-correction.** The model is called in **strict JSON mode** against a fixed schema; options are shuffled to remove positional bias; each candidate is validated, and on failure the generator **retries once with the validation errors fed back into the prompt**.
- **Constraint validation.** Every MAQ must have 2–7 distinct options, one unambiguous correct combination (all-correct disallowed), difficulty 1–5, and linked evidence — the same gate blocks human approval.
- **Focus-area steering.** An interactive radar chart weights areas (Architecture, Testing, …); weights expand into a proportional question schedule.
- **MLOps telemetry.** An append-only event log captures generation config and human review/edit signals (derived metadata only — never raw code); a metrics endpoint aggregates approval rate, human-edit rate, and validator-block rate for comparing prompt/model versions.
- **Auth & intake security.** Creator routes are protected by HMAC-signed `httponly` session cookies behind a password gate; intake validates GitHub URLs, runs shallow timed clones, guards against zip path traversal, and gates total project size.
- **Deterministic mock mode.** With no API key, RepoProof produces evidence-grounded sample questions labeled `[MOCK]`, so the entire flow is demoable without spending tokens.

> A deeper write-up of the architecture and techniques lives in [`overview_repoproof.md`](overview_repoproof.md).

### Tech stack

Python · FastAPI · Uvicorn · Pydantic · OpenAI API (JSON mode) · `rank_bm25` · Python `ast` · SQLite (JSON columns + lightweight migrations) · vanilla-JS frontend with Figma-synced CSS design tokens and inline SVG.

### Project layout

```text
app/
├── ingest.py      # GitHub clone / .zip extraction, size & path-traversal guards
├── analyzer.py    # Python AST + multi-language file analysis
├── knowledge.py   # evidence chunks + BM25 retrieval
├── generator.py   # LLM & mock MAQ generation (+ validate-and-retry)
├── validator.py   # MAQ schema & rule validation
├── scoring.py     # exact-match + per-focus-area scoring
├── db.py          # SQLite storage, migrations, telemetry events
├── config.py      # env config, mock mode, consent copy/versioning
├── main.py        # FastAPI routes, session auth, middleware
└── static/        # index (landing/login), creator, demo, assess UIs
```

---

## Supported projects

Python receives the deepest analysis (functions, classes, imports, approximate call edges, docstrings, source snippets). Lightweight file-level analysis covers Jupyter notebooks (per-cell), R/R Markdown, Java/Kotlin/Scala/Swift, JavaScript/TypeScript/JSX/TSX/Vue, HTML/CSS/SCSS, SQL, C/C++/C#/Go/Rust, Ruby/PHP/Perl/Lua/Julia/Dart, Shell/PowerShell/MATLAB, and JSON/YAML/TOML. Question quality scales with analysis depth.

## Scope & limitations

RepoProof is an early prototype, and its boundaries are deliberate seams for later upgrades: shared-password access (no per-user accounts or tenant isolation); public GitHub repos only; BM25-only retrieval (no embeddings/hybrid yet); SQLite rather than PostgreSQL; exact-match scoring (no partial credit yet); non-Python languages use lightweight parsing rather than full ASTs; and no automated test suite or container image yet.

**Roadmap:** partial-credit scoring · Tree-sitter parsers · semantic/hybrid retrieval · private-repo support · per-user auth & organizations · PostgreSQL + pgvector · retention/deletion lifecycle · production packaging.

## Responsible use

Repository familiarity is evidence of understanding, not definitive evidence of authorship. Education and hiring assessments should include human review, clear scoring rules, an appeal process, and appropriate accommodations. Don't submit projects you aren't authorized to process, and review your model provider's data-handling terms before analyzing sensitive code.

---

<sub>Running locally is possible (`pip install -r requirements.txt` then `python run.py`), but RepoProof is primarily meant to be viewed live at **[repoproof.chingyu.site](https://repoproof.chingyu.site/)**.</sub>
