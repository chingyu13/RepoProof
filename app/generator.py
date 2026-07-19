"""MAQ generation from evidence chunks.

Uses the question-blueprint slots from the design doc (§7). Falls back to a
deterministic MOCK generator when no OpenAI key is configured, so the whole
app is testable end to end without spending tokens.
"""
import json
import random
import re

from . import config
from .knowledge import ChunkIndex, data_engineering_expansion
from .strategies import STRATEGY_BY_ID, default_template
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

THE TAKER SEES ONLY THE STEM AND OPTIONS — never the evidence. Evidence titles, chunk ids, and \
notebook cell numbers (e.g. "cell 40") are meaningless to them. File paths are fine; cell/chunk \
numbers are not. NOT EVERY QUESTION NEEDS CODE: conceptual questions (why/design/comparison) \
should refer to functions, modules, and files BY NAME. When the question hinges on specific code, \
keep the quote as short as the question allows — the taker's exam time is limited. A small \
function (<= ~7 lines) may be shown whole; for longer code keep only the lines that matter and \
replace irrelevant ones with a line containing just "..." like:
    def process(items):
        ...
        total += item.value
        return total
Never make the taker read code the question does not need.

Return STRICT JSON with exactly these fields:
{
  "stem": "self-contained question text (include the quoted code it refers to)",
  "options": [{"key": "A", "text": "...", "correct": true, "justification": "ONE short sentence (<15 words)"}],
  "difficulty": 1,
  "focus_areas": ["..."],
  "evidence_ids": ["c1", "c2"],
  "explanation": "1-2 sentences shown to the taker after submission"
}"""

LOCAL_EVIDENCE_COUNT = 4
LOCAL_EVIDENCE_CHARS = 1_000


def _question_prompt(slot: dict, evidence: list[dict], choice_count: int,
                     correct_count: int, difficulty: int, extra_focus: str,
                     evidence_chars: int = 1_400) -> str:
    ev_text = "\n\n".join(f"[{c['id']}] {c['title']}\n{c['text'][:evidence_chars]}" for c in evidence)
    focus_line = f"\nAssessment creator focus/instructions: {extra_focus}" if extra_focus else ""
    # Assessment strategies carry a fixed distractor-generation method — how
    # wrong options must be constructed for this way of probing understanding.
    if slot.get("distractors"):
        focus_line += f"\nDistractor construction rule: {slot['distractors']}"
    # Small-model scaffolding: a fixed stem skeleton plus an explicit
    # code-quoting policy keeps local 7B models from pasting code into every
    # question (see strategies.STEM_PATTERNS / CODE_QUOTE).
    if slot.get("pattern"):
        focus_line += ("\nStem pattern to follow — fill in the <placeholders> from the evidence: "
                       f"{slot['pattern']}")
    policy = slot.get("code_quote")
    if policy == "snippet":
        focus_line += ("\nCode in stem: quote the code the question hinges on — ideally 3-7 "
                       "lines (hard max 12 shown). A small function may be shown whole; elide "
                       "irrelevant lines with `...` so the taker reads only what matters.")
    elif policy == "minimal":
        focus_line += ("\nCode in stem: at most 1-3 lines (e.g. a signature) and only if needed; "
                       "prefer referring to functions/files by name.")
    elif policy == "none":
        focus_line += ("\nCode in stem: NONE — this is a conceptual question; refer to functions, "
                       "modules, and files by name only.")
    return f"""Question slot: {slot['slot']} — {slot['brief']}
Target difficulty: {difficulty} (1=recall ... 5=evaluate)
Options: exactly {choice_count}, keyed {list(OPTION_KEYS[:choice_count])}.
Correct options: exactly {correct_count} (the rest must be incorrect).{focus_line}

OUTPUT CHECKLIST — apply this immediately before responding:
1. Return exactly {choice_count} distinct options.
2. Count the boolean values in `correct`: exactly {correct_count} options must be `true`.
3. Every `true` option must be supported by the evidence; every `false` option must contradict it.
4. Cite only the evidence ids shown below. Return JSON only, without Markdown.
5. The stem is SELF-CONTAINED: quote the code lines it asks about inside the stem; never mention
   cell numbers, chunk ids, evidence titles, or phrases like "according to the evidence".

EVIDENCE (cite ids you used in evidence_ids):
{ev_text}

