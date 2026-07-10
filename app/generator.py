"""MAQ generation from evidence chunks.

Uses the question-blueprint slots from the design doc (§7). Falls back to a
deterministic MOCK generator when no OpenAI key is configured, so the whole
app is testable end to end without spending tokens.
"""
import json
import random

from . import config
from .knowledge import ChunkIndex
from .validator import OPTION_KEYS, validate_maq

# Default blueprint (design doc §7): slots instantiated against each repo.
DEFAULT_BLUEPRINT = [
    {"slot": "comprehension", "focus": "Project logic",
     "query": "core main function implementation logic",
     "brief": "Pick one concrete function from the evidence and ask what it does / how it behaves."},
    {"slot": "comprehension", "focus": "Project logic",
     "query": "class method process handle compute parse",
     "brief": "Pick a different function or class and ask about its behavior or purpose."},
    {"slot": "flow", "focus": "Architecture",
     "query": "entry point main call flow pipeline run",
     "brief": "Ask about execution or data flow: what calls what, in which order."},
    {"slot": "structure", "focus": "Architecture",
     "query": "module package file structure imports",
     "brief": "Ask about module/folder responsibilities and how modules depend on each other."},
    {"slot": "storage", "focus": "Data modelling",
     "query": "database file save load persist config json read write",
     "brief": "Ask how data is stored, loaded, or exchanged (files, DB, network, config)."},
    {"slot": "dependencies", "focus": "Programming-language knowledge",
     "query": "dependencies libraries imports frameworks",
     "brief": "Ask which libraries the project actually uses and what for."},
]

SYSTEM_PROMPT = """You are RepoProof, an assessment generator. You write ONE multi-answer question (MAQ) \
about a specific software project, grounded ONLY in the evidence provided. Never invent facts that are \
not in the evidence. Incorrect options must be plausible but verifiably wrong given the evidence.

Return STRICT JSON with exactly these fields:
{
  "stem": "question text",
  "options": [{"key": "A", "text": "...", "correct": true, "justification": "why correct/incorrect, citing evidence"}],
  "difficulty": 1,
  "focus_areas": ["..."],
  "evidence_ids": ["c1", "c2"],
  "explanation": "shown to the taker after submission"
}"""


def _question_prompt(slot: dict, evidence: list[dict], choice_count: int,
                     correct_count: int, difficulty: int, extra_focus: str) -> str:
    ev_text = "\n\n".join(f"[{c['id']}] {c['title']}\n{c['text'][:1400]}" for c in evidence)
    focus_line = f"\nAssessment creator focus/instructions: {extra_focus}" if extra_focus else ""
    return f"""Question slot: {slot['slot']} — {slot['brief']}
Target difficulty: {difficulty} (1=recall ... 5=evaluate)
Options: exactly {choice_count}, keyed {list(OPTION_KEYS[:choice_count])}.
Correct options: exactly {correct_count} (the rest must be incorrect).{focus_line}

EVIDENCE (cite ids you used in evidence_ids):
{ev_text}

Write the MAQ now as strict JSON."""


def _call_openai(system: str, user: str) -> dict:
    from openai import OpenAI
    client = OpenAI(api_key=config.openai_api_key())
    resp = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        temperature=0.4,
    )
    return json.loads(resp.choices[0].message.content)


def _mock_question(slot: dict, evidence: list[dict], choice_count: int,
                   correct_count: int, difficulty: int, rng: random.Random) -> dict:
    """Deterministic evidence-grounded question used when no API key is set."""
    fn = next((c for c in evidence if c["kind"] == "function"), None)
    anchor = fn or (evidence[0] if evidence else None)
    if anchor is None:
        raise GenerationError("No evidence available for mock generation.")

    facts, lies = [], []
    if fn:
        name = fn["title"].split()[1]
        facts.append(f"`{name}` is defined in `{fn['file']}`.")
        facts.append(f"`{name}` spans lines {fn['start_line']}-{fn['end_line']} of `{fn['file']}`.")
        first_line = (fn["text"].splitlines()[0] if fn["text"] else "").strip()
        if first_line:
            facts.append(f"The evidence describes it as: \"{first_line[:110]}\".")
        lies.append(f"`{name}` is defined in `tests/test_{fn['file'].replace('/', '_')}`.")
        lies.append(f"`{name}` is imported from an external library rather than defined in this project.")
        lies.append(f"`{name}` is a class, not a function.")
        stem = f"[MOCK — no API key configured] Which statements about `{name}` in this project are correct?"
    else:
        facts.append(f"The project contains evidence titled \"{anchor['title']}\".")
        facts.append("The statements below are checked against the analyzed snapshot.")
        lies.append("The project contains no Python files.")
        lies.append("The project has no analyzable evidence.")
        lies.append("This repository is written primarily in COBOL.")
        stem = f"[MOCK — no API key configured] Which statements about this project are correct? ({slot['slot']})"

    rng.shuffle(facts)
    rng.shuffle(lies)
    correct_texts = facts[:correct_count]
    wrong_texts = lies[: choice_count - correct_count]
    while len(correct_texts) < correct_count:
        correct_texts.append(f"The snapshot id recorded for this evidence is `{anchor['snapshot']}`.")
    while len(correct_texts) + len(wrong_texts) < choice_count:
        wrong_texts.append("Every module in this project is auto-generated.")

    texts = [(t, True) for t in correct_texts] + [(t, False) for t in wrong_texts]
    rng.shuffle(texts)
    options = [
        {"key": OPTION_KEYS[i], "text": t, "correct": ok,
         "justification": "Stated in the linked evidence." if ok else "Contradicts the linked evidence."}
        for i, (t, ok) in enumerate(texts)
    ]
    return {
        "stem": stem,
        "options": options,
        "difficulty": min(difficulty, 2),
        "focus_areas": [slot["focus"]],
        "evidence_ids": [anchor["id"]],
        "explanation": "Mock question generated without an LLM. Add an OPENAI_API_KEY to get real questions.",
    }


