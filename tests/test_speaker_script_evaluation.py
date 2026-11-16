"""Behavioral checks for evaluator validation and deterministic scoring."""

import unittest

from pydantic import ValidationError

from evaluation.evaluator_schema import DIMENSION_NAMES, EvaluationResult
from evaluation.scoring import calculate_score


def _result(*, score: int = 4, critical: bool = False) -> dict:
    return {
        "rubric_version": "1.0.0",
        "critical_grounding_error": {
            "present": critical,
            "claims": ["Invented a statistical result"] if critical else [],
        },
        "dimensions": {
            name: {
                "applicable": True,
                "score": score,
                "rationale": "Supported by the supplied slide",
                "evidence": ["Target slide"],
                "problems": [],
                "improvement": "",
            }
            for name in DIMENSION_NAMES
        },
    }


class SpeakerScriptEvaluationTests(unittest.TestCase):
    def test_normalized_score_and_optional_dimensions(self) -> None:
        data = _result(score=5)
        data["dimensions"]["visual_reference"].update(
            applicable=False, score=None, rationale="No meaningful visual"
        )
        data["dimensions"]["cross_slide_connection"].update(
            applicable=False, score=None, rationale="No neighboring slide"
        )
        data["dimensions"]["coherence"]["score"] = 1

        result = EvaluationResult.model_validate(data)

        self.assertAlmostEqual(calculate_score(result), 21 / 25)

    def test_critical_grounding_error_overrides_other_scores(self) -> None:
        result = EvaluationResult.model_validate(_result(score=5, critical=True))

        self.assertEqual(calculate_score(result), 0.0)

    def test_rejects_invalid_dimension(self) -> None:
        invalid_cases = (
            ("grounding", True, 0),
            ("grounding", True, 6),
            ("grounding", True, None),
            ("grounding", True, True),
            ("visual_reference", False, 3),
            ("grounding", False, None),
        )
        for dimension, applicable, score in invalid_cases:
            with self.subTest(dimension=dimension, applicable=applicable, score=score):
                data = _result()
                data["dimensions"][dimension]["applicable"] = applicable
                data["dimensions"][dimension]["score"] = score
                with self.assertRaises(ValidationError):
                    EvaluationResult.model_validate(data)

    def test_rejects_missing_dimension_and_extra_output_fields(self) -> None:
        missing = _result()
        missing["dimensions"].pop("coherence")
        with self.assertRaises(ValidationError):
            EvaluationResult.model_validate(missing)

        extra = _result()
        extra["selection_score"] = 0.8
        with self.assertRaises(ValidationError):
            EvaluationResult.model_validate(extra)

    def test_rejects_wrong_version_and_unexplained_critical_error(self) -> None:
        outdated = _result()
        outdated["rubric_version"] = "0.9.0"
        with self.assertRaises(ValidationError):
            EvaluationResult.model_validate(outdated)

        unexplained = _result(critical=True)
        unexplained["critical_grounding_error"]["claims"] = []
        with self.assertRaises(ValidationError):
            EvaluationResult.model_validate(unexplained)
