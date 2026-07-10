# RepoProof

**Turn a code project into an evidence-grounded understanding assessment.**

RepoProof analyzes a project and generates multi-answer questions (MAQs) about its real implementation. Assessment creators can configure the question framework, inspect the supporting evidence, edit and approve questions, publish an assessment, and review exact-match results.

The goal is to test whether someone understands a project—not simply whether they can produce one with code generation tools.

> [!WARNING]
> RepoProof is an early, local prototype. It has no authentication or tenant isolation and is not ready for production, unsupervised grading, or automated hiring decisions.

## Use cases

- **Computer science education:** assess whether students understand their submitted assignments.
- **Engineering hiring:** create a project-specific screening assessment before an open interview.
- **Self-assessment:** test your own understanding of a codebase, notebook, model, or data project.

RepoProof measures demonstrated project understanding. It does not prove authorship or conclusively detect AI-generated work.

## What works today

- Public GitHub repository import
- Drag-and-drop `.zip` upload
- Browser folder selection and client-side packaging
- Deep Python AST analysis
- File- and cell-level analysis for many other languages and Jupyter notebooks
- Evidence chunks with file, line, cell, and snapshot provenance
- BM25 evidence retrieval
- OpenAI-powered MAQ generation
- Deterministic mock mode without an API key
- Configurable MAQ structure and difficulty
- Focus-area weighting through an interactive radar chart
- Human editing, approval, and rejection
- Shareable assessment links
- Printable assessments and answer keys
- Exact-match scoring with per-focus-area results
- Light and dark themes

## Workflow

The creator interface uses a four-step workflow:

1. **Link the Project**
   - Paste a public GitHub URL, upload a `.zip`, or select a folder.
   - Accept the project-processing notice and analyze an immutable snapshot.
2. **Question Framework**
   - Choose the number of questions, 2–7 options, exact or dynamic correct-answer count, and difficulty from 1–5.
   - Adjust focus-area weights on the radar chart and add optional instructions.
3. **Review and Approve**
   - Inspect project evidence and edit question stems, options, answer keys, difficulty, and explanations.
   - Approve valid questions or reject unsuitable ones.
4. **Publish Assessment**
   - Publish selected approved questions and receive shareable, printable, and answer-key links.
   - Review stored attempts and scores.

The progress bar remains visible and allows navigation between unlocked steps.

## Multi-answer question rules

Each MAQ has:

- 2–7 distinct options
- At least one correct option, but not every option correct
- One unambiguous correct combination
- Difficulty from 1–5
- Linked project evidence
- An explanation for post-submission review

Scoring currently uses exact set matching. A response is correct only when its selected options exactly match the answer key. Partial credit is not yet implemented.

## Supported projects

Python receives the deepest analysis, including:

- Functions and classes
- Imports and dependencies
- Approximate call edges
- Docstrings and source snippets

RepoProof also provides lightweight file-level analysis for:

- Jupyter notebooks, including per-cell source extraction
- R and R Markdown
- Java, Kotlin, Scala, and Swift
- JavaScript, TypeScript, JSX, TSX, and Vue
- HTML, CSS, and SCSS
- SQL
- C, C++, C#, Go, and Rust
- Ruby, PHP, Perl, Lua, Julia, and Dart
- Shell, PowerShell, and MATLAB
- JSON, YAML, and TOML

Question quality depends on analysis depth. Non-Python languages currently use lightweight declaration extraction rather than a complete language-specific AST.

## Quick start

### Requirements

- Python 3.10 or newer
- `pip`
- Git, when importing a GitHub repository

### Installation

```bash
git clone https://github.com/your-account/RepoProof.git
cd RepoProof

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
python run.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

FastAPI's interactive API documentation is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

### Windows activation

```powershell
.venv\Scripts\Activate.ps1
```

## Configuration

Copy `.env.example` to `.env`. Supported settings include:

- `OPENAI_API_KEY` — optional OpenAI API key; leave empty to use mock mode
- `OPENAI_MODEL` — generation model; defaults to `gpt-4o-mini`
- `REPOPROOF_MAX_MB` — maximum total project size in MB; defaults to `1024`
- `REPOPROOF_MAX_FILE_MB` — per-file analysis limit; defaults to `1`
- `REPOPROOF_MAX_NOTEBOOK_MB` — notebook analysis limit; defaults to `25`
- `REPOPROOF_PORT` — local server port; defaults to `8000`

Additional runtime overrides:

- `REPOPROOF_WORK_DIR` — runtime data directory; defaults to `./data`
- `REPOPROOF_DB` — SQLite database path
- `MOCK_LLM=1` — force mock mode even when an API key is configured

Never commit `.env` or API keys.

## Mock mode

An OpenAI key is not required to try the complete workflow. Without `OPENAI_API_KEY`, RepoProof generates deterministic sample questions from real project evidence and labels them `[MOCK]`.

Mock questions are intended to exercise the product flow; they are not a substitute for real model-generated assessment content.

## How it works

```text
Project URL / Upload
        ↓
Snapshot and Intake Validation
        ↓
Code, Notebook, and File Analysis
        ↓
Evidence Chunk Construction
        ↓
BM25 Retrieval by Question Focus
        ↓
OpenAI or Mock Question Generation
        ↓
Constraint Validation and Human Review
        ↓
Publish → Take → Score
```

All assessments remain associated with the analyzed snapshot: a Git commit prefix for imported repositories or an archive checksum for uploads.

## Project structure

```text
.
├── app/
│   ├── analyzer.py      # Python AST and generic file analysis
│   ├── config.py        # Environment configuration and limits
│   ├── db.py            # SQLite storage
│   ├── generator.py     # OpenAI and mock MAQ generation
│   ├── ingest.py        # GitHub clone and archive extraction
│   ├── knowledge.py     # Evidence chunks and BM25 retrieval
│   ├── main.py          # FastAPI routes and page delivery
│   ├── scoring.py       # Exact-match and focus-area scoring
│   ├── validator.py     # MAQ schema and evidence validation
│   └── static/
│       ├── assess.html  # Assessment-taker interface
│       └── index.html   # Assessment-creator interface
├── .env.example
├── requirements.txt
└── run.py
```

Runtime files are written to the gitignored `data/` directory:

- `data/repoproof.db` stores projects, questions, assessments, and attempts.
- `data/projects/` stores extracted project snapshots.

## Current limitations

- Local, single-user prototype with no authentication or authorization
- Public GitHub repositories only
- No private-repository OAuth or GitHub App integration
- Python-first deep analysis; other languages use lightweight parsing
- BM25 retrieval only; no embeddings or hybrid search
- SQLite storage instead of PostgreSQL
- Exact-match scoring only
- No open-question or conversational interview mode
- No automated deletion lifecycle
- No automated test suite, Docker image, or production deployment configuration

To delete local project data, stop the app and remove the relevant files from `data/projects/` and records from the local database. Automated lifecycle deletion is planned but not yet implemented.

## Roadmap

- Open questions and conversational follow-ups
- Partial-credit scoring
- Tree-sitter language parsers
- Semantic and hybrid retrieval
- Private GitHub repository support
- Authentication, organizations, and tenant isolation
- Automated retention and deletion policies
- PostgreSQL and pgvector
- Webhook-driven snapshot updates
- Production packaging and deployment

## Responsible use

Repository familiarity is evidence of understanding, not definitive evidence of authorship. Education and hiring assessments should include human review, clear scoring rules, an appeal process, and appropriate accommodations.

Do not submit projects you are not authorized to process. Review your model provider's data-handling terms before analyzing private or sensitive code.
