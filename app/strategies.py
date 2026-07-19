"""Assessment-strategy catalog.

A strategy configures HOW the AI verifies understanding of the submitted
code — not WHAT topics it asks about (topics will eventually be extracted
automatically from the assignment description and grading rubric).

Each strategy carries:
  - a fixed prompt directive (how to ask),
  - a fixed distractor-generation method (how wrong options are built),
  - a retrieval query (which evidence chunks suit this strategy),
  - a set of templates (variants of the strategy; exactly one is default).

Question `focus_areas` are tagged with the strategy name, so the existing
per-focus scoring buckets automatically become the per-strategy
"Student Understanding Profile" in reports (e.g. Explain 92% / Debugging 45%).

Custom (creator-authored) templates are planned; the UI already reserves the
slot ("Custom template — coming soon").
"""


def _t(tid: str, name: str, directive: str, default: bool = False) -> dict:
    return {"id": tid, "name": name, "directive": directive, "default": default}


STRATEGIES: list[dict] = [
    {
        "id": "explain", "name": "Explain", "default_weight": 5,
        "goal": "Verify conceptual understanding.",
        "example": "Why is a queue used here?",
        "query": "purpose design decision why choose core function class approach",
        "distractors": (
            "Incorrect options must be plausible but wrong rationales: benefits this "
            "construct does not provide in THIS code, reasons that would apply to a "
            "different data structure/approach, or purposes contradicted by the evidence."),
        "templates": [
            _t("explain_design_decision", "Explain Design Decision",
               "Ask WHY the code uses a particular structure, construct, or approach "
               "(e.g. 'Why is a queue used here?'). Correct options state the actual "
               "reason evident from the code.", default=True),
            _t("explain_function_purpose", "Explain Function Purpose",
               "Pick one concrete function from the evidence and ask what its purpose/"
               "role in the program is."),
            _t("explain_algorithm", "Explain Algorithm",
               "Ask what algorithmic idea the code implements and why it fits this problem."),
            _t("explain_data_structure", "Explain Data Structure",
               "Ask why a specific data structure is used and what property of it the code relies on."),
        ],
    },
    {
        "id": "debugging", "name": "Debugging", "default_weight": 1,
        "goal": "Verify whether students can identify incorrect logic.",
        "example": "Which change would break/fix this condition?",
        "query": "condition if else boundary check validate error handle edge",
        "distractors": (
            "Base every option ONLY on the evidence. Correct options identify genuine "
            "flaws, fragile assumptions, or unhandled cases actually visible in the code; "
            "incorrect options accuse the code of flaws it verifiably does NOT have."),
        "templates": [
            _t("find_the_bug", "Find the Bug",
               "Ask which statements correctly identify a real flaw/limitation in the code.",
               default=True),
            _t("find_incorrect_condition", "Find Incorrect Condition",
               "Focus on boundary/logic conditions: which condition is wrong or fragile, "
               "or what input would make a given condition misbehave."),
            _t("find_missing_statement", "Find Missing Statement",
               "Ask what necessary handling/statement is absent (e.g. missing reset, "
               "missing validation) given the code's intent."),
            _t("find_incorrect_variable", "Find Incorrect Variable",
               "Ask which variable use/update is wrong or would cause incorrect results."),
            _t("find_incorrect_algorithm", "Find Incorrect Algorithm",
               "Ask whether the implemented algorithm actually satisfies the stated intent, "
               "and where it deviates."),
        ],
    },
    {
        "id": "execution", "name": "Execution", "default_weight": 4,
        "goal": "Verify whether students can mentally execute the program.",
        "example": "What is the value of x after the third iteration?",
        "query": "loop iterate call main run compute update state variable",
        "distractors": (
            "Incorrect options must be values/orders produced by COMMON TRACING MISTAKES: "
            "off-by-one iteration counts, wrong initial value, skipped condition, "
            "reversed call order, or using the pre-update value."),
        "templates": [
            _t("trace_variables", "Trace Variables",
               "Ask the taker to trace concrete variable values through an execution of "
               "the code in the evidence.", default=True),
            _t("trace_function_calls", "Trace Function Calls",
               "Ask which functions are called, in what order, for a concrete run."),
            _t("predict_output", "Predict Output",
               "Ask what the code prints/returns for a concrete, evidence-grounded input."),
            _t("trace_recursion", "Trace Recursion",
               "Ask about the recursion: depth, base-case hit, or argument values at a given level."),
            _t("trace_state_changes", "Trace State Changes",
               "Ask how a data structure's contents change step by step during execution."),
        ],
    },
    {
        "id": "prediction", "name": "Prediction", "default_weight": 2,
        "goal": "Verify reasoning about unseen situations.",
        "example": "What happens if this input is empty?",
        "query": "exception raise error return output result input handle",
        "distractors": (
            "Incorrect options must be plausible alternative outcomes: the wrong exception "
            "type, a silently wrong value instead of an error, or behavior the code would "
            "show only under a different condition."),
        "templates": [
            _t("predict_behaviour", "Predict Behaviour",
               "Describe a concrete situation not explicitly tested in the code and ask "
               "what the code would do.", default=True),
            _t("predict_runtime", "Predict Runtime",
               "Ask how runtime/behavior changes as input grows or conditions change."),
            _t("predict_exception", "Predict Exception",
               "Ask what error/exception (if any) a specific scenario triggers."),
            _t("predict_side_effects", "Predict Side Effects",
               "Ask what state/files/outputs are affected beyond the return value."),
        ],
    },
    {
        "id": "modification", "name": "Modification", "default_weight": 3,
        "goal": "Verify adaptation ability.",
        "example": "How would you support a new requirement?",
        "query": "function parameter config extend add support feature change",
        "distractors": (
            "Incorrect options must be changes that LOOK reasonable but would break "
            "existing behavior, miss a dependency visible in the evidence, or fail to "
            "achieve the requirement."),
        "templates": [
            _t("support_new_requirement", "Support New Requirement",
               "State a small new requirement and ask which changes would correctly "
               "implement it in THIS codebase.", default=True),
            _t("optimize_complexity", "Optimize Complexity",
               "Ask which change would genuinely improve time/space complexity here."),
            _t("refactor_code", "Refactor Code",
               "Ask which refactoring preserves behavior while improving the code."),
            _t("improve_robustness", "Improve Robustness",
               "Ask which change would make the code handle failures/bad input better."),
        ],
    },
    {
        "id": "comparison", "name": "Comparison", "default_weight": 3,
        "goal": "Compare alternatives.",
        "example": "Why this implementation instead of an alternative?",
        "query": "algorithm data structure implementation approach alternative choice",
        "distractors": (
            "Incorrect options must swap or misattribute trade-offs: advantages that "
            "actually belong to the alternative, or costs the chosen approach does not have."),
        "templates": [
            _t("compare_implementations", "Compare Implementations",
               "Compare the code's implementation with a plausible alternative and ask "
               "which trade-off statements are true.", default=True),
            _t("compare_algorithms", "Compare Algorithms",
               "Compare the used algorithm to a named alternative on correctness/cost."),
            _t("compare_data_structures", "Compare Data Structures",
               "Compare the chosen data structure with an alternative for THIS usage."),
            _t("choose_better_design", "Choose Better Design",
               "Present design variants and ask which is better here — and why."),
        ],
    },
    {
        "id": "edge_cases", "name": "Edge Cases", "default_weight": 3,
        "goal": "Test boundary condition understanding.",
        "example": "What happens with an empty list?",
        "query": "empty null missing input validate boundary limit zero none",
        "distractors": (
            "Incorrect options must be plausible but wrong boundary behaviors: claiming a "
            "crash where the code actually handles it, or claiming graceful handling where "
            "the evidence shows none."),
        "templates": [
            _t("missing_input", "Missing Input",
               "Ask how the code behaves when an expected input/field is missing.", default=True),
            _t("empty_input", "Empty Input",
               "Ask what happens on empty collections/strings/files."),
            _t("large_dataset", "Large Dataset",
               "Ask what happens (memory/time/limits) with very large input."),
            _t("invalid_state", "Invalid State",
               "Ask how the code behaves when internal state is inconsistent/unexpected."),
            _t("corner_case", "Corner Case",
               "Ask about an unusual-but-possible combination of conditions in the code."),
        ],
    },
    {
        "id": "complexity", "name": "Complexity", "default_weight": 3,
        "goal": "Test efficiency understanding.",
        "example": "What is the time complexity of this function?",
        "query": "loop nested sort search iterate algorithm complexity performance",
        "distractors": (
            "Incorrect options must be ADJACENT complexity classes or analyses that ignore "
            "one loop/operation visible in the code (e.g. O(n) vs O(n log n) vs O(n²))."),
        "templates": [
            _t("time_complexity", "Time Complexity",
               "Ask for the time complexity of a specific function in the evidence.", default=True),
            _t("space_complexity", "Space Complexity",
               "Ask for the additional space the code uses and why."),
            _t("bottleneck_analysis", "Bottleneck Analysis",
               "Ask which part dominates cost for large inputs."),
            _t("scalability", "Scalability",
               "Ask what breaks first as data/users grow, given the code."),
        ],
    },
    {
        "id": "design", "name": "Design", "default_weight": 3,
        "goal": "Test architecture understanding.",
        "example": "Why is this responsibility in this module?",
        "query": "class module structure imports responsibility layer architecture",
        "distractors": (
            "Incorrect options must misattribute responsibilities (claiming module A does "
            "what module B does) or assert couplings/patterns the evidence contradicts."),
        "templates": [
            _t("design_rationale", "Design Rationale",
               "Ask why the code is organized the way it is (modules/layers/boundaries).",
               default=True),
            _t("responsibility", "Responsibility",
               "Ask which module/class is responsible for a given concern."),
            _t("coupling_cohesion", "Coupling & Cohesion",
               "Ask which statements about dependencies between modules are true."),
            _t("pattern_recognition", "Pattern Recognition",
               "Ask which design pattern/idiom the code actually follows."),
        ],
    },
    {
        "id": "testing", "name": "Testing", "default_weight": 3,
        "goal": "Test verification mindset.",
        "example": "Which test best verifies this behavior?",
        "query": "test assert validate check verify behavior case",
        "distractors": (
            "Incorrect options must be tests that LOOK relevant but do not actually "
            "exercise the target logic, assert the wrong thing, or would pass even if "
            "the code were broken."),
        "templates": [
            _t("best_test_case", "Best Test Case",
               "Ask which test case would best verify a specific behavior in the evidence.",
               default=True),
            _t("missing_test", "Missing Test",
               "Ask which important case is NOT covered by the visible tests/logic."),
            _t("boundary_test", "Boundary Test",
               "Ask which test would catch a boundary error in this code."),
            _t("failure_scenario", "Failure Scenario",
               "Ask which scenario would expose a failure mode of this code."),
        ],
    },
]


