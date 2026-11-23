"""Offline checks for the read-only baseline review viewer."""

from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from evaluation.evaluator_schema import DIMENSION_NAMES, EvaluationResult
from evaluation.scoring import calculate_score
from experiments.baseline.viewer import create_app


class BaselineViewerTests(unittest.TestCase):
    def test_shows_recorded_prompt_images_script_and_dimension_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = root / "images"
            images.mkdir()
            for name in ("before.png", "target.png", "after.png"):
                (images / name).write_bytes(name.encode("utf-8"))
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"examples": [{
                "split": "baseline", "example_id": "deck_1_slide_0002", "deck_id": "deck_1",
                "slide_number": 2, "target_slide_image": "target.png",
                "preceding_slide_image": "before.png", "following_slide_image": "after.png",
                "target_duration_seconds": 30,
            }]}), encoding="utf-8")
            dimensions = {
                name: {
                    "applicable": name != "visual_reference",
                    "score": None if name == "visual_reference" else 4,
                    "rationale": "No meaningful visual" if name == "visual_reference" else "Good example",
                    "evidence": [], "problems": [], "improvement": "",
                }
                for name in DIMENSION_NAMES
            }
            evaluation = EvaluationResult.model_validate({
                "rubric_version": "1.1.0", "dimensions": dimensions,
            })
            prompt_fields = (
                "Presentation title: Not provided\nIntended audience: Researchers\n"
                "Target speaking time: 30 seconds\nTarget slide number: 2\n"
                "Speaker notes or raw script: Not provided\n"
                "Relevant paper or source excerpt: Not provided"
            )
            recorded_images = [
                {"type": "image", "path": str(images / name),
                 "sha256": hashlib.sha256(name.encode("utf-8")).hexdigest()}
                for name in ("before.png", "target.png", "after.png")
            ]
            results = root / "evaluations.jsonl"
            results.write_text(json.dumps({
                "example_id": "deck_1_slide_0002", "deck_id": "deck_1", "slide_number": 2,
                "candidate_sha256": "a" * 64,
                "position": "beginning", "script": "This slide introduces the question.",
                "evaluation": evaluation.model_dump(mode="json"),
                "score": calculate_score(evaluation),
                "request_audit": [{
                    "stage": "generation", "provider": "anthropic", "model": "claude-haiku-5-5",
                    "settings": {"output_config": {"effort": "medium"}},
                    "system_text": "Speak naturally.",
                    "user_content": [*recorded_images, {"type": "text", "text": prompt_fields}],
                }],
            }) + "\n", encoding="utf-8")

            with TestClient(create_app(results, manifest, images)) as client:
                listing = client.get("/api/examples")
                self.assertEqual(listing.status_code, 200)
                self.assertEqual(listing.json()["count"], 1)
                detail = client.get("/api/examples/deck_1_slide_0002")
                self.assertEqual(detail.status_code, 200)
                data = detail.json()
                self.assertEqual(data["script"], "This slide introduces the question.")
                self.assertEqual(data["generation"]["parameters"]["Intended audience"], "Researchers")
                self.assertEqual(data["generation"]["source"], "recorded request")
                self.assertEqual(data["generation"]["system_text"], "Speak naturally.")
                self.assertFalse(data["evaluation"]["dimensions"]["visual_reference"]["applicable"])
                self.assertEqual(client.get(data["images"]["target"]).content, b"target.png")
                self.assertEqual(client.get(data["images"]["preceding"]).content, b"before.png")
                self.assertEqual(client.get(data["images"]["following"]).content, b"after.png")
                self.assertEqual(client.get("/api/images/deck_1_slide_0002/unknown").status_code, 404)
                self.assertEqual(client.get("/api/images/unknown/target").status_code, 404)
                (images / "target.png").write_bytes(b"changed image")
                self.assertEqual(client.get(data["images"]["target"]).status_code, 409)
                self.assertEqual(client.get("/").status_code, 200)
                self.assertEqual(client.get("/assets/app.js").status_code, 200)

    def test_switches_runs_and_recovers_baseline_one_generator_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = root / "images"
            images.mkdir()
            target = images / "target.png"
            target.write_bytes(b"target image")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"examples": [{
                "split": "baseline", "example_id": "deck_slide_2", "deck_id": "deck",
                "slide_number": 2, "target_slide_image": "target.png",
            }]}), encoding="utf-8")
            evaluation = EvaluationResult.model_validate({
                "rubric_version": "1.1.0",
                "dimensions": {
                    name: {"applicable": True, "score": 4, "rationale": "Supported",
                           "evidence": [], "problems": [], "improvement": ""}
                    for name in DIMENSION_NAMES
                },
            })
            base = {
                "example_id": "deck_slide_2", "deck_id": "deck", "slide_number": 2,
                "candidate_sha256": "a" * 64, "evaluation": evaluation.model_dump(mode="json"),
                "score": calculate_score(evaluation),
            }
            generator = {
                "stage": "generation", "provider": "openai", "model": "gpt-5.6-luna",
                "settings": {"reasoning": {"effort": "medium"}},
                "system_text": "Ground in the slide.",
                "user_content": [
                    {"type": "image", "path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()},
                    {"type": "text", "text": (
                        "Presentation title: Not provided\nIntended audience: Not provided\n"
                        "Target speaking time: Not provided\nTarget slide number: 2\n"
                        "Speaker notes or raw script: Not provided\n"
                        "Relevant paper or source excerpt: Not provided"
                    )},
                ],
            }
            original = root / "original.jsonl"
            original.write_text(json.dumps({**base, "script": "Original script.",
                                            "request_audit": [generator]}) + "\n", encoding="utf-8")
            baseline1 = root / "baseline1.jsonl"
            baseline1.write_text(json.dumps({**base, "script": "Original script.",
                                             "request_audit": [{"stage": "evaluation", "model": "claude-haiku-5-5"}]}) + "\n", encoding="utf-8")
            baseline2 = root / "baseline2.jsonl"
            baseline2.write_text(json.dumps({**base, "script": "Swapped script.",
                                             "request_audit": [{"stage": "evaluation", "model": "gpt-5.6-luna"}]}) + "\n", encoding="utf-8")
            app = create_app(
                baseline2, manifest, images,
                baseline1_results_path=baseline1, baseline1_generation_path=original,
            )
            with TestClient(app) as client:
                runs = client.get("/api/runs").json()
                self.assertEqual({run["key"] for run in runs["runs"]}, {"baseline_1", "baseline_2"})
                self.assertEqual(runs["default_run"], "baseline_2")
                one = client.get("/api/examples/deck_slide_2?run=baseline_1").json()
                two = client.get("/api/examples/deck_slide_2?run=baseline_2").json()
                self.assertEqual(one["script"], "Original script.")
                self.assertEqual(one["generation"]["model"], "gpt-5.6-luna")
                self.assertEqual(one["generation"]["source"], "original generator request")
                self.assertEqual(one["evaluation_model"], "claude-haiku-5-5")
                self.assertEqual(two["script"], "Swapped script.")
                self.assertEqual(two["evaluation_model"], "gpt-5.6-luna")
                self.assertEqual(client.get(one["images"]["target"]).status_code, 200)
                self.assertEqual(client.get("/api/examples?run=unknown").status_code, 404)


if __name__ == "__main__":
    unittest.main()