Write the MAQ now as strict JSON."""


def _repair_prompt(raw: dict, evidence: list[dict], choice_count: int,
                   correct_count: int, errors: str) -> str:
    """Ask the model to repair an invalid draft without repeating full retrieval.

    The normal question prompt can be several thousand tokens. For common
    local-model failures such as a wrong number of correct options, send the
    candidate plus only the evidence it cited. This is quicker and gives the
    model a focused correction task instead of discarding the whole question.
    """
    cited = set(raw.get("evidence_ids") or [])
    repair_evidence = [c for c in evidence if c["id"] in cited] or evidence[:2]
    ev_text = "\n\n".join(f"[{c['id']}] {c['title']}\n{c['text'][:900]}" for c in repair_evidence)
    draft = json.dumps(raw, ensure_ascii=False)
    return f"""Repair this RepoProof MAQ draft. The validator reported:
{errors}

Use only the evidence below. Preserve the question's intent, but rewrite
options, `correct` flags, justifications, or evidence_ids when necessary.
Return the complete JSON object and nothing else.

Hard requirements:
- exactly {choice_count} distinct options with keys {list(OPTION_KEYS[:choice_count])};
- exactly {correct_count} options have `correct: true` — count them before responding;
- true options must be supported and false options contradicted by the evidence;
- include at least one valid evidence id.

INVALID DRAFT:
{draft}

