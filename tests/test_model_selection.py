import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import config
from app.generator import _call_llm
from app.main import GenerateConfig, meta


class ModelSelectionTests(unittest.TestCase):
    def test_openai_catalog_has_current_choices(self):
        model_ids = [model["id"] for model in config.openai_model_options()]
        self.assertEqual(model_ids[:3], [
            "gpt-5.6-terra",
            "gpt-5.6-sol",
            "gpt-5.6-luna",
        ])
        self.assertIn("gpt-4o", model_ids)
        self.assertIn("gpt-4o-mini", model_ids)

    def test_model_resolution_rejects_unlisted_request(self):
        self.assertEqual(
            config.resolve_model("openai", "untrusted-model"),
            config.OPENAI_MODEL,
        )
        self.assertEqual(
            config.resolve_model("local", "untrusted-model"),
            config.LOCAL_LLM_MODEL,
        )

    def test_meta_exposes_one_openai_model_catalog(self):
        with (
            patch("app.main.config.local_llm_available", return_value=True),
            patch("app.main.config.default_provider", return_value="openai"),
        ):
            result = meta()
        self.assertEqual(
            result["providers"]["openai"]["models"],
            config.openai_model_options(),
        )

    def test_generation_config_accepts_selected_model(self):
        cfg = GenerateConfig(provider="openai", model="gpt-5.6-sol")
        self.assertEqual(cfg.model, "gpt-5.6-sol")

    def test_gpt_56_uses_reasoning_compatible_chat_parameters(self):
        completion = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"questions": []}')
                )
            ]
        )
        client = MagicMock()
        client.chat.completions.create.return_value = completion
        with patch("openai.OpenAI", return_value=client):
            result = _call_llm(
                "openai",
                "system",
                "user",
                model="gpt-5.6-terra",
            )

        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(result, {"questions": []})
        self.assertEqual(kwargs["model"], "gpt-5.6-terra")
        self.assertEqual(kwargs["reasoning_effort"], "low")
        self.assertEqual(kwargs["max_completion_tokens"], 16_000)
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("max_tokens", kwargs)


if __name__ == "__main__":
    unittest.main()
