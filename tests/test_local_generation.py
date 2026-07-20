import random
import unittest

from app.generator import (
    _catalog_tasks,
    _normalize,
    _specific_evidence_errors,
    _template_bundle,
    generate_questions,
)
from app.knowledge import EvidenceStore
from app.strategies import TEMPLATE_BY_ID, TOPIC_BY_ID, weighted_template_schedule
from app.validator import find_similar_question, validate_maq


def chunk(chunk_id, kind, title, text, evidence_types):
    return {
        "id": chunk_id,
        "kind": kind,
        "title": title,
        "text": text,
        "file": "pipeline.py",
        "start_line": 1,
        "end_line": 8,
        "snapshot": "test123",
        "evidence_types": evidence_types,
    }


CHUNKS = [
    chunk(
        "c0", "module_graph", "Module graph summary",
        "pipeline.py -> storage.py; pipeline.py coordinates extraction and storage.",
        ["module_graph"],
    ),
    chunk(
        "c1", "function", "Function fetch_records (pipeline.py)",
        "Function fetch_records in pipeline.py.\nCode:\ndef fetch_records(client):\n"
        "    response = client.get('/records')\n    return response.json()",
        ["symbol_table", "data_flow_graph", "control_flow_graph", "api_discovery"],
    ),
    chunk(
        "c2", "function", "Function clean_records (pipeline.py)",
        "Function clean_records in pipeline.py.\nCode:\ndef clean_records(rows):\n"
        "    return [row for row in rows if row.get('value') is not None]",
        ["symbol_table", "data_flow_graph", "control_flow_graph"],
    ),
    chunk(
        "c3", "flow", "Call flow from run_pipeline",
        "run_pipeline -> fetch_records -> clean_records -> save_records",
        ["call_graph", "data_flow_graph", "control_flow_graph"],
    ),
    chunk(
        "c4", "sql_analysis", "SQL analysis summary",
        "CREATE TABLE records (id INTEGER PRIMARY KEY, value REAL NOT NULL)",
        ["sql_analysis"],
    ),
    chunk(
        "c5", "test_discovery", "Test discovery summary",
        "test-like function: test_clean_records",
        ["test_discovery"],
    ),
    chunk(
        "c6", "complexity", "Static complexity indicators",
        "clean_records: 2 code lines; 1 loop keyword; 1 branch keyword.",
        ["complexity_analysis"],
    ),
    chunk(
        "c7", "readme", "README",
        "The pipeline retrieves records, validates values, and stores clean results.",
        [],
    ),
    chunk(
        "c8", "function", "Function stop_services (pipeline.py)",
        "Function stop_services in pipeline.py.\nCode:\ndef stop_services(stop):\n"
        "    if stop:\n"
        "        subscriber.loop_stop()\n"
        "        subscriber.disconnect()\n"
        "        dashboard_stop.set()",
        ["symbol_table", "data_flow_graph", "control_flow_graph"],
    ),
]


