"""Multimodal rubric evaluation with validated structured output."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.speaker_scripts import SlideContext, markdown_section, response_usage, slide_content
from evaluation.evaluator_schema import EvaluationResult


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    result: EvaluationResult
    usage: dict[str, int]


def load_evaluator_instructions(prompt_path: Path | str, rubric_path: Path | str) -> str:
    """Assemble every fixed evaluator rule into the system message.

    The Markdown document also describes a user template and example JSON. Its
    headings are documentation; this loader explicitly selects the system
    instruction, procedure, and output rules, then inserts the real YAML rubric.
    """

    document = Path(prompt_path).read_text(encoding="utf-8")
    rubric = Path(rubric_path).read_text(encoding="utf-8").strip()
    if not rubric:
        raise ValueError(f"Empty evaluation rubric: {rubric_path}")

    system = markdown_section(document, "System instruction")
    placeholder = "{contents_of_evaluation/speaker_script_rubric.yaml}"
    if placeholder not in system:
        raise ValueError("Evaluator system instruction lacks the rubric placeholder")
    system = system.replace(placeholder, rubric)
    procedure = markdown_section(document, "Required evaluation procedure")
    output_section = markdown_section(document, "Output schema")
    output_rules = output_section.split("```", 1)[0].strip()
    applicability_rules = (
        "For a non-applicable dimension, set applicable to false and score to null, "
        "and explain why in rationale. Only visual_reference and "
        "cross_slide_connection may be non-applicable. "
        "For every applicable dimension, set applicable to true and score to an "
        "integer from 1 to 5. Include all seven dimensions and no derived score."
    )
    return (
        f"{system}\n\nEvaluation procedure:\n{procedure}\n\n"
        f"Output rules:\n{output_rules}\n{applicability_rules}"
    )


def evaluate_script(
    script: str,
    slide: SlideContext,
    *,
    client: OpenAI,
    model: str,
    instructions: str,
    max_output_tokens: int = 5000,
    reasoning_effort: str | None = None,
) -> EvaluationRun:
    """Score the candidate script using target and neighboring slide images."""

    if not script.strip():
        raise ValueError("Cannot evaluate an empty speaker script")
    kwargs: dict[str, Any] = {}
    if reasoning_effort:
        kwargs["reasoning"] = {"effort": reasoning_effort}
    response = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": slide_content(slide, candidate_script=script)},
        ],
        text_format=EvaluationResult,
        max_output_tokens=max_output_tokens,
        store=False,
        **kwargs,
    )
    if response.output_parsed is None:
        raise ValueError("Evaluator returned no parsed JSON result")
    return EvaluationRun(result=response.output_parsed, usage=response_usage(response))
