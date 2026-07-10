# RepoProof — Prototype

AI-powered assessments that test whether someone *understands* a code project — not whether they can produce one. See `PRODUCT_DESIGN.md` for the full design.

This prototype implements the MVP slice: **project → evidence-grounded multi-answer questions (MAQs) → human review → publish → take → score**.

Supported inputs: Python (deep AST analysis: functions, classes, imports, call edges) plus text-level analysis for Jupyter notebooks (per-cell), R, R Markdown, Java, JavaScript/TypeScript, HTML, CSS, SQL, C/C++, C#, Go, Rust, Ruby, PHP, Shell, Kotlin, Swift, Scala, Julia, and config formats (JSON/YAML/TOML). Question quality is best where analysis is deepest (Python); other languages get file- and cell-level evidence.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env        # add your OPENAI_API_KEY (optional, see below)
python run.py               # → http://127.0.0.1:8000
```

Without an `OPENAI_API_KEY`, the app runs in **mock mode**: the full workflow works, but questions are simple deterministic samples built from real project evidence (marked `[MOCK]`). Add a key to `.env` to get real LLM-generated questions.

## Workflow

1. **Submit a project** — paste a public GitHub URL or upload a `.zip` (≤ 1 GB), accept the consent notice.
2. **Generate** — configure question count, options per question (2–7), exact/dynamic correct-answer count, difficulty, optional focus instructions.
3. **Review** — edit stems/options/answers, see the evidence behind each question, approve or reject. Only approved questions can be published (invalid answer keys are blocked at approval).
4. **Publish** — get a shareable take-link, plus a printable version (`?key=1` adds the answer key) for offline, supervised exams.
5. **Results** — exact-match scoring with a per-focus-area breakdown; attempts are stored per assessment.

## Layout

```
app/
  config.py     env config, consent text, 1 GB limit
  db.py         SQLite storage (JSON columns; Postgres later)
  ingest.py     GitHub shallow clone / zip extract, size gate
  analyzer.py   Python `ast` analysis (functions, classes, imports, call edges)
  knowledge.py  evidence chunks with provenance + BM25 retrieval
  generator.py  blueprint-slot MAQ generation (OpenAI or mock)
  validator.py  MAQ constraints (2–7 options, correct = 1..n−1, evidence required)
  scoring.py    exact-match scoring, focus-area report
  main.py       FastAPI routes, printable export
  static/       creator UI (index.html) and taker UI (assess.html)
```

## Design-doc deviations (deliberate, prototype-only)

- `ast` instead of Tree-sitter — full fidelity for Python, zero native deps; Tree-sitter arrives with the second language.
- BM25 only, no embeddings — keeps retrieval key-free; hybrid retrieval is post-prototype.
- SQLite instead of PostgreSQL+pgvector.
- No auth/multi-tenancy — single-user prototype.

## Notes

- Data lives in `data/` (gitignored). Delete a project's folder under `data/projects/` to honor the consent promise manually; automated lifecycle deletion is still TODO.
- Everything else (open questions, interviews, partial credit, webhooks) is deferred per `PRODUCT_DESIGN.md` §14.
