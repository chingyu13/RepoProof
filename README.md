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

**Use cases:** CS education (do students understand what they submitted?), engineering hiring (a project-specific screening assessment), and self-assessment of a codebase, notebook, or data project.

RepoProof measures *demonstrated understanding*. It does not prove authorship or conclusively detect AI-generated work.

---

## Architecture

RepoProof is a **retrieval-augmented generation (RAG) pipeline** with a human-in-the-loop review stage and an operational-telemetry layer, wrapped in a FastAPI service.

```text
Project intake  (GitHub clone / .zip upload / folder)
        ↓   immutable snapshot: git SHA or archive checksum
Static analysis  (shared IR: Python AST + tree-sitter pilot + generic fallback)
        ↓
Evidence-chunk construction  (file / line / cell / snapshot provenance)
        ↓
Assessment context  (prior knowledge + scope/rubric → aligned targets)
        ↓
Focus × Template selection  →  template-specific BM25 evidence bundle
        ↓
Provider branch:
  Local/Mock → structured Evidence + Template pipeline
  OpenAI     → temporary raw-project template-research baseline
        ↓
Constraint validation  +  bounded repair/regeneration
        ↓
Human review  (edit / drag-reorder / approve / reject)
        ↓
Publish → Take → Exact-match scoring  (per-focus-area breakdown)
```

### Key techniques

- **RAG grounding.** Analysis is decomposed into evidence chunks; a **BM25** retriever (with a custom tokenizer that splits `snake_case`) selects the relevant chunks per question, and the prompt enforces a "cite only these evidence ids / never invent facts" contract.
- **Static analysis.** All parsers emit one shared IR. Python and notebooks use `ast`; Java, JavaScript, TypeScript, C, and C++ use tree-sitter; remaining supported languages use a generic declaration/text fallback.
- **Constrained generation + self-correction.** Local questions use strict JSON, backend-owned Focus/difficulty/evidence, option shuffling, one targeted repair, then one alternate-evidence regeneration. Invalid questions are never silently published.
- **Constraint validation.** Every MAQ must have 2–7 distinct options, one unambiguous correct combination (all-correct disallowed), difficulty 1–5, and linked evidence — the same gate blocks human approval.
- **Focus-area steering.** An interactive radar chart weights areas (Architecture, Testing, …); weights allocate question topics, then a Focus × Template matrix selects evidence-sufficient question forms.
- **Assessment alignment.** Lecture/prior-knowledge material and project scope, requirements, or rubrics can be entered or uploaded as PDF, DOCX, PPTX, or text. RepoProof extracts weighted targets, matches them to static evidence with the shared tokenizer/concept lexicon, and shows the selected target on each review question.
- **MLOps telemetry.** An append-only event log captures generation config and human review/edit signals (derived metadata only — never raw code); a metrics endpoint aggregates approval rate, human-edit rate, and validator-block rate for comparing prompt/model versions.
- **Auth & intake security.** Creator routes are protected by HMAC-signed `httponly` session cookies behind a password gate; intake validates GitHub URLs, runs shallow timed clones, guards against zip path traversal, and gates total project size.
- **Deterministic mock mode.** With no API key, RepoProof produces evidence-grounded sample questions labeled `[MOCK]`, so the entire flow is demoable without spending tokens.

### Tech stack

Python · FastAPI · Uvicorn · Pydantic · OpenAI API (JSON mode) · `rank_bm25` · Python `ast` · SQLite (JSON columns + lightweight migrations) · vanilla-JS frontend with Figma-synced CSS design tokens and inline SVG.

### Project layout

```text
app/
├── ingest.py      # GitHub clone / .zip extraction, size & path-traversal guards
├── analyzer.py    # language parsers + shared static-analysis IR
├── knowledge.py   # evidence chunks + BM25 retrieval
├── alignment.py   # context extraction + assessment-target/evidence alignment
├── assessment_catalog.py # catalog validation + weighted template scheduling
├── generator.py   # Local/mock and raw-OpenAI generation orchestration
├── validator.py   # MAQ schema & rule validation
├── scoring.py     # exact-match + per-focus-area scoring
├── db.py          # SQLite storage, migrations, telemetry events
├── config.py      # env config, provider selection, consent copy/versioning
├── main.py        # FastAPI routes, session auth, middleware
└── static/        # index (landing/login), creator, demo, assess UIs
assessment_catalog.json # authoritative Topics/Templates/Strategies/Evidence requirements
```

---

## Supported projects

Python receives the deepest analysis (functions, classes, imports, approximate call edges, docstrings, source snippets). Lightweight file-level analysis covers Jupyter notebooks (per-cell), R/R Markdown, Java/Kotlin/Scala/Swift, JavaScript/TypeScript/JSX/TSX/Vue, HTML/CSS/SCSS, SQL, C/C++/C#/Go/Rust, Ruby/PHP/Perl/Lua/Julia/Dart, Shell/PowerShell/MATLAB, and JSON/YAML/TOML. Question quality scales with analysis depth.

## Scope & limitations

RepoProof is an early prototype, and its boundaries are deliberate seams for later upgrades: shared-password access (no per-user accounts or tenant isolation); public GitHub repos only; BM25-only retrieval (no embeddings/hybrid yet); SQLite rather than PostgreSQL; exact-match scoring (no partial credit yet); and generic rather than grammar-based parsing outside the current tree-sitter pilot languages.

**Roadmap:** partial-credit scoring · wider grammar-based parsing · semantic/hybrid retrieval · private-repo support · per-user auth & organizations · PostgreSQL + pgvector · retention/deletion lifecycle · production packaging.

## Responsible use

Repository familiarity is evidence of understanding, not definitive evidence of authorship. Education and hiring assessments should include human review, clear scoring rules, an appeal process, and appropriate accommodations. Don't submit projects you aren't authorized to process, and review your model provider's data-handling terms before analyzing sensitive code.

---

<sub>Running locally is possible (`pip install -r requirements.txt` then `python run.py`), but RepoProof is primarily meant to be viewed live at **[repoproof.chingyu.site](https://repoproof.chingyu.site/)**.</sub>