# ---------------------------------------------------------------------------
# Small-model scaffolding. Local 7B models imitate concrete patterns far
# better than they follow abstract directives, so every template gets a FIXED
# stem pattern (fill-in-the-placeholders skeleton) and every strategy gets a
# code-quoting policy. Without this, a local model tends to paste a code block
# into every stem; GPT-4o naturally mixes conceptual/flow/architecture
# questions — the scaffolding closes that gap.
#   code_quote: "snippet" = quote the 3-7 lines the question hinges on;
#               "minimal" = at most 1-3 lines (e.g. a signature) if needed;
#               "none"    = conceptual — refer to functions/files by name only.
# ---------------------------------------------------------------------------

CODE_QUOTE = {
    "explain": "minimal", "debugging": "snippet", "execution": "snippet",
    "prediction": "minimal", "modification": "minimal", "comparison": "none",
    "edge_cases": "minimal", "complexity": "snippet", "design": "none",
    "testing": "minimal",
}

STEM_PATTERNS = {
    # Explain — conceptual, name things instead of pasting them
    "explain_design_decision": "Why does <function/module> in <file> use <construct/approach>?",
    "explain_function_purpose": "What is the role of <function> (<file>) in this project?",
    "explain_algorithm": "Which statements correctly describe the algorithmic idea implemented by <function> in <file>?",
    "explain_data_structure": "Why is <data structure> used in <function> (<file>)?",
    # Execution — quote the exact lines being traced
    "trace_variables": "Consider this code from <file>:\n<3-7 line snippet>\nAfter <concrete step/iteration>, which statements about <variable> are correct?",
    "trace_function_calls": "When <entry function> in <file> runs, which statements about the order of function calls are correct?",
    "predict_output": "Consider this code from <file>:\n<3-7 line snippet>\nWhat does it return/print for <concrete input>?",
    "trace_recursion": "Consider the recursive function <function> in <file>:\n<3-7 line snippet>\nWhich statements about its recursion for <input> are correct?",
    "trace_state_changes": "Consider this code from <file>:\n<3-7 line snippet>\nHow does <data structure> change while it runs?",
    # Debugging — quote the suspect lines
    "find_the_bug": "Consider this code from <file>:\n<3-7 line snippet>\nWhich statements identify a real flaw or limitation?",
    "find_incorrect_condition": "Consider this code from <file>:\n<3-7 line snippet>\nWhich statements about the condition(s) are correct?",
    "find_missing_statement": "Consider this code from <file>:\n<3-7 line snippet>\nWhat necessary handling is missing?",
    "find_incorrect_variable": "Consider this code from <file>:\n<3-7 line snippet>\nWhich statements about how <variable> is used/updated are correct?",
    "find_incorrect_algorithm": "The function <function> in <file> is meant to <intent>:\n<3-7 line snippet>\nWhich statements about whether it achieves this are correct?",
    # Prediction — situation-first, little or no code
    "predict_behaviour": "What happens when <function> in <file> is called with <situation>?",
    "predict_runtime": "How does the behavior/runtime of <function> (<file>) change as <input grows / condition changes>?",
    "predict_exception": "What happens if <error scenario> while <function> (<file>) runs?",
    "predict_side_effects": "Beyond its return value, what does <function> in <file> affect?",
    # Modification — conceptual change reasoning
    "support_new_requirement": "To make this project <new requirement>, which changes would work?",
    "optimize_complexity": "Which change would genuinely reduce the cost of <function> (<file>)?",
    "refactor_code": "Which refactoring of <function> (<file>) preserves behavior while improving the code?",
    "improve_robustness": "Which change would make <function> (<file>) handle failures or bad input better?",
    # Comparison — pure concept, no code
    "compare_implementations": "This project implements <task> using <approach>. Compared with <alternative>, which statements are true?",
    "compare_algorithms": "The project uses <algorithm> for <task>. Compared with <alternative algorithm>, which statements are true?",
    "compare_data_structures": "The project stores <data> in <structure>. Compared with <alternative structure>, which statements are true?",
    "choose_better_design": "For <goal in this project>, which statements about the design alternatives are correct?",
    # Edge cases — scenario-first
    "missing_input": "What happens when <expected input/field> is missing while <function> (<file>) runs?",
    "empty_input": "What happens when <function> (<file>) receives an empty <collection/string>?",
    "large_dataset": "What happens as the input to <function> (<file>) becomes very large?",
    "invalid_state": "What happens if <state> is inconsistent when <function> (<file>) runs?",
    "corner_case": "Which statements describe how <function> (<file>) behaves when <corner case>?",
    # Complexity — quote the loop(s) that matter
    "time_complexity": "Consider this code from <file>:\n<3-7 line snippet>\nWhat is its time complexity?",
    "space_complexity": "Consider this code from <file>:\n<3-7 line snippet>\nHow much extra memory does it use, and why?",
    "bottleneck_analysis": "Which part of <function/pipeline> in <file> dominates the cost for large inputs?",
    "scalability": "As data grows, which statements about the scalability of <component> are correct?",
    # Design — architecture in words
    "design_rationale": "Why is this project organized with <module structure / separation>?",
    "responsibility": "Which module or class is responsible for <concern> in this project?",
    "coupling_cohesion": "Which statements about the dependencies between <module A> and <module B> are correct?",
    "pattern_recognition": "Which design pattern or idiom does <component> in <file> follow?",
    # Testing — verification mindset
    "best_test_case": "Which test case would best verify <behavior> of <function> (<file>)?",
    "missing_test": "Which important case is NOT covered for <function> (<file>)?",
    "boundary_test": "Which test would catch a boundary error in <function> (<file>)?",
    "failure_scenario": "Which scenario would expose a failure mode of <function> (<file>)?",
}

