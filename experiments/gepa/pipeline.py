"""Shared generation and rubric evaluation for the pilot and GEPA.

All model calls are inside ``score_example``. Merely importing this module or
loading a manifest never contacts a model provider.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable

from openai import OpenAI

from app.speaker_scripts import SlideContext, generate_script
from evaluation.evaluator_schema import DIMENSION_NAMES, EvaluationResult
from evaluation.run_evaluator import evaluate_script
from evaluation.scoring import calculate_score
from experiments.gepa.dataset import SlideExample


@dataclass(frozen=True, slots=True)
class ModelSettings:
    generation_model: str
    evaluator_model: str
    evaluator_instructions: str
    generation_max_output_tokens: int = 1600
    evaluator_max_output_tokens: int = 5000
    generation_reasoning_effort: str | None = None
    evaluator_reasoning_effort: str | None = None


@dataclass(frozen=True, slots=True)
class ScoredExample:
    example_id: str
    deck_id: str
    slide_number: int
    candidate_sha256: str
    script: str
    evaluation: EvaluationResult
    score: float
    generation_usage: dict[str, int]
    evaluator_usage: dict[str, int]

    def to_record(self, split: str, candidate_label: str) -> dict:
        return {
            "split": split,
            "candidate_label": candidate_label,
            "candidate_sha256": self.candidate_sha256,
            "example_id": self.example_id,
            "deck_id": self.deck_id,
            "slide_number": self.slide_number,
            "script": self.script,
            "evaluation": self.evaluation.model_dump(mode="json"),
            "score": self.score,
            "generation_usage": self.generation_usage,
            "evaluator_usage": self.evaluator_usage,
        }

    def feedback_for_gepa(self) -> dict:
        """Keep concrete evaluator feedback available to GEPA's reflector."""

        dimensions = {
            name: {
                "score": getattr(self.evaluation.dimensions, name).score,
                "applicable": getattr(self.evaluation.dimensions, name).applicable,
                "rationale": getattr(self.evaluation.dimensions, name).rationale,
                "evidence": getattr(self.evaluation.dimensions, name).evidence,
                "problems": getattr(self.evaluation.dimensions, name).problems,
                "improvement": getattr(self.evaluation.dimensions, name).improvement,
            }
            for name in DIMENSION_NAMES
        }
        return {
            "example_id": self.example_id,
            "slide_number": self.slide_number,
            "speaker_script": self.script,
            "critical_grounding_error": self.evaluation.critical_grounding_error.model_dump(mode="json"),
            "dimensions": dimensions,
        }


def as_slide_context(example: SlideExample) -> SlideContext:
    return SlideContext(
        slide_number=example.slide_number,
        target_slide_image=example.target_slide_image,
        preceding_slide_image=example.preceding_slide_image,
        following_slide_image=example.following_slide_image,
        presentation_title=example.presentation_title,
        intended_audience=example.intended_audience,
        target_duration_seconds=example.target_duration_seconds,
        speaker_notes=example.speaker_notes,
        source_excerpt=example.source_excerpt,
    )


def score_example(
    candidate_prompt: str,
    example: SlideExample,
    *,
    client: OpenAI,
    settings: ModelSettings,
) -> ScoredExample:
    """Generate once, evaluate once, and compute the fixed scalar score.

    Provider errors are deliberately raised. They must not turn into apparent
    quality failures with a zero score during optimization.
    """

    slide = as_slide_context(example)
    generated = generate_script(
        candidate_prompt,
        slide,
        client=client,
        model=settings.generation_model,
        max_output_tokens=settings.generation_max_output_tokens,
        reasoning_effort=settings.generation_reasoning_effort,
    )
    evaluated = evaluate_script(
        generated.text,
        slide,
        client=client,
        model=settings.evaluator_model,
        instructions=settings.evaluator_instructions,
        max_output_tokens=settings.evaluator_max_output_tokens,
        reasoning_effort=settings.evaluator_reasoning_effort,
    )
    return ScoredExample(
        example_id=example.example_id,
        deck_id=example.deck_id,
        slide_number=example.slide_number,
        candidate_sha256=hashlib.sha256(candidate_prompt.encode("utf-8")).hexdigest(),
        script=generated.text,
        evaluation=evaluated.result,
        score=calculate_score(evaluated.result),
        generation_usage=generated.usage,
        evaluator_usage=evaluated.usage,
    )


def evaluate_set(
    candidate_prompt: str,
    examples: Iterable[SlideExample],
    *,
    client: OpenAI,
    settings: ModelSettings,
    records_path: Path,
    split: str,
    candidate_label: str,
) -> list[ScoredExample]:
    """Evaluate every example and append records as each one completes."""

    results: list[ScoredExample] = []
    records_path.parent.mkdir(parents=True, exist_ok=True)
    with records_path.open("a", encoding="utf-8") as stream:
        for example in examples:
            scored = score_example(candidate_prompt, example, client=client, settings=settings)
            stream.write(json.dumps(scored.to_record(split, candidate_label), ensure_ascii=False) + "\n")
            stream.flush()
            results.append(scored)
    return results


def summarize(results: list[ScoredExample]) -> dict:
    """Aggregate scores, critical errors, dimension means, and token usage."""

    if not results:
        raise ValueError("Cannot summarize an empty evaluation set")
    dimension_means = {}
    for name in DIMENSION_NAMES:
        values = [
            dimension.score
            for result in results
            if (dimension := getattr(result.evaluation.dimensions, name)).applicable
            and dimension.score is not None
        ]
        dimension_means[name] = mean(values) if values else None

    def token_total(usage_field: str, token_field: str) -> int | None:
        usages = [getattr(result, usage_field) for result in results]
        if any(token_field not in usage for usage in usages):
            return None
        return sum(usage[token_field] for usage in usages)

    return {
        "n": len(results),
        "mean_score": mean(result.score for result in results),
        "critical_grounding_error_count": sum(
            result.evaluation.critical_grounding_error.present for result in results
        ),
        "dimension_means_1_to_5": dimension_means,
        "generation_input_tokens": token_total("generation_usage", "input_tokens"),
        "generation_output_tokens": token_total("generation_usage", "output_tokens"),
        "evaluator_input_tokens": token_total("evaluator_usage", "input_tokens"),
        "evaluator_output_tokens": token_total("evaluator_usage", "output_tokens"),
    }
