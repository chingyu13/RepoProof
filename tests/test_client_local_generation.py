import json

from app.generator import (
    apply_local_generation_outputs,
    local_generation_batch,
    prepare_local_generation,
)
from tests.test_local_generation import CHUNKS


CFG = {
    "num_questions": 1,
    "choice_count": 4,
    "correct_mode": "exact",
    "correct_exact": 1,
    "difficulty": 3,
    "difficulty_min": 2,
    "difficulty_max": 4,
    "focus_areas": [{"id": "api", "name": "Integration / API", "weight": 5}],
    "seed": 42,
}


def _valid_response() -> str:
    return json.dumps({
        "correct_options": [{
            "text": "The operation uses the evidenced project integration.",
            "justification": "The supplied evidence shows that integration.",
        }],
        "incorrect_options": [
            {
                "text": f"The operation performs unrelated behavior {index}.",
                "justification": "That behavior conflicts with the supplied evidence.",
            }
            for index in range(3)
        ],
        "explanation": "The correct option follows from the supplied project evidence.",
        "confidence": 8,
    })


def test_client_local_batch_contains_fixed_prompts():
    state = prepare_local_generation(CHUNKS, CFG)
    batch = local_generation_batch(state, "batch-token")

    assert batch["model"]
    assert batch["system"]
    assert len(batch["tasks"]) == 1
    assert "FIXED STEM" in batch["tasks"][0]["prompt"]
    assert "EVIDENCE" in batch["tasks"][0]["prompt"]


def test_client_local_output_is_validated_and_normalized():
    state = prepare_local_generation(CHUNKS, CFG)
    batch = local_generation_batch(state, "batch-token")
    task = batch["tasks"][0]

    questions, done = apply_local_generation_outputs(CHUNKS, state, [{
        "task_index": task["task_index"],
        "attempt": task["attempt"],
        "content": _valid_response(),
        "duration_seconds": 1.25,
    }])

    assert done is True
    assert len(questions) == 1
    assert questions[0]["generator"].startswith("local:")
    assert len(questions[0]["options"]) == 4
    assert len(questions[0]["answer"]) == 1
    assert state["metrics"]["accepted_first_pass"] == 1


def test_invalid_output_advances_to_repair_prompt():
    state = prepare_local_generation(CHUNKS, CFG)
    first = local_generation_batch(state, "batch-one")["tasks"][0]
    questions, done = apply_local_generation_outputs(CHUNKS, state, [{
        "task_index": first["task_index"],
        "attempt": first["attempt"],
        "content": "{}",
    }])

    assert questions == []
    assert done is False
    repair = local_generation_batch(state, "batch-two")["tasks"][0]
    assert repair["attempt"] == 1
    assert "Repair the options" in repair["prompt"]