EVIDENCE:
{ev_text}"""


def _extract_json(text: str) -> dict:
    """Local models often wrap the JSON in prose or ```json fences —
    grab the outermost {...} block instead of trusting the raw output."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("model returned no JSON object")
    return json.loads(m.group(0))


def _call_llm(provider: str, system: str, user: str, *, temperature: float | None = None) -> dict:
    """One code path for both providers: the local server (Ollama/LM Studio)
    speaks the same OpenAI chat-completions protocol, so only base_url,
    model name, and timeout differ. Data never leaves the machine when
    provider == 'local'."""
    from openai import OpenAI
    if provider == "local":
        # trust_env=False bypasses HTTP(S)_PROXY/ALL_PROXY env vars — localhost
        # traffic must never be routed through a corporate/system proxy.
        import httpx
        client = OpenAI(base_url=config.LOCAL_LLM_URL, api_key="local-llm",
                        http_client=httpx.Client(trust_env=False, timeout=300))
        model, timeout = config.LOCAL_LLM_MODEL, 300   # local inference can be slow
    else:
        client = OpenAI(api_key=config.openai_api_key())
        model, timeout = config.OPENAI_MODEL, 90
    kwargs = dict(
        model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        # A smaller local model is much more consistent about JSON/schema
        # constraints at low temperature. OpenAI keeps the previous setting.
        temperature=temperature if temperature is not None else (0.2 if provider == "local" else 0.4),
        timeout=timeout,
    )
    if provider == "local":
        # Enough for one MAQ, but prevents a malformed local generation from
        # wasting time on a long answer that the validator will reject anyway.
        kwargs["max_tokens"] = 1_200
    try:
        resp = client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
    except Exception as exc:
        # some local servers (older Ollama, llama.cpp) reject response_format —
        # retry once without it and rely on _extract_json instead
        if provider == "local" and "response_format" in str(exc).lower():
            resp = client.chat.completions.create(**kwargs)
        else:
            raise
    return _extract_json(resp.choices[0].message.content)


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
    # hard_max = n-1 enforces the design rule "all options correct" is never
    # allowed — otherwise a disclosed correct-count would trivialize the
    # question (select everything).
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

    # Provider choice: per-request (UI dropdown) > server default. Falls back
    # to mock with a visible warning instead of failing silently.
    provider = (cfg.get("provider") or "").strip().lower() or config.default_provider()
    fallback_warnings = []
    if provider == "openai" and not config.openai_api_key():
        fallback_warnings.append("OpenAI selected but no API key configured — using mock questions.")
        provider = "mock"
    elif provider == "local" and not config.local_llm_available():
        fallback_warnings.append(
            f"Local LLM selected but no server answered at {config.LOCAL_LLM_URL} — using mock questions. "
            "Start it with e.g. `ollama serve` (and `ollama pull " + config.LOCAL_LLM_MODEL + "`).")
        provider = "mock"
    elif provider not in ("openai", "local", "mock"):
        provider = config.default_provider()
    mock = provider == "mock"
    generator_label = {"mock": "mock", "openai": config.OPENAI_MODEL,
                       "local": f"local:{config.LOCAL_LLM_MODEL}"}[provider]
    evidence_k = LOCAL_EVIDENCE_COUNT if provider == "local" else 6
    evidence_chars = LOCAL_EVIDENCE_CHARS if provider == "local" else 1_400

    # Assessment strategies (preferred config): HOW understanding is verified.
    # Each entry {id, weight 1-5, template} maps to a catalog strategy with a
    # fixed prompt directive + fixed distractor rule; questions distribute
    # across strategies proportionally to weight (same integer algorithm as
    # the legacy focus areas below). focus_areas is tagged with the strategy
    # name so per-focus scoring becomes the Student Understanding Profile.
    strategies_cfg = []
    for s in cfg.get("strategies", []):
        strat = STRATEGY_BY_ID.get(str(s.get("id", "")).strip())
        w = int(s.get("weight", 0))
        if strat and w > 0:
            tmpl = next((t for t in strat["templates"] if t["id"] == s.get("template")),
                        default_template(strat))
            strategies_cfg.append((strat, tmpl, w))
    strategy_seq: list[tuple] = []
    if strategies_cfg:
        weighted = [(strat, tmpl) for strat, tmpl, w in strategies_cfg for _ in range(w)]
        strategy_seq = [weighted[(i * len(weighted)) // num % len(weighted)] for i in range(num)]

    # Legacy focus-area radar weights (kept for API compatibility; the UI now
    # sends `strategies` instead): distribute questions across topic areas.
    areas_cfg = [(str(a.get("name", "")).strip(), int(a.get("weight", 0)))
                 for a in cfg.get("areas", [])
                 if str(a.get("name", "")).strip() and int(a.get("weight", 0)) > 0]
    area_seq: list[str] = []
    if not strategies_cfg and areas_cfg:
        # Proportional assignment without floating point. Example: areas
        # {Data:4, Logic:2}, num=6 → weighted = [D,D,D,D,L,L] (each name
        # repeated `weight` times). Question i maps to index
        # (i*len(weighted))//num, which walks that list evenly from start to
        # end — so 6 questions land on D,D,D,D,L,L: exactly a 4:2 split.
        # The final % handles num > len(weighted) by wrapping around.
        weighted = [name for name, w in areas_cfg for _ in range(w)]
        area_seq = [weighted[(i * len(weighted)) // num % len(weighted)] for i in range(num)]

    # ---- Pre-compute every per-question input in the MAIN thread (slot,
    # retrieval, correct count, per-task RNG) so the LLM calls themselves can
    # run in parallel. random.Random isn't safe to share across threads, so
    # each task gets its own deterministically-seeded instance.
    seed = int(cfg.get("seed", 42))
    tasks = []
    for i in range(num):
        if strategy_seq:
            strat, tmpl = strategy_seq[i]
            # slot carries the strategy's fixed prompt + distractor method;
            # `focus` tags focus_areas -> per-strategy Understanding Profile.
            slot = {
                "slot": f"{strat['id']}:{tmpl['id']}",
                "focus": strat["name"],
                "query": strat["query"] + " " + tmpl["name"].lower(),
                "brief": f"{tmpl['directive']} Strategy goal: {strat['goal']}",
                "distractors": strat["distractors"],
                "pattern": tmpl.get("pattern", ""),
                "code_quote": strat.get("code_quote", ""),
            }
        else:
            slot = dict(DEFAULT_BLUEPRINT[i % len(DEFAULT_BLUEPRINT)])
        focus_for_prompt = extra_focus
        query = slot["query"] + (" " + extra_focus if extra_focus else "")
        # Only expand the creator's requested topic, not generic blueprint
        # words such as "load" or "pipeline". This keeps general-purpose
        # questions stable while giving data-engineering assignments a small,
        # explicit semantic bridge to code identifiers.
        retrieval_focus = extra_focus
        if area_seq:
            area = area_seq[i]
            slot["focus"] = area
            query += " " + area
            retrieval_focus = (retrieval_focus + " " + area).strip()
            focus_for_prompt = ((extra_focus + "; ") if extra_focus else "") + \
                f"primary focus area: {area} — the question must test this area and focus_areas must include it"
        evidence = index.retrieve(query, k=evidence_k,
                                  expansion_terms=data_engineering_expansion(retrieval_focus))
        # rotate anchor evidence so consecutive comprehension slots hit different functions
        if i > 0 and len(evidence) > 2:
            evidence = evidence[i % 3:] + evidence[: i % 3]
        correct_count = _pick_correct_count(cfg, choice_count, rng)
        tasks.append({"i": i, "slot": slot, "evidence": evidence,
                      "focus_for_prompt": focus_for_prompt,
                      "correct_count": correct_count,
                      "rng": random.Random(seed * 1000 + i)})

    tag_strategy = bool(strategy_seq)

    def _run(task):
        """Generate -> validate -> focused repair -> fresh regeneration for ONE
        question. Returns (index, question | None, last_error). The repair pass
        is especially important for local 7B models: a question may be
        evidence-grounded yet have one instead of two `correct` flags —
        repairing that compact draft beats resending the full prompt."""
        slot, evidence = task["slot"], task["evidence"]
        correct_count, trng = task["correct_count"], task["rng"]

        def _accept(cand):
            cand["generator"] = generator_label
            if tag_strategy:
                # deterministic profile bucket — don't let the model's own
                # labels leak into the per-strategy Understanding Profile
                cand["focus_areas"] = [slot["focus"]]
            return task["i"], cand, None

        last_err = None
        for fresh_attempt in range(2):
            try:
                if mock:
                    raw = _mock_question(slot, evidence, choice_count, correct_count, difficulty, trng)
                else:
                    prompt = _question_prompt(
                        slot, evidence, choice_count, correct_count, difficulty,
                        task["focus_for_prompt"], evidence_chars,
                    )
                    if fresh_attempt and last_err:
                        prompt += (
                            "\n\nThe previous candidate could not be repaired. Generate a new question "
                            f"with a different wording and obey the output checklist. Previous errors: {last_err}"
                        )
                    raw = _call_llm(provider, SYSTEM_PROMPT, prompt)
                q = _normalize(raw, slot, chunk_by_id, trng)
                errs = validate_maq(q, choice_count, correct_count)
                if not errs:
                    return _accept(q)
                last_err = "; ".join(errs)
                if mock:
                    continue

                # Send a small correction request before consuming another
                # full generation attempt. `raw` is retained so the model can
                # fix its own JSON rather than starting from nothing.
                repair_raw = _call_llm(
                    provider,
                    SYSTEM_PROMPT,
                    _repair_prompt(raw, evidence, choice_count, correct_count, last_err),
                    temperature=0.0,
                )
                repaired = _normalize(repair_raw, slot, chunk_by_id, trng)
                repair_errs = validate_maq(repaired, choice_count, correct_count)
                if not repair_errs:
                    return _accept(repaired)
                last_err = "; ".join(repair_errs)
            except GenerationError as exc:
                last_err = str(exc)
            except Exception as exc:  # API/JSON errors -> retry once, then warn
                last_err = f"{type(exc).__name__}: {exc}"
        return task["i"], None, last_err

    questions, warnings = [], list(fallback_warnings)
    # OpenAI calls are network-bound, so a small thread pool cuts a typical
    # batch from ~30s to <10s. Ollama/LM Studio serialize requests internally
    # (parallel submits would just queue) and mock is instant — both stay
    # sequential.
    if provider == "openai" and num > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(4, num)) as pool:
            results = list(pool.map(_run, tasks))
    else:
        results = [_run(t) for t in tasks]

    for i, q, err in results:      # pool.map preserves task order
        if q is not None:
            questions.append(q)
        else:
            warnings.append(
                f"Question {i + 1} ({tasks[i]['slot']['slot']}) rejected after repair and fresh regeneration: {err}"
            )

    return questions, warnings


def _normalize(raw: dict, slot: dict, chunk_by_id: dict, rng: random.Random | None = None) -> dict:
    opts_raw = list(raw.get("options", [])[:7])
    # LLMs put correct options first (position bias) — shuffle so the answer
    # key is uniformly distributed across A..G.
    if rng is not None:
        rng.shuffle(opts_raw)
    options = []
    answer = []
    for j, opt in enumerate(opts_raw):
        key = OPTION_KEYS[j]
        options.append({"key": key, "text": str(opt.get("text", "")).strip()})
        if opt.get("correct"):
            answer.append(key)
    justifications = {
        OPTION_KEYS[j]: str(opt.get("justification", "")).strip()
        for j, opt in enumerate(opts_raw)
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