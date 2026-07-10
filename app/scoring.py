"""Exact-match scoring with per-focus-area breakdown for the radar report."""
from .validator import normalize_answer


def score_attempt(questions: list[dict], responses: dict) -> dict:
    """questions: DB question dicts. responses: {str(question_id): ["A","B"]}"""
    per_question = []
    per_focus: dict[str, dict] = {}
    correct_total = 0

    for q in questions:
        qid = q["id"]
        selected = normalize_answer(responses.get(str(qid), []))
        answer = normalize_answer(q["answer"])
        is_correct = selected == answer
        correct_total += is_correct
        per_question.append({
            "question_id": qid,
            "correct": is_correct,
            "selected": selected,
            "answer": answer,
            "explanation": q.get("explanation", ""),
            "justifications": q.get("justifications", {}),
        })
        for area in q.get("focus_areas", ["General"]):
            bucket = per_focus.setdefault(area, {"correct": 0, "total": 0})
            bucket["total"] += 1
            bucket["correct"] += is_correct

    total = len(questions)
    return {
        "correct": correct_total,
        "total": total,
        "percent": round(100 * correct_total / total, 1) if total else 0.0,
        "per_question": per_question,
        "per_focus": per_focus,
    }
