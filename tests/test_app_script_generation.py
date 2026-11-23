"""Offline checks for the app's selectable image-based script generator."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.config import settings
from app.ingestion import MultimodalGenerator, _generate_multimodal_slide_script, _multimodal_setup


class AppScriptGenerationTests(unittest.TestCase):
    def test_setup_selects_claude_and_seed_prompt(self) -> None:
        with (
            patch.object(settings, "speaker_script_prompt_path", Path("prompts/speaker_script_gen/seed_v1_multimodal.md")),
            patch.object(settings, "speaker_script_provider", "anthropic"),
            patch.object(settings, "speaker_script_model", None),
            patch.object(settings, "anthropic_api_key", "test-key"),
            patch("app.ingestion.Anthropic") as client_class,
        ):
            generator = _multimodal_setup()

        self.assertIsNotNone(generator)
        self.assertEqual(generator.model, "claude-haiku-5-5")
        self.assertIn("Your primary source is the target slide image", generator.instructions)
        client_class.assert_called_once_with(api_key="test-key")

    def test_setup_selects_gpt_and_requires_its_key(self) -> None:
        with (
            patch.object(settings, "speaker_script_prompt_path", Path("prompts/speaker_script_gen/seed_v1_multimodal.md")),
            patch.object(settings, "speaker_script_provider", "openai"),
            patch.object(settings, "speaker_script_model", None),
            patch.object(settings, "openai_api_key", "test-key"),
            patch("app.ingestion.OpenAI") as client_class,
        ):
            generator = _multimodal_setup()

        self.assertEqual(generator.model, "gpt-5.6-luna")
        client_class.assert_called_once_with(api_key="test-key")

        with (
            patch.object(settings, "speaker_script_prompt_path", Path("prompts/speaker_script_gen/seed_v1_multimodal.md")),
            patch.object(settings, "speaker_script_provider", "openai"),
            patch.object(settings, "openai_api_key", "your-openai-api-key"),
        ):
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY is missing"):
                _multimodal_setup()

    def test_claude_receives_neighbor_images_notes_and_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pres_id = "example"
            images = root / pres_id
            images.mkdir()
            for index in range(3):
                (images / f"slide_{index:03d}.png").write_bytes(b"image")
            paths = [f"/static/slides/{pres_id}/slide_{i:03d}.png" for i in range(3)]

            class FakeMessages:
                def create(self, **request):
                    self.request = request
                    return SimpleNamespace(
                        stop_reason="end_turn",
                        content=[SimpleNamespace(type="text", text="The result is visible in the chart.")],
                        usage=SimpleNamespace(input_tokens=50, output_tokens=12),
                    )

            messages = FakeMessages()
            generator = MultimodalGenerator(
                instructions="Seed instructions", provider="anthropic", model="claude-haiku-5-5",
                client=SimpleNamespace(messages=messages),
            )
            with patch.object(settings, "slides_dir", root):
                script = asyncio.run(_generate_multimodal_slide_script(
                    paths, 1, pres_id, "Research talk", "Prior work used a smaller sample.", generator,
                ))

        self.assertEqual(script, "The result is visible in the chart.")
        request = messages.request
        self.assertEqual(request["system"], "Seed instructions")
        self.assertEqual(request["model"], "claude-haiku-5-5")
        self.assertEqual(request["output_config"], {"effort": "medium"})
        blocks = request["messages"][0]["content"]
        self.assertEqual(sum(block["type"] == "image" for block in blocks), 3)
        text = "\n".join(block["text"] for block in blocks if block["type"] == "text")
        self.assertIn("Target slide number: 2", text)
        self.assertIn("Target speaking time: 30 seconds", text)
        self.assertIn("Prior work used a smaller sample.", text)

    def test_gpt_uses_same_slide_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pres_id = "example"
            images = root / pres_id
            images.mkdir()
            (images / "slide_000.png").write_bytes(b"image")

            class FakeResponses:
                def create(self, **request):
                    self.request = request
                    return SimpleNamespace(output_text="A concise opening.", usage=None)

            responses = FakeResponses()
            generator = MultimodalGenerator(
                instructions="Seed instructions", provider="openai", model="gpt-5.6-luna",
                client=SimpleNamespace(responses=responses),
            )
            with patch.object(settings, "slides_dir", root):
                script = asyncio.run(_generate_multimodal_slide_script(
                    ["/static/slides/example/slide_000.png"], 0, pres_id, "Research talk", "", generator,
                ))

        self.assertEqual(script, "A concise opening.")
        request = responses.request
        self.assertEqual(request["model"], "gpt-5.6-luna")
        self.assertEqual(request["reasoning"], {"effort": "medium"})
        self.assertEqual(request["input"][0]["content"], "Seed instructions")
        blocks = request["input"][1]["content"]
        self.assertEqual(sum(block["type"] == "input_image" for block in blocks), 1)
        self.assertIn("Target speaking time: 30 seconds", "\n".join(
            block["text"] for block in blocks if block["type"] == "input_text"
        ))


if __name__ == "__main__":
    unittest.main()
