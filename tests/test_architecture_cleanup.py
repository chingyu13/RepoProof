import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app import config, generator
from app.assessment_catalog import TOPICS
from app.generator import _raw_openai_prompt, generate_questions
from app.knowledge import evidence_types_for_chunk
from app.main import GenerateConfig, app, print_view


class ArchitectureCleanupTests(unittest.TestCase):
    def test_generation_config_rejects_removed_legacy_fields(self):
        for field in (
            "topic", "areas", "template", "keep_approved", "question_emphasis",
            "allow_code", "excluded_assessment_points",
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                GenerateConfig(**{field: "legacy"})

    def test_generation_without_a_plan_has_no_legacy_fallback(self):
        with self.assertRaisesRegex(ValueError, "confirmed question plan"):
            generate_questions([], {"provider": "mock", "num_questions": 2})

    def test_browser_local_is_the_only_ollama_transport(self):
        self.assertFalse(hasattr(config, "LOCAL_LLM_URL"))
        self.assertFalse(hasattr(config, "local_llm_available"))
        self.assertFalse(hasattr(generator, "_call_llm"))
        with self.assertRaisesRegex(ValueError, "Browser-local"):
            generate_questions([], {"provider": "local"})

    def test_topics_do_not_own_a_second_template_matrix(self):
        self.assertTrue(all("template_weights" not in topic for topic in TOPICS))

    def test_evidence_type_is_not_inferred_from_legacy_chunk_kind(self):
        self.assertEqual(evidence_types_for_chunk({"kind": "function"}), ())

    def test_only_background_generation_route_remains(self):
        paths = {route.path for route in app.routes}
        self.assertIn("/static", paths)
        self.assertIn("/api/projects/{project_id}/generation-runs", paths)
        self.assertNotIn("/api/projects/{project_id}/generate", paths)

    def test_raw_code_logic_rules_are_injected_once(self):
        prompt = _raw_openai_prompt(
            [{"id": "f0", "file": "pipeline.py", "text": "print('ok')"}],
            {
                "focus_areas": [
                    {"id": "project_logic", "weight": 5},
                ],
            },
            choice_count=4,
            correct_counts=[1, 1, 1],
            difficulty=3,
        )
        self.assertEqual(prompt.count("CODE LOGIC PROTOTYPE REQUIREMENTS:"), 1)

    def test_step_two_uses_inline_context_file_tags(self):
        html = Path("app/static/creator.html").read_text()
        css = Path("app/static/creator.css").read_text()
        script = Path("app/static/creator.js").read_text()
        self.assertNotIn("priorFileNames", html + script)
        self.assertNotIn("scopeFileNames", html + script)
        self.assertIn('id="priorFileTags"', html)
        self.assertIn('id="scopeFileTags"', html)
        self.assertIn(".context-fields{display:grid;gap:.4rem", css)
        self.assertIn('class="framework-field question-count-field"', html)
        self.assertIn('class="difficulty-control"', html)
        self.assertIn('class="difficulty-icon-wrap"', html)
        self.assertNotIn("numeric-step", html + css + script)
        self.assertIn("const difficultyIcons = {", script)
        self.assertNotIn("Target avg difficulty", html + script)
        for name in ("dropdown.svg", "easy_easy.svg", "easy.svg", "mid.svg", "hard.svg", "hard_hard.svg"):
            self.assertTrue((Path("app/static/assets") / name).is_file())

    def test_print_view_escapes_dynamic_content(self):
        rows = {
            ("assessments", 1): {
                "id": 1,
                "project_id": 2,
                "title": "<script>title()</script>",
                "question_ids": [3],
            },
            ("projects", 2): {
                "name": "<b>project</b>",
                "snapshot_id": "snapshot",
            },
            ("questions", 3): {
                "stem": "<img src=x onerror=alert(1)>",
                "difficulty": 3,
                "options": [{"key": "A", "text": "<script>answer()</script>"}],
                "answer": ["A"],
                "evidence": [],
                "explanation": "<b>explanation</b>",
            },
        }
        with patch("app.main.db.get", side_effect=lambda table, row_id: rows[(table, row_id)]):
            response = print_view(1, key=1)
        html = response.body.decode()
        self.assertNotIn("<script>title()", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;title()", html)
        self.assertIn("&lt;img src=x", html)


if __name__ == "__main__":
    unittest.main()
