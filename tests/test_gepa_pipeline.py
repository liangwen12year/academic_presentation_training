"""Cross-module contract for image evidence, structured feedback, and GEPA score.

This test uses a fake Responses client. It never calls an API when run later.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from evaluation.evaluator_schema import DIMENSION_NAMES, EvaluationResult
from experiments.gepa.dataset import SlideExample
from experiments.gepa.pipeline import ModelSettings, score_example


class FakeResponses:
    def __init__(self, evaluation: EvaluationResult) -> None:
        self.evaluation = evaluation
        self.generation_input = None
        self.evaluation_input = None

    def create(self, **kwargs):
        self.generation_input = kwargs["input"]
        return SimpleNamespace(
            output_text="The chart's two labeled groups differ, which motivates the next step.",
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        )

    def parse(self, **kwargs):
        self.evaluation_input = kwargs["input"]
        return SimpleNamespace(
            output_parsed=self.evaluation,
            usage=SimpleNamespace(input_tokens=120, output_tokens=60),
        )


def example_evaluation() -> EvaluationResult:
    return EvaluationResult.model_validate(
        {
            "rubric_version": "1.1.0",
            "dimensions": {
                name: {
                    "applicable": True,
                    "score": 4,
                    "rationale": "A model judgment for this fixture",
                    "evidence": ["Target slide"],
                    "problems": ["Check the trend claim"],
                    "improvement": "Describe only the labeled groups",
                }
                for name in DIMENSION_NAMES
            },
        }
    )


class GepaPipelineTests(unittest.TestCase):
    def test_same_labeled_images_reach_generation_and_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = [root / f"slide_{number}.png" for number in (1, 2, 3)]
            for image in images:
                image.write_bytes(b"image fixture")

            example = SlideExample(
                example_id="deck-a-slide-2",
                deck_id="deck-a",
                slide_number=2,
                preceding_slide_image=images[0],
                target_slide_image=images[1],
                following_slide_image=images[2],
                speaker_notes="The experiment compares two groups.",
            )
            responses = FakeResponses(example_evaluation())
            client = SimpleNamespace(responses=responses)
            scored = score_example(
                "Write a grounded script.",
                example,
                client=client,
                settings=ModelSettings(
                    generation_model="fake-generation",
                    evaluator_model="fake-evaluator",
                    evaluator_instructions="Score from images and notes.",
                ),
            )

            self.assertEqual(scored.score, 0.8)
            self.assertEqual(scored.generation_usage["input_tokens"], 100)
            self.assertEqual(scored.feedback_for_gepa()["dimensions"]["grounding"]["score"], 4)
            for request in (responses.generation_input, responses.evaluation_input):
                self.assertIsNotNone(request)
                user_content = request[1]["content"]
                self.assertEqual(
                    [block["text"] for block in user_content if block["type"] == "input_text"][:3],
                    ["Preceding slide image:", "Target slide image:", "Following slide image:"],
                )
                self.assertEqual(sum(block["type"] == "input_image" for block in user_content), 3)
                self.assertIn("The experiment compares two groups.", user_content[-2]["text"])
            self.assertIn("Candidate speaker script", responses.evaluation_input[1]["content"][-1]["text"])


if __name__ == "__main__":
    unittest.main()