class GenerationError(Exception):
    pass


def _pick_correct_count(cfg: dict, choice_count: int, rng: random.Random) -> int:
    hard_max = choice_count - 1
    if cfg.get("correct_mode") == "dynamic":
        lo = max(1, int(cfg.get("correct_min", 1)))
        hi = min(hard_max, int(cfg.get("correct_max", hard_max)))
        if lo > hi:
            lo = hi
        return rng.randint(lo, hi)
    return max(1, min(hard_max, int(cfg.get("correct_exact", 2))))


def generate_questions(chunks: list[dict], cfg: dict) -> tuple[list[dict], list[str]]:
    """Generate cfg['num_questions'] MAQs. Returns (questions, warnings)."""
    index = ChunkIndex(chunks)
    chunk_by_id = {c["id"]: c for c in chunks}
    rng = random.Random(cfg.get("seed", 42))
    num = int(cfg.get("num_questions", 5))
    choice_count = max(2, min(7, int(cfg.get("choice_count", 5))))
    difficulty = max(1, min(5, int(cfg.get("difficulty", 2))))
    extra_focus = (cfg.get("focus") or "").strip()
    mock = config.mock_mode()

    # Focus-area radar weights: distribute questions across areas
    # proportionally to their configured degree (design doc §3.4).
    areas_cfg = [(str(a.get("name", "")).strip(), int(a.get("weight", 0)))
                 for a in cfg.get("areas", [])
                 if str(a.get("name", "")).strip() and int(a.get("weight", 0)) > 0]
    area_seq: list[str] = []
    if areas_cfg:
        weighted = [name for name, w in areas_cfg for _ in range(w)]
        area_seq = [weighted[(i * len(weighted)) // num % len(weighted)] for i in range(num)]

    questions, warnings = [], []
    for i in range(num):
        slot = dict(DEFAULT_BLUEPRINT[i % len(DEFAULT_BLUEPRINT)])
        focus_for_prompt = extra_focus
        query = slot["query"] + (" " + extra_focus if extra_focus else "")
        if area_seq:
            area = area_seq[i]
            slot["focus"] = area
            query += " " + area
            focus_for_prompt = ((extra_focus + "; ") if extra_focus else "") + \
                f"primary focus area: {area} — the question must test this area and focus_areas must include it"
        evidence = index.retrieve(query, k=6)
        # rotate anchor evidence so consecutive comprehension slots hit different functions
        if i > 0 and len(evidence) > 2:
            evidence = evidence[i % 3:] + evidence[: i % 3]
        correct_count = _pick_correct_count(cfg, choice_count, rng)

        last_err = None
        for attempt in range(2):
            try:
                if mock:
                    raw = _mock_question(slot, evidence, choice_count, correct_count, difficulty, rng)
                else:
                    prompt = _question_prompt(slot, evidence, choice_count, correct_count, difficulty, focus_for_prompt)
                    if attempt == 1 and last_err:
                        prompt += f"\n\nYour previous attempt was invalid: {last_err}. Fix these problems."
                    raw = _call_openai(SYSTEM_PROMPT, prompt)
                q = _normalize(raw, slot, chunk_by_id)
                errs = validate_maq(q, choice_count, correct_count)
                if errs:
                    last_err = "; ".join(errs)
                    continue
                q["generator"] = "mock" if mock else config.OPENAI_MODEL
                questions.append(q)
                break
            except GenerationError as exc:
                last_err = str(exc)
            except Exception as exc:  # API/JSON errors -> retry once, then warn
                last_err = f"{type(exc).__name__}: {exc}"
        else:
            warnings.append(f"Question {i + 1} ({slot['slot']}) rejected after retry: {last_err}")

    return questions, warnings


def _normalize(raw: dict, slot: dict, chunk_by_id: dict) -> dict:
    options = []
    answer = []
    for j, opt in enumerate(raw.get("options", [])[:7]):
        key = OPTION_KEYS[j]
        options.append({"key": key, "text": str(opt.get("text", "")).strip()})
        if opt.get("correct"):
            answer.append(key)
    justifications = {
        OPTION_KEYS[j]: str(opt.get("justification", "")).strip()
        for j, opt in enumerate(raw.get("options", [])[:7])
    }
    evidence = []
    for cid in raw.get("evidence_ids", []):
        c = chunk_by_id.get(cid)
        if c:
            evidence.append({
                "chunk_id": c["id"], "title": c["title"], "file": c["file"],
                "lines": f"{c['start_line']}-{c['end_line']}" if c["start_line"] else "",
                "snapshot": c["snapshot"],
            })
    diff = raw.get("difficulty", 1)
    return {
        "slot": slot["slot"],
        "stem": str(raw.get("stem", "")).strip(),
        "options": options,
        "answer": sorted(answer),
        "justifications": justifications,
        "evidence": evidence,
        "difficulty": int(diff) if isinstance(diff, (int, float, str)) and str(diff).isdigit() else 1,
        "focus_areas": [str(f) for f in raw.get("focus_areas", [slot["focus"]])][:4] or [slot["focus"]],
        "explanation": str(raw.get("explanation", "")).strip(),
    }
