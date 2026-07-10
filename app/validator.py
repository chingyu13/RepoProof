"""MAQ constraint validation (design doc §3.1 and §11, schema-level checks)."""
import string

MIN_CHOICES, MAX_CHOICES = 2, 7
OPTION_KEYS = string.ascii_uppercase


def validate_maq(q: dict, choice_count: int, correct_count: int | None = None) -> list[str]:
    """Return a list of problems; empty list means valid."""
    errors: list[str] = []

    stem = (q.get("stem") or "").strip()
    if len(stem) < 10:
        errors.append("Stem is missing or too short.")

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

    difficulty = q.get("difficulty")
    if not isinstance(difficulty, int) or not (1 <= difficulty <= 5):
        errors.append("Difficulty must be an integer 1-5.")

    if not q.get("evidence"):
        errors.append("Question has no linked evidence (insufficient evidence -> reject).")

    return errors


def normalize_answer(selected: list[str]) -> list[str]:
    return sorted(set(k.strip().upper() for k in selected if k.strip()))
