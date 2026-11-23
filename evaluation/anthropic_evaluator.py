"""Claude evaluator for the fixed speaker-script rubric."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from anthropic import Anthropic

from app.anthropic_speaker_scripts import claude_slide_content
from app.speaker_scripts import SlideContext
from evaluation.evaluator_schema import EvaluationResult
from evaluation.run_evaluator import EvaluationRun


def evaluate_script_claude(
    script: str,
    slide: SlideContext,
    *,
    client: Anthropic,
    instructions: str,
    model: str = "claude-haiku-5-5",
    max_output_tokens: int = 8192,
    effort: str = "medium",
    request_hook: Callable[[dict[str, Any]], None] | None = None,
) -> EvaluationRun:
    """Return seven validated judgments; provider failures propagate to caller."""

    if not script.strip():
        raise ValueError("Cannot evaluate an empty speaker script")
    if max_output_tokens < 1:
        raise ValueError("max_output_tokens must be positive")
    request: dict[str, Any] = {
        "model": model,
        "system": instructions,
        "messages": [{"role": "user", "content": claude_slide_content(slide, script)}],
        "max_tokens": max_output_tokens,
        "output_format": EvaluationResult,
        "output_config": {"effort": effort},
    }
    if request_hook is not None:
        request_hook(request)
    response = client.messages.parse(**request)
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise ValueError(f"Claude did not return a complete parsed evaluation: {response.stop_reason}")
    usage = {
        "input_tokens": int(response.usage.input_tokens),
        "output_tokens": int(response.usage.output_tokens),
        "cache_read_input_tokens": int(getattr(response.usage, "cache_read_input_tokens", 0) or 0),
        "cache_creation_input_tokens": int(getattr(response.usage, "cache_creation_input_tokens", 0) or 0),
    }
    return EvaluationRun(result=response.parsed_output, usage=usage)