class LocalGenerationTests(unittest.TestCase):
    def test_focus_matrix_drives_template_schedule(self):
        project_logic = [
            template["id"]
            for template in weighted_template_schedule(TOPIC_BY_ID["project_logic"], 5)
        ]
        self.assertEqual(
            project_logic[:4],
            ["code_explain", "code_trace", "debugging", "modification"],
        )
        architecture = [
            template["id"]
            for template in weighted_template_schedule(TOPIC_BY_ID["architecture"], 5)
        ]
        self.assertEqual(architecture[0], "design_behavior")
        self.assertNotIn("code_trace", architecture)

    def test_template_bundle_uses_required_evidence(self):
        store = EvidenceStore(CHUNKS)
        evidence, missing = _template_bundle(
            store,
            TOPIC_BY_ID["project_logic"],
            TEMPLATE_BY_ID["code_explain"],
            "",
        )
        self.assertFalse(missing)
        self.assertIn(evidence[0]["kind"], {"function", "notebook_cell", "source"})

        evidence, missing = _template_bundle(
            store,
            TOPIC_BY_ID["architecture"],
            TEMPLATE_BY_ID["design_behavior"],
            "",
        )
        self.assertFalse(missing)
        self.assertTrue(
            any("module_graph" in item["evidence_types"] for item in evidence)
        )

    def test_scenario_edge_injects_the_cited_condition_branch(self):
        tasks, warnings, tagged = _catalog_tasks(
            EvidenceStore(CHUNKS),
            {
                "choice_count": 4,
                "correct_mode": "exact",
                "correct_exact": 1,
                "focus_areas": [{"id": "data_flow", "weight": 5}],
                "template": "scenario_edge",
                "focus": "stop services subscriber dashboard state",
            },
            1,
            random.Random(42),
        )
        self.assertTrue(tagged)
        self.assertFalse(warnings)
        slot = tasks[0]["slot"]
        self.assertIn("if stop:", slot["display_code"])
        self.assertIn("dashboard_stop.set()", slot["display_code"])
        self.assertNotIn("def stop_services", slot["display_code"])

        no_code_question = {
            "stem": "What happens when stop is true?",
            "evidence": [{"chunk_id": "c8"}],
        }
        errors = _specific_evidence_errors(
            no_code_question, slot, {item["id"]: item for item in CHUNKS}
        )
        self.assertTrue(any("self-contained fenced code excerpt" in error for error in errors))

        vague_correct_answer = {
            "stem": (
                "What happens when stop is true?\n```python\n"
                + slot["display_code"]
                + "\n```"
            ),
            "options": [
                {"key": "A", "text": "Nothing happens."},
                {"key": "B", "text": "The dashboard stop event is set."},
            ],
            "answer": ["A"],
            "evidence": [{"chunk_id": slot["display_evidence_id"]}],
        }
        errors = _specific_evidence_errors(
            vague_correct_answer, slot, {item["id"]: item for item in CHUNKS}
        )
        self.assertTrue(any("exact observable" in error for error in errors))

    def test_focus_weights_allocate_question_topics(self):
        config = {
            "choice_count": 4,
            "correct_mode": "exact",
            "correct_exact": 1,
            "focus_areas": [
                {"id": "architecture", "weight": 4},
                {"id": "project_logic", "weight": 2},
            ],
        }
        tasks, warnings, tagged = _catalog_tasks(
            EvidenceStore(CHUNKS), config, 6, random.Random(42)
        )
        self.assertTrue(tagged)
        self.assertFalse(warnings)
        focuses = [task["slot"]["focus"] for task in tasks]
        self.assertEqual(focuses.count("Architecture"), 4)
        self.assertEqual(focuses.count("Implementation / Code Logic"), 2)

    def test_duplicate_detection_uses_stem_options_and_evidence(self):
        question = {
            "stem": "What happens when fetch_records receives a successful response?",
            "options": [{"text": "It returns parsed JSON."}, {"text": "It deletes the table."}],
            "evidence": [{"chunk_id": "c1"}],
        }
        duplicate = {
            "stem": "What happens when fetch_records receives a successful response?",
            "options": [{"text": "It returns parsed JSON."}, {"text": "It deletes the table."}],
            "evidence": [{"chunk_id": "c1"}],
        }
        different = {
            "stem": "Why does the schema require a non-null value?",
            "options": [{"text": "To preserve record integrity."}, {"text": "To call the API."}],
            "evidence": [{"chunk_id": "c4"}],
        }
        self.assertIsNotNone(find_similar_question(question, [duplicate]))
        self.assertIsNone(find_similar_question(question, [different]))

    def test_subjective_design_question_and_unstated_distractor_are_rejected(self):
        question = {
            "stem": (
                "Which of the following best explains why the project uses "
                "a decoupled architecture with four phases?"
            ),
            "options": [
                {"key": "A", "text": "The phases can run without blocking each other."},
                {"key": "B", "text": "The design reduces the number of functions."},
                {"key": "C", "text": "The design follows a regulatory requirement."},
                {"key": "D", "text": "The separation can make components easier to test."},
            ],
            "answer": ["A"],
            "justifications": {
                "A": "The execution evidence shows independent phase boundaries.",
                "B": "The module graph shows that each phase contains several functions.",
                "C": "There is no mention of a regulatory requirement.",
                "D": "This may be a benefit, but it is not explicitly stated in the evidence.",
            },
            "difficulty": 3,
            "evidence": [{"chunk_id": "c0"}],
        }
        errors = validate_maq(question, 4, 1)
        self.assertTrue(any("factually correct statement" in error for error in errors))
        self.assertTrue(any("treated as false only because it is unstated" in error for error in errors))

    def test_objective_design_behavior_question_passes_validation(self):
        question = {
            "stem": "Which statement correctly describes the dependency between the project phases?",
            "options": [
                {"key": "A", "text": "Publishing receives data produced by retrieval."},
                {"key": "B", "text": "Retrieval imports and calls the visualization phase."},
                {"key": "C", "text": "Every phase is implemented in one shared function."},
                {"key": "D", "text": "Visualization executes before retrieval produces data."},
            ],
            "answer": ["A"],
            "justifications": {
                "A": "The data-flow edge connects retrieval output to publishing input.",
                "B": "The dependency graph contains no edge from retrieval to visualization.",
                "C": "The symbol table identifies separate functions for the phases.",
                "D": "The call flow places retrieval before visualization.",
            },
            "difficulty": 3,
            "evidence": [{"chunk_id": "c0"}],
        }
        self.assertEqual(validate_maq(question, 4, 1), [])

    def test_code_question_must_copy_cited_evidence(self):
        slot = {
            "template_id": "code_trace",
            "template_name": "Code Trace / Outcome",
        }
        question = {
            "stem": "What is returned?\n```python\ndef process_data(value):\n    return value + 1\n```",
            "evidence": [{"chunk_id": "c1"}],
        }
        errors = _specific_evidence_errors(
            question, slot, {item["id"]: item for item in CHUNKS}
        )
        self.assertTrue(any("copied from a cited evidence" in error for error in errors))

        question["stem"] = (
            "What is returned?\n```python\n"
            "def fetch_records(client):\n"
            "    response = client.get('/records')\n"
            "    return response.json()\n```"
        )
        self.assertEqual(
            _specific_evidence_errors(
                question, slot, {item["id"]: item for item in CHUNKS}
            ),
            [],
        )

    def test_normalize_injects_grounded_code_and_removes_cell_identifier(self):
        slot = {
            "slot": "project_logic:code_explain",
            "focus": "Implementation / Code Logic",
            "template_name": "Code Explain",
            "display_code": (
                "def fetch_records(client):\n"
                "    response = client.get('/records')\n"
                "    return response.json()"
            ),
            "display_language": "python",
            "display_evidence_id": "c1",
        }
        raw = {
            "stem": "What does `fetch_records` do in notebook cell 8?",
            "options": [
                {"text": "Returns JSON.", "correct": True, "justification": ""},
                {"text": "Deletes data.", "correct": False, "justification": ""},
            ],
            "difficulty": 3,
            "evidence_ids": [],
        }
        question = _normalize(
            raw, slot, {item["id"]: item for item in CHUNKS}, random.Random(1)
        )
        self.assertNotIn("cell 8", question["stem"])
        self.assertIn("```python\ndef fetch_records", question["stem"])
        self.assertEqual(question["evidence"][0]["chunk_id"], "c1")

    def test_mock_code_logic_keeps_requested_question_count(self):
        questions, warnings = generate_questions(
            CHUNKS,
            {
                "provider": "mock",
                "num_questions": 5,
                "choice_count": 4,
                "correct_mode": "exact",
                "correct_exact": 1,
                "difficulty": 3,
                "seed": 42,
                "focus_areas": [{"id": "project_logic", "weight": 5}],
            },
        )
        self.assertEqual(len(questions), 5, warnings)
        self.assertEqual(
            [question["slot"] for question in questions],
            [
                "project_logic:code_explain",
                "project_logic:code_trace",
                "project_logic:debugging",
                "project_logic:modification",
                "project_logic:testing_behavior",
            ],
        )


if __name__ == "__main__":
    unittest.main()
