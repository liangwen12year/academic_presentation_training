"""Offline contracts for sampling, Claude evidence, and baseline summaries."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.speaker_scripts import SlideContext, generate_script
from evaluation.anthropic_evaluator import evaluate_script_claude
from evaluation.evaluator_schema import DIMENSION_NAMES, EvaluationResult
from evaluation.scoring import calculate_score
from experiments.baseline.evaluate_saved import completed_results, evaluate_saved_example, load_saved_scripts
from experiments.baseline.plot_results import read_results, summarize_distributions
from experiments.baseline.request_audit import summarize_request
from experiments.baseline.run_baseline import score_baseline_example, write_request_log
from experiments.baseline.select_arcbench import build_draft, proposed_pages
from experiments.gepa.prepare_pilot import _selection_decks
from experiments.gepa.dataset import SlideExample


def example_evaluation(*, low_grounding: bool = False) -> EvaluationResult:
    return EvaluationResult.model_validate({
        "rubric_version": "1.1.0",
        "dimensions": {
            name: {
                "applicable": True,
                "score": 1 if low_grounding and name == "grounding" else 4,
                "rationale": "Fixture",
                "evidence": ["The labeled chart"],
                "problems": [],
                "improvement": "",
            }
            for name in DIMENSION_NAMES
        },
    })


class BaselineExperimentTests(unittest.TestCase):
    def test_swapped_baseline_uses_claude_generation_and_openai_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "slide.png"
            image.write_bytes(b"image fixture")
            example = SlideExample(
                example_id="deck_1_slide_0002", deck_id="deck_1", slide_number=2,
                target_slide_image=image, position="beginning",
            )
            audits = []

            class FakeClaudeMessages:
                def create(self, **request):
                    self.request = request
                    return SimpleNamespace(
                        stop_reason="end_turn",
                        content=[SimpleNamespace(type="text", text="The chart compares two groups.")],
                        usage=SimpleNamespace(input_tokens=20, output_tokens=15),
                    )

            class FakeOpenAIResponses:
                def parse(self, **request):
                    self.request = request
                    return SimpleNamespace(
                        output_parsed=example_evaluation(),
                        usage=SimpleNamespace(input_tokens=30, output_tokens=100),
                    )

            claude = FakeClaudeMessages()
            openai = FakeOpenAIResponses()

            def capture(stage, request, slide):
                audit = summarize_request(stage=stage, example_id=example.example_id, slide=slide, request=request)
                write_request_log(root, audit)
                audits.append(audit)

            scored = score_baseline_example(
                example, generation_client=SimpleNamespace(messages=claude),
                evaluator_client=SimpleNamespace(responses=openai),
                generation_instructions="Speak naturally.",
                evaluator_instructions="Apply the rubric.",
                generation_max_output_tokens=1600, evaluator_max_output_tokens=8192,
                swap=True, request_audit=capture,
            )
            self.assertEqual(scored.script, "The chart compares two groups.")
            self.assertEqual(scored.score, 0.8)
            self.assertEqual([(a["stage"], a["provider"]) for a in audits], [
                ("generation", "anthropic"), ("evaluation", "openai"),
            ])
            self.assertEqual(claude.request["model"], "claude-haiku-5-5")
            self.assertEqual(claude.request["output_config"], {"effort": "medium"})
            self.assertEqual(openai.request["model"], "gpt-5.6-luna")
            self.assertEqual(openai.request["reasoning"], {"effort": "medium"})
            self.assertEqual(openai.request["text_format"], EvaluationResult)
            self.assertIn(scored.script, audits[1]["user_content"][-1]["text"])
            self.assertEqual(audits[1]["output_schema"]["name"], "EvaluationResult")
            self.assertTrue((root / "log/generator/deck_1_slide_0002.txt").is_file())
            self.assertTrue((root / "log/evaluator/deck_1_slide_0002.txt").is_file())

    def test_evaluation_only_reuses_script_and_can_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "slide.png"
            image.write_bytes(b"image fixture")
            example = SlideExample(
                example_id="deck_1_slide_0002", deck_id="deck_1", slide_number=2,
                target_slide_image=image, position="middle",
            )
            source = {
                "split": "baseline", "candidate_label": "seed_v1_multimodal",
                "candidate_sha256": "a" * 64,
                "example_id": example.example_id, "deck_id": example.deck_id,
                "slide_number": 2, "position": "middle", "slide_type": None,
                "script": "The chart compares two groups.",
                "evaluation": {"rubric_version": "1.0.0"},
            }
            source_path = root / "source.jsonl"
            source_path.write_text(json.dumps(source) + "\n", encoding="utf-8")
            loaded = load_saved_scripts(source_path, (example,))

            class FakeMessages:
                def parse(self, **request):
                    self.request = request
                    return SimpleNamespace(
                        stop_reason="end_turn", parsed_output=example_evaluation(),
                        usage=SimpleNamespace(input_tokens=20, output_tokens=30),
                    )

            messages = FakeMessages()
            scored, audit = evaluate_saved_example(
                example, loaded[0], client=SimpleNamespace(messages=messages),
                instructions="Use rubric 1.1.0.", model="claude-haiku-5-5",
                effort="medium", max_output_tokens=8192, output_dir=root,
            )
            self.assertEqual(scored.script, source["script"])
            self.assertEqual(scored.score, 0.8)
            self.assertIn(source["script"], messages.request["messages"][0]["content"][-1]["text"])
            self.assertTrue((root / "log/evaluator/deck_1_slide_0002.txt").is_file())
            self.assertFalse((root / "log/generator").exists())
            record = scored.to_record("baseline", source["candidate_label"])
            record["source_rubric_version"] = "1.0.0"
            record["request_audit"] = [audit]
            result_path = root / "evaluations.jsonl"
            result_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            self.assertEqual(len(completed_results(result_path, (example,), loaded)), 1)

    def test_draft_is_reproducible_without_slide_review(self) -> None:
        self.assertEqual(proposed_pages(5), {
            "beginning": 2,
            "middle": 3,
            "penultimate_page": 4,
        })
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for number in range(100):
                (root / f"slide{number}_example.pdf").write_bytes(b"PDF fixture")
            with patch("experiments.baseline.select_arcbench._page_count", return_value=10):
                first = build_draft(root, seed=7)
                second = build_draft(root, seed=7)
        self.assertEqual(first, second)
        self.assertEqual(len(first["decks"]), 30)
        self.assertEqual(len({deck["pdf"] for deck in first["decks"]}), 30)
        self.assertTrue(all(not deck["reviewed"] for deck in first["decks"]))
        self.assertTrue(all(len(deck["slides"]) == 3 for deck in first["decks"]))

    def test_claude_receives_labeled_images_and_structured_output_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "slide.png"
            image.write_bytes(b"image fixture")
            slide = SlideContext(slide_number=2, target_slide_image=image)
            log_file = Path(temporary) / "log/evaluator/example_2.txt"

            class FakeMessages:
                request = None

                def parse(self, **kwargs):
                    if not log_file.is_file():
                        raise AssertionError("Evaluator request was not logged before the SDK call")
                    self.request = kwargs
                    return SimpleNamespace(
                        stop_reason="end_turn",
                        parsed_output=example_evaluation(),
                        usage=SimpleNamespace(input_tokens=100, output_tokens=200),
                    )

            messages = FakeMessages()
            audited = []

            def capture_evaluation(request):
                audit = summarize_request(
                    stage="evaluation", example_id="example_2", slide=slide, request=request,
                )
                write_request_log(Path(temporary), audit)
                audited.append(audit)

            result = evaluate_script_claude(
                "The chart shows a labeled comparison.", slide,
                client=SimpleNamespace(messages=messages),
                instructions="Apply the seven-dimension rubric.",
                request_hook=capture_evaluation,
            )
            blocks = messages.request["messages"][0]["content"]
            self.assertEqual(messages.request["model"], "claude-haiku-5-5")
            self.assertEqual(messages.request["output_format"], EvaluationResult)
            self.assertEqual(messages.request["output_config"], {"effort": "medium"})
            self.assertEqual(sum(block["type"] == "image" for block in blocks), 1)
            self.assertIn("Target slide image:", [block.get("text") for block in blocks])
            self.assertEqual(result.usage["input_tokens"], 100)
            image_block = next(block for block in audited[0]["user_content"] if block["type"] == "image")
            self.assertEqual(image_block["path"], str(image.resolve()))
            self.assertIn("Candidate speaker script", audited[0]["user_content"][-1]["text"])
            self.assertEqual(audited[0]["output_schema"]["name"], "EvaluationResult")
            saved = json.loads((Path(temporary) / "log/evaluator/example_2.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["user_content"][-1]["text"], audited[0]["user_content"][-1]["text"])

    def test_generation_audit_preserves_text_and_hashes_attached_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "slide.png"
            image.write_bytes(b"image fixture")
            slide = SlideContext(slide_number=2, target_slide_image=image)
            log_file = Path(temporary) / "log/generator/example_2.txt"
            requests = []

            class FakeResponses:
                def create(self, **kwargs):
                    if not log_file.is_file():
                        raise AssertionError("Generator request was not logged before the SDK call")
                    requests.append(kwargs)
                    return SimpleNamespace(output_text="A short script.", usage=None)

            audited = []

            def capture_generation(request):
                audit = summarize_request(
                    stage="generation", example_id="example_2", slide=slide, request=request,
                )
                write_request_log(Path(temporary), audit)
                audited.append(audit)

            result = generate_script(
                "Ground every claim.", slide,
                client=SimpleNamespace(responses=FakeResponses()),
                model="gpt-5.6-luna", reasoning_effort="medium",
                request_hook=capture_generation,
            )
            self.assertEqual(result.text, "A short script.")
            self.assertEqual(audited[0]["system_text"], "Ground every claim.")
            self.assertEqual(audited[0]["settings"]["reasoning"], {"effort": "medium"})
            image_block = next(block for block in audited[0]["user_content"] if block["type"] == "image")
            self.assertEqual(image_block["path"], str(image.resolve()))
            self.assertNotIn("image_url", image_block)
            self.assertEqual(
                sum(block["type"] == "input_image" for block in requests[0]["input"][1]["content"]), 1,
            )
            text_log = (Path(temporary) / "log/generator/example_2.txt").read_text(encoding="utf-8")
            self.assertIn("Ground every claim.", text_log)
            self.assertIn("Target slide image:", text_log)

    def test_renderer_accepts_unreviewed_baseline_and_legacy_position_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "slide0_example.pdf").write_bytes(b"PDF fixture")
            selection = root / "selection.json"
            deck = {
                "deck_id": "arcbench_000",
                "pdf": "slide0_example.pdf",
                "split": "baseline",
                "page_count": 10,
                "reviewed": False,
                "slides": [
                    {"position": position, "slide_number": page, "slide_type": None}
                    for position, page in (
                        ("beginning", 2), ("middle", 5), ("penultimate_substantive", 9)
                    )
                ],
            }
            selection.write_text(json.dumps({"schema_version": "1.0.0", "decks": [deck]}), encoding="utf-8")
            with patch("experiments.gepa.prepare_pilot._page_count", return_value=10):
                parsed = _selection_decks(selection, root)
            self.assertEqual(parsed[0].slide_numbers, (2, 5, 9))
            self.assertEqual(len(parsed[0].slide_metadata), 3)
            self.assertEqual(parsed[0].slide_metadata[-1], (9, "penultimate_page", None))
            self.assertFalse(parsed[0].reviewed)

    def test_distributions_count_low_grounding_without_zero_override(self) -> None:
        rows = []
        for deck in range(30):
            for index, position in enumerate(("beginning", "middle", "penultimate_page")):
                low_grounding = deck == 0 and index == 0
                evaluation = example_evaluation(low_grounding=low_grounding)
                rows.append({
                    "split": "baseline",
                    "candidate_label": "seed_v1_multimodal",
                    "example_id": f"deck_{deck}_slide_{index}",
                    "deck_id": f"deck_{deck}",
                    "position": position,
                    "slide_type": None,
                    "score": calculate_score(evaluation),
                    "evaluation": evaluation.model_dump(mode="json"),
                })
        with tempfile.TemporaryDirectory() as temporary:
            result_file = Path(temporary) / "evaluations.jsonl"
            result_file.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            summary = summarize_distributions(read_results(result_file))
        self.assertEqual(summary["script_count"], 90)
        self.assertEqual(summary["aggregate_score_bins"]["[0.7, 0.8)"], 1)
        self.assertEqual(summary["aggregate_score_bins"]["[0.8, 0.9)"], 89)
        self.assertEqual(summary["dimension_rating_counts"]["grounding"]["1"], 1)
        self.assertEqual(summary["dimension_rating_counts"]["grounding"]["4"], 89)
        self.assertEqual(sum(summary["aggregate_score_bins"].values()), 90)


if __name__ == "__main__":
    unittest.main()