for _s in STRATEGIES:
    _s["code_quote"] = CODE_QUOTE[_s["id"]]
    for _tpl in _s["templates"]:
        _tpl["pattern"] = STEM_PATTERNS.get(_tpl["id"], "")


# ---------------------------------------------------------------------------
# Creator-editable overrides — tweak any wording WITHOUT touching this file.
# Put a `strategy_overrides.json` next to run.py (or point the
# REPOPROOF_STRATEGY_OVERRIDES env var at a file):
#
# {
#   "strategies": {
#     "execution": {"code_quote": "minimal", "distractors": "..."}
#   },
#   "templates": {
#     "trace_variables": {"pattern": "...", "directive": "...", "default": true}
#   }
# }
#
# Allowed strategy keys:  name, goal, example, query, distractors,
#                         code_quote, default_weight
# Allowed template keys:  name, directive, pattern, default
# Applied at import time — restart the server after editing. Unknown ids/keys
# are ignored silently, and a broken JSON file just means "no overrides".
# See strategy_overrides.example.json for a starting point.
# ---------------------------------------------------------------------------
import json as _json
import os as _os
from pathlib import Path as _Path

_OVERRIDE_PATH = _Path(_os.environ.get(
    "REPOPROOF_STRATEGY_OVERRIDES",
    str(_Path(__file__).resolve().parent.parent / "strategy_overrides.json")))

