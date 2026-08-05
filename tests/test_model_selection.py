import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import config
from app.generator import _call_openai
from app.main import GenerateConfig, meta


class ModelSelectionTests(unittest.TestCase):
    def test_openai_catalog_has_current_choices(self):
        model_ids = [model["id"] for model in config.openai_model_options()]
        self.assertEqual(model_ids, [
            "gpt-5.6-terra",
            "gpt-5.6-luna",
            "gpt-4o-mini",
        ])

    def test_local_catalog_keeps_baseline_and_reasoning_candidate(self):
        models = config.local_model_options()

        self.assertEqual(
            [model["id"] for model in models],
            ["qwen2.5-coder:7b", "qwen3.5:9b"],
        )
        self.assertIsNone(models[0]["think"])
        self.assertIs(models[1]["think"], False)

    def test_model_resolution_rejects_unlisted_request(self):
        self.assertEqual(
            config.resolve_model("openai", "untrusted-model"),
            config.OPENAI_MODEL,
        )
        self.assertEqual(
            config.resolve_model("local", "untrusted-model"),
            config.LOCAL_LLM_MODEL,
        )
        self.assertEqual(config.resolve_model("local", "qwen3.5:9b"), "qwen3.5:9b")

    def test_meta_exposes_browser_managed_local_provider_without_server_probe(self):
        with patch("app.main.config.default_provider", return_value="openai"):
            result = meta()
        self.assertEqual(
            result["providers"]["openai"]["models"],
            config.openai_model_options(),
        )
        self.assertTrue(result["providers"]["local"]["client_managed"])
        self.assertEqual(
            result["providers"]["local"]["url"],
            config.BROWSER_OLLAMA_URL,
        )
        self.assertEqual(
            result["providers"]["local"]["models"],
            config.local_model_options(),
        )

    def test_generation_config_accepts_selected_model(self):
        cfg = GenerateConfig(provider="openai", model="gpt-5.6-luna")
        self.assertEqual(cfg.model, "gpt-5.6-luna")

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
            result = _call_openai(
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
