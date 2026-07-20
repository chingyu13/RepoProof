import random
import unittest
from unittest.mock import patch

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
        self.assertTrue(
            any(
                item["kind"] in {"module_graph", "flow", "callgraph", "import_graph"}
                for item in evidence
            )
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

    def test_identifier_name_matching_question_is_rejected(self):
        question = {
            "stem": (
                "Which function is responsible for updating the dropdown filters "
                "based on facility records?"
            ),
            "options": [
                {"key": "A", "text": "dropdown_update_map_and_table"},
                {"key": "B", "text": "refresh_filter_dropdowns"},
                {"key": "C", "text": "_sync_toggle"},
                {"key": "D", "text": "_on_toggle"},
            ],
            "answer": ["B"],
            "justifications": {
                "A": "It updates the map and table.",
                "B": "It rebuilds filter options from facility records.",
                "C": "It synchronizes toggle styles.",
                "D": "It handles toggle clicks.",
            },
            "difficulty": 3,
            "evidence": [{"chunk_id": "c8"}],
        }
        errors = validate_maq(question, 4, 1)
        self.assertTrue(any("identifier-name matching" in error for error in errors))

    def test_giveaway_absolute_distractors_are_rejected(self):
        question = {
            "stem": "Which statement correctly describes how the dropdown options are refreshed?",
            "options": [
                {"key": "A", "text": "Existing selections are retained when still valid."},
                {"key": "B", "text": "The options are always replaced on every call."},
                {"key": "C", "text": "Fuel values are used to build region choices."},
                {"key": "D", "text": "A missing previous value is copied into the new options."},
            ],
            "answer": ["A"],
            "justifications": {
                "A": "The previous value is reset only when absent from the new options.",
                "B": "Unchanged option lists skip the update.",
                "C": "Region choices use network_region values.",
                "D": "An absent previous value is reset to All.",
            },
            "difficulty": 3,
            "evidence": [{"chunk_id": "c8"}],
        }
        errors = validate_maq(question, 4, 1)
        self.assertTrue(any("giveaway absolute wording" in error for error in errors))

    def test_broad_named_function_behavior_question_is_rejected(self):
        question = {
            "stem": "Which observable behavior occurs when `refresh_filter_dropdowns` is called?",
            "options": [
                {"key": "A", "text": "It refreshes map markers."},
                {"key": "B", "text": "It updates dropdown options from facility records."},
                {"key": "C", "text": "It updates only region data."},
                {"key": "D", "text": "It clears the dropdown options."},
            ],
            "answer": ["B"],
            "justifications": {
                "A": "The function does not update markers.",
                "B": "It derives dropdown options from current records.",
                "C": "It derives both region and fuel values.",
                "D": "It includes derived values in each list.",
            },
            "difficulty": 3,
            "evidence": [{"chunk_id": "c8"}],
        }
        errors = validate_maq(question, 4, 1)
        self.assertTrue(any("broad purpose can be guessed" in error for error in errors))

    def test_architecture_requires_relational_evidence(self):
        trivial_module = chunk(
            "c9",
            "module_graph",
            "Module graph summary",
            "Static module inventory:\npipeline.py [Python]",
            ["module_graph"],
        )
        evidence, missing = _template_bundle(
            EvidenceStore([trivial_module]),
            TOPIC_BY_ID["architecture"],
            TEMPLATE_BY_ID["design_behavior"],
            "",
        )
        self.assertTrue(evidence)
        self.assertIn("relational architecture evidence", missing)

        tasks, warnings, tagged = _catalog_tasks(
            EvidenceStore([trivial_module, CHUNKS[-1]]),
            {
                "choice_count": 4,
                "correct_mode": "exact",
                "correct_exact": 1,
                "focus_areas": [{"id": "architecture", "weight": 5}],
            },
            1,
            random.Random(42),
        )
        self.assertTrue(tagged)
        self.assertFalse(tasks)
        self.assertTrue(any("relational architecture evidence" in warning for warning in warnings))

    def test_unavailable_focus_slots_are_reallocated(self):
        trivial_module = chunk(
            "c9",
            "module_graph",
            "Module graph summary",
            "Static module inventory:\npipeline.py [Python]",
            ["module_graph"],
        )
        tasks, warnings, tagged = _catalog_tasks(
            EvidenceStore([trivial_module, CHUNKS[-1]]),
            {
                "choice_count": 4,
                "correct_mode": "exact",
                "correct_exact": 1,
                "difficulty": 3,
                "focus_areas": [
                    {"id": "architecture", "weight": 4},
                    {"id": "project_logic", "weight": 2},
                ],
            },
            6,
            random.Random(42),
        )
        self.assertTrue(tagged)
        self.assertEqual(len(tasks), 6, warnings)
        self.assertTrue(all(
            task["slot"]["focus"] == "Implementation / Code Logic"
            for task in tasks
        ))
        self.assertTrue(any("relational architecture evidence" in warning for warning in warnings))

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

    def test_normalize_uses_backend_difficulty_and_evidence_bundle(self):
        slot = {
            "slot": "data_flow:workflow",
            "focus": "Workflow / Data Flow",
            "requested_difficulty": 4,
            "default_evidence_ids": ["c3", "c0"],
        }
        raw = {
            "stem": "Which statement correctly describes the path from retrieval to storage?",
            "options": [
                {"text": "Retrieval precedes cleaning and storage.", "correct": True},
                {"text": "Storage precedes retrieval.", "correct": False},
            ],
            "difficulty": 1,
            "evidence_ids": ["missing"],
        }
        question = _normalize(
            raw, slot, {item["id"]: item for item in CHUNKS}, random.Random(1)
        )
        self.assertEqual(question["difficulty"], 4)
        self.assertEqual(
            {item["chunk_id"] for item in question["evidence"]},
            {"c3", "c0"},
        )

    def test_normalize_remaps_explanation_option_after_shuffle(self):
        raw = {
            "stem": "Which statement correctly describes the workflow?",
            "options": [
                {"key": "A", "text": "Records are cleaned before storage.", "correct": True},
                {"key": "B", "text": "Storage happens before retrieval.", "correct": False},
                {"key": "C", "text": "Retrieval is skipped.", "correct": False},
                {"key": "D", "text": "Cleaning happens after storage.", "correct": False},
            ],
            "difficulty": 3,
            "evidence_ids": ["c3"],
            "explanation": "Option A is the correct answer because cleaning precedes storage.",
        }
        question = _normalize(
            raw,
            {"slot": "data_flow:workflow", "focus": "Workflow / Data Flow"},
            {item["id"]: item for item in CHUNKS},
            random.Random(2),
        )
        self.assertNotEqual(question["answer"], ["A"])
        self.assertIn(f"Option {question['answer'][0]}", question["explanation"])
        self.assertFalse(any(
            "different correct option" in error
            for error in validate_maq(question, 4, 1)
        ))

    def test_hidden_condition_and_explanation_key_mismatch_are_rejected(self):
        question = {
            "stem": "If `stop` is True, which statement correctly describes the result?",
            "options": [
                {"key": "A", "text": "The subscriber disconnects."},
                {"key": "B", "text": "The subscriber remains connected."},
            ],
            "answer": ["A"],
            "justifications": {
                "A": "The stop branch disconnects the subscriber.",
                "B": "The stop branch calls disconnect.",
            },
            "difficulty": 3,
            "evidence": [{"chunk_id": "c8"}],
            "explanation": "Option B is the correct answer because the connection remains active.",
        }
        errors = validate_maq(question, 2, 1)
        self.assertTrue(any("must show the code" in error for error in errors))
        self.assertTrue(any("different correct option" in error for error in errors))

    def test_workflow_template_rejects_single_condition_question(self):
        question = {
            "stem": "What happens if `stop` is True?",
            "evidence": [{"chunk_id": "c3"}],
        }
        errors = _specific_evidence_errors(
            question,
            {"template_id": "workflow", "template_name": "Workflow"},
            {item["id"]: item for item in CHUNKS},
        )
        self.assertTrue(any("multi-stage path" in error for error in errors))

    def test_local_validation_failure_is_repaired_and_measured(self):
        def draft(correct_count):
            return {
                "stem": (
                    "Which statement correctly describes the relationship between "
                    "`pipeline.py` and `storage.py`?"
                ),
                "options": [
                    {
                        "key": "A",
                        "text": "The pipeline passes processed records to storage.",
                        "correct": True,
                        "justification": "The module and flow evidence show this path.",
                    },
                    {
                        "key": "B",
                        "text": "Storage starts retrieval before the pipeline runs.",
                        "correct": correct_count == 2,
                        "justification": "The flow places retrieval before storage.",
                    },
                    {
                        "key": "C",
                        "text": "The two modules have no data relationship.",
                        "correct": False,
                        "justification": "The module graph contains their relationship.",
                    },
                    {
                        "key": "D",
                        "text": "Storage sends records back to retrieval.",
                        "correct": False,
                        "justification": "The recorded flow moves in the other direction.",
                    },
                ],
                "difficulty": 1,
                "evidence_ids": ["c0", "c3"],
                "explanation": "Option A is the correct answer.",
            }

        cfg = {
            "provider": "local",
            "num_questions": 1,
            "choice_count": 4,
            "correct_mode": "exact",
            "correct_exact": 1,
            "difficulty": 4,
            "focus_areas": [{"id": "architecture", "weight": 5}],
        }
        with (
            patch("app.generator.config.local_llm_available", return_value=True),
            patch(
                "app.generator._call_llm",
                side_effect=[draft(2), draft(1)],
            ) as call,
        ):
            questions, warnings = generate_questions(CHUNKS, cfg)

        self.assertEqual(len(questions), 1, warnings)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(questions[0]["difficulty"], 4)
        self.assertEqual(cfg["_generation_metrics"]["validation_failures"], 1)
        self.assertEqual(cfg["_generation_metrics"]["repair_calls"], 1)
        self.assertEqual(cfg["_generation_metrics"]["accepted_after_repair"], 1)

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