_STRATEGY_KEYS = ("name", "goal", "example", "query", "distractors", "code_quote", "default_weight")
_TEMPLATE_KEYS = ("name", "directive", "pattern", "default")


def _apply_overrides() -> None:
    if not _OVERRIDE_PATH.is_file():
        return
    try:
        data = _json.loads(_OVERRIDE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    strat_over = data.get("strategies", {}) or {}
    tmpl_over = data.get("templates", {}) or {}
    for s in STRATEGIES:
        for key, val in (strat_over.get(s["id"]) or {}).items():
            if key in _STRATEGY_KEYS:
                s[key] = val
        for t in s["templates"]:
            for key, val in (tmpl_over.get(t["id"]) or {}).items():
                if key in _TEMPLATE_KEYS:
                    t[key] = val


_apply_overrides()

STRATEGY_BY_ID = {s["id"]: s for s in STRATEGIES}


def default_template(strategy: dict) -> dict:
    return next((t for t in strategy["templates"] if t.get("default")), strategy["templates"][0])


def public_catalog() -> list[dict]:
    """Catalog for the UI (/api/meta): no prompt/distractor internals."""
    return [{
        "id": s["id"], "name": s["name"], "goal": s["goal"],
        "example": s["example"], "default_weight": s["default_weight"],
        "templates": [{"id": t["id"], "name": t["name"], "default": bool(t.get("default"))}
                      for t in s["templates"]],
    } for s in STRATEGIES]
