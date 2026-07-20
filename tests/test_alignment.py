import unittest

from app.alignment import (
    align_assessment_targets,
    build_assessment_targets,
    extract_document_text,
)
from app.generator import generate_questions
from app.knowledge import expand_concepts


CHUNKS = [
    {
        "id": "c0",
        "kind": "function",
        "title": "Function clean_records",
        "text": (
            "Function clean_records in pipeline.py.\nCode:\n"
            "def clean_records(rows):\n"
            "    return [row for row in rows if row.get('value') is not None]"
        ),
        "file": "pipeline.py",
        "start_line": 1,
        "end_line": 2,
        "snapshot": "test",
        "evidence_types": [
            "symbol_table", "data_flow_graph", "control_flow_graph",
        ],
    },
    {
        "id": "c1",
        "kind": "flow",
        "title": "Call flow from run_pipeline",
        "text": "run_pipeline -> fetch_records -> clean_records -> save_records",
        "file": "pipeline.py",
        "start_line": 4,
        "end_line": 8,
        "snapshot": "test",
        "evidence_types": [
            "call_graph", "data_flow_graph", "control_flow_graph",
        ],
    },
]


class AssessmentAlignmentTests(unittest.TestCase):
    def test_context_targets_are_extracted_and_weighted(self):
        text = extract_document_text("rubric.md", b"- Explain the ETL workflow. 20 marks.\n")
        targets = build_assessment_targets(
            "Students know Python functions.",
            "",
            scope_documents=[{"name": "rubric.md", "text": text}],
        )
        self.assertEqual([target["kind"] for target in targets],
                         ["prior_knowledge", "project_scope"])
        self.assertGreater(targets[1]["weight"], targets[0]["weight"])

    def test_curriculum_queries_share_concept_expansion(self):
        terms = expand_concepts("Explain the ETL data ingestion workflow.")
        self.assertIn("fetch", terms)
        self.assertIn("pipeline", terms)

    def test_rubric_table_uses_criterion_and_excellent_descriptor(self):
        rubric = """Criteria Ratings Points
Data Integration & Cleaning
3/3 pts
Excellent
Multiple files are integrated and invalid rows are removed.
3 pts
Good
Most files are integrated.
2 pts
"""
        targets = build_assessment_targets(
            "",
            "",
            scope_documents=[{"name": "rubric.pdf", "text": rubric}],
        )
        self.assertEqual(len(targets), 1)
        self.assertIn("Data Integration & Cleaning", targets[0]["description"])
        self.assertIn("invalid rows", targets[0]["description"])
        self.assertGreater(targets[0]["weight"], 2)

    def test_markdown_heading_and_total_are_not_assessment_targets(self):
        targets = build_assessment_targets(
            "",
            "",
            scope_documents=[{
                "name": "rubric.md",
                "text": (
                    "# Assignment 2 Tasks\n\n"
                    "- Explain the batch validation workflow. 10 points.\n\n"
                    "**Total:** 25 points"
                ),
            }],
        )
        self.assertEqual(len(targets), 1)
        self.assertIn("validation workflow", targets[0]["description"])

    def test_extended_total_and_bonus_line_is_not_an_assessment_target(self):
        targets = build_assessment_targets(
            "",
            "",
            scope_documents=[{
                "name": "rubric.md",
                "text": (
                    "Explain the dashboard integration behavior. 8 points.\n\n"
                    "**Total:** 25 points (plus up to 2 bonus points for Assignment 1 "
                    "integration, capped at 25 overall)"
                ),
            }],
        )
        self.assertEqual(len(targets), 1)
        self.assertIn("dashboard integration", targets[0]["description"])

    def test_targets_align_to_project_evidence(self):
        targets = build_assessment_targets(
            "",
            "Explain how records move through cleaning before they are saved.",
        )
        aligned = align_assessment_targets(
            CHUNKS,
            targets,
            [{"id": "data_flow", "weight": 5}],
        )
        self.assertEqual(aligned[0]["topic_ids"], ["data_flow"])
        self.assertNotEqual(aligned[0]["coverage"], "unmatched")
        self.assertTrue(aligned[0]["evidence"])

    def test_local_generation_keeps_question_alignment(self):
        target = {
            "id": "t0",
            "kind": "project_scope",
            "label": "Explain record cleaning",
            "description": "Explain how invalid records are removed during cleaning.",
            "source": "rubric.md",
            "weight": 2,
            "topic_ids": ["project_logic"],
            "topic_names": ["Implementation / Code Logic"],
            "coverage": "strong",
            "evidence": [{"chunk_id": "c0", "score": 2.5}],
        }
        questions, warnings = generate_questions(
            CHUNKS,
            {
                "provider": "mock",
                "num_questions": 1,
                "choice_count": 4,
                "correct_mode": "exact",
                "correct_exact": 1,
                "difficulty": 3,
                "focus_areas": [{"id": "project_logic", "weight": 5}],
                "assessment_targets": [target],
            },
        )
        self.assertEqual(len(questions), 1, warnings)
        self.assertEqual(questions[0]["alignment"]["label"], target["label"])
        self.assertEqual(questions[0]["alignment"]["source"], "rubric.md")


if __name__ == "__main__":
    unittest.main()
