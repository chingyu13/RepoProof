"""MAQ constraint validation (design doc §3.1 and §11, schema-level checks)."""
import re
import string
from difflib import SequenceMatcher

MIN_CHOICES, MAX_CHOICES = 2, 7
OPTION_KEYS = string.ascii_uppercase
_VAGUE_OPTION_RE = re.compile(
    r"\b(?:core|main)\s+function(?:ality)?\b|\bappropriate ownership\b",
    re.I,
)
_SUBJECTIVE_STEM_RE = re.compile(
    r"\b(?:why|best|better|preferable|preferred|ideal|recommended)\b|"
    r"\bmost\s+(?:appropriate|suitable|likely)\b|"
    r"\b(?:main|primary)\s+reason\b",
    re.I,
)
_UNPROVEN_FALSE_REASON_RE = re.compile(
    r"\bnot\s+(?:explicitly\s+)?(?:stated|mentioned|shown|provided|supported)\b|"
    r"\bno\s+mention\b|\bnot\s+necessarily\b|"
    r"\boutside\s+(?:the\s+)?(?:evidence|provided\s+context)\b",
    re.I,
)
_CODE_BLOCK_RE = re.compile(r"```(?:[a-zA-Z0-9_+.#-]+)?\s*\n.*?```", re.S)
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _stem_code_errors(stem: str, options: list[str]) -> list[str]:
    lowered = stem.lower()
    if "the relevant code states" in lowered:
        return ["Code-based stems must use a complete fenced code block, not an isolated quoted line."]

    blocks = re.findall(r"```(?:[a-zA-Z0-9_+-]+)?\s*\n(.*?)```", stem, re.S)
    blocks += re.findall(r"<code>(.*?)</code>", stem, re.S | re.I)
    if not blocks:
        return []

    code = "\n".join(blocks).lower()
    option_text = " ".join(options).lower()
    errors = []
    if re.search(r"\breturns?\b", option_text) and not re.search(r"\breturn\b", code):
        errors.append("A code-based option mentions a return value that is not shown in the stem.")
    if re.search(r"\breturn(?:s)?\s+`?(?:none|null)`?", option_text) and not re.search(
        r"\breturn\s+(?:none|null)\b", code
    ):
        errors.append("A code-based option mentions `return None` without showing it in the stem.")
    return errors


def validate_maq(q: dict, choice_count: int, correct_count: int | None = None,
                 *, semantic_checks: bool = True) -> list[str]:
    """Return a list of problems; empty list means valid."""
    errors: list[str] = []

    stem = (q.get("stem") or "").strip()
    if len(stem) < 10:
        errors.append("Stem is missing or too short.")
    if re.search(r"\b(?:notebook\s+)?cell\s+#?\d+\b|\bchunk\s+[a-z]?\d+\b", stem, re.I):
        errors.append("The stem must not expose notebook cell or evidence chunk identifiers.")
    if re.search(r"\baccording to (?:the )?evidence\b", stem, re.I):
        errors.append("The stem must not refer to evidence that the taker cannot see.")

    options = q.get("options") or []
    if not (MIN_CHOICES <= len(options) <= MAX_CHOICES):
        errors.append(f"Question must have {MIN_CHOICES}-{MAX_CHOICES} options, got {len(options)}.")
    if choice_count and len(options) != choice_count:
        errors.append(f"Expected {choice_count} options, got {len(options)}.")

    expected_keys = list(OPTION_KEYS[: len(options)])
    keys = [o.get("key") for o in options]
    if keys != expected_keys:
        errors.append(f"Option keys must be {expected_keys}, got {keys}.")

    texts = [(o.get("text") or "").strip() for o in options]
    if any(not t for t in texts):
        errors.append("Every option needs text.")
    if len({t.lower() for t in texts}) != len(texts):
        errors.append("Options must be distinct.")
    if semantic_checks:
        if _SUBJECTIVE_STEM_RE.search(stem):
            errors.append(
                "The stem must ask for a factually correct statement, not a best/preferred choice or design rationale."
            )
        if any(_VAGUE_OPTION_RE.search(text) for text in texts):
            errors.append("Options must state a concrete, evidence-supported operation rather than a vague responsibility.")
        errors.extend(_stem_code_errors(stem, texts))

    answer = q.get("answer") or []
    if not answer:
        errors.append("Answer key is empty.")
    if not set(answer) <= set(expected_keys):
        errors.append("Answer key references unknown option keys.")
    if len(set(answer)) != len(answer):
        errors.append("Answer key has duplicates.")
    # cap: correct count must be 1 .. n-1 ("all correct" is disallowed by design)
    if options and not (1 <= len(answer) <= len(options) - 1):
        errors.append("Correct-answer count must be between 1 and (options - 1).")
    if correct_count is not None and len(answer) != correct_count:
        errors.append(f"Expected exactly {correct_count} correct options, got {len(answer)}.")
    if semantic_checks and isinstance(q.get("justifications"), dict):
        for option in options:
            key = option.get("key")
            reason = str(q["justifications"].get(key, "")).strip()
            if key not in answer and _UNPROVEN_FALSE_REASON_RE.search(reason):
                errors.append(
                    f"Option {key} is treated as false only because it is unstated; "
                    "an incorrect option must contradict the evidence."
                )

    difficulty = q.get("difficulty")
    if not isinstance(difficulty, int) or not (1 <= difficulty <= 5):
        errors.append("Difficulty must be an integer 1-5.")

    if not q.get("evidence"):
        errors.append("Question has no linked evidence (insufficient evidence -> reject).")

    return errors


def question_similarity(left: dict, right: dict) -> float:
    def normalized_stem(question: dict) -> str:
        stem = _CODE_BLOCK_RE.sub(" code ", str(question.get("stem") or "").lower())
        return " ".join(_WORD_RE.findall(stem))

    def tokens(value: str) -> set[str]:
        return set(_WORD_RE.findall(value.lower()))

    left_stem = normalized_stem(left)
    right_stem = normalized_stem(right)
    sequence = SequenceMatcher(None, left_stem, right_stem).ratio()
    left_tokens, right_tokens = tokens(left_stem), tokens(right_stem)
    union = left_tokens | right_tokens
    stem_jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0

    left_options = tokens(" ".join(option.get("text", "") for option in left.get("options", [])))
    right_options = tokens(" ".join(option.get("text", "") for option in right.get("options", [])))
    option_union = left_options | right_options
    option_jaccard = (
        len(left_options & right_options) / len(option_union) if option_union else 0.0
    )
    score = 0.65 * sequence + 0.2 * stem_jaccard + 0.15 * option_jaccard

    left_evidence = {item.get("chunk_id") for item in left.get("evidence", [])}
    right_evidence = {item.get("chunk_id") for item in right.get("evidence", [])}
    if left_evidence and right_evidence and left_evidence.isdisjoint(right_evidence):
        score *= 0.85
    return score


def find_similar_question(question: dict, previous: list[dict],
                          threshold: float = 0.76) -> tuple[int, float] | None:
    matches = [
        (index, question_similarity(question, existing))
        for index, existing in enumerate(previous)
    ]
    if not matches:
        return None
    index, score = max(matches, key=lambda item: item[1])
    return (index, score) if score >= threshold else None


def normalize_answer(selected: list[str]) -> list[str]:
    return sorted(set(k.strip().upper() for k in selected if k.strip()))
