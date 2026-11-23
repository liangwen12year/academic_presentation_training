"""Multimodal speaker-script generation shared by experiments and the app.

This module only contacts a model when ``generate_script`` is called. Prompts
are kept in files so a GEPA-selected instruction can be loaded unchanged.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI


_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@dataclass(frozen=True, slots=True)
class SlideContext:
    """Evidence and presentation requirements for one target slide."""

    slide_number: int  # One-based.
    target_slide_image: Path
    preceding_slide_image: Path | None = None
    following_slide_image: Path | None = None
    presentation_title: str | None = None
    intended_audience: str | None = None
    target_duration_seconds: float | None = None
    speaker_notes: str | None = None
    source_excerpt: str | None = None


@dataclass(frozen=True, slots=True)
class ModelResult:
    text: str
    usage: dict[str, int]


def markdown_section(document: str, heading: str) -> str:
    """Extract a named level-two Markdown section, including its body only."""

    marker = f"## {heading}\n"
    if marker not in document:
        raise ValueError(f"Missing prompt section: {heading}")
    body = document.split(marker, 1)[1].split("\n## ", 1)[0].strip()
    if not body:
        raise ValueError(f"Empty prompt section: {heading}")
    return body


def load_generation_instructions(path: Path | str) -> str:
    """Load the system instruction from a seed file or a plain optimized prompt."""

    document = Path(path).read_text(encoding="utf-8").strip()
    if not document:
        raise ValueError(f"Empty generation prompt: {path}")
    if "## System instruction\n" in document:
        return markdown_section(document, "System instruction")
    return document


def image_content(path: Path) -> dict[str, str]:
    """Encode a local slide image as an OpenAI Responses image content block."""

    image = Path(path)
    mime = _MIME_TYPES.get(image.suffix.lower())
    if mime is None:
        raise ValueError(f"Unsupported slide image format: {image}")
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    return {
        "type": "input_image",
        "image_url": f"data:{mime};base64,{encoded}",
        "detail": "high",
    }


def _text(value: object | None) -> str:
    return str(value).strip() if value is not None and str(value).strip() else "Not provided"


def slide_content(slide: SlideContext, *, candidate_script: str | None = None) -> list[dict[str, str]]:
    """Build one user message with clearly labeled target and neighboring images."""

    if slide.slide_number < 1:
        raise ValueError("slide_number must be one-based and positive")

    content: list[dict[str, str]] = []
    for label, path in (
        ("Preceding slide image", slide.preceding_slide_image),
        ("Target slide image", slide.target_slide_image),
        ("Following slide image", slide.following_slide_image),
    ):
        content.append({"type": "input_text", "text": f"{label}:"})
        if path is None:
            if label == "Target slide image":
                raise ValueError("A target slide image is required")
            content.append({"type": "input_text", "text": "Not provided"})
        else:
            content.append(image_content(path))

    duration = (
        f"{slide.target_duration_seconds:g} seconds"
        if slide.target_duration_seconds is not None
        else "Not provided"
    )
    fields = (
        f"Presentation title: {_text(slide.presentation_title)}\n"
        f"Intended audience: {_text(slide.intended_audience)}\n"
        f"Target speaking time: {duration}\n"
        f"Target slide number: {slide.slide_number}\n"
        f"Speaker notes or raw script: {_text(slide.speaker_notes)}\n"
        f"Relevant paper or source excerpt: {_text(slide.source_excerpt)}"
    )
    content.append({"type": "input_text", "text": fields})
    if candidate_script is None:
        content.append({"type": "input_text", "text": "Write the speaker script for the target slide. Return only the words the speaker should say."})
    else:
        content.append({"type": "input_text", "text": f"Candidate speaker script to evaluate:\n{candidate_script}"})
    return content


def response_usage(response: Any) -> dict[str, int]:
    """Extract usage when the provider returns it; absence stays explicit."""

    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }


def generate_script(
    instructions: str,
    slide: SlideContext,
    *,
    client: OpenAI,
    model: str,
    max_output_tokens: int = 1600,
    reasoning_effort: str | None = None,
    request_hook: Callable[[dict[str, Any]], None] | None = None,
) -> ModelResult:
    """Call a multimodal model with the candidate system instruction."""

    if not instructions.strip():
        raise ValueError("Generation instructions cannot be empty")
    kwargs: dict[str, Any] = {}
    if reasoning_effort:
        kwargs["reasoning"] = {"effort": reasoning_effort}
    request: dict[str, Any] = {
        "model": model,
        "input": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": slide_content(slide)},
        ],
        "max_output_tokens": max_output_tokens,
        "store": False,
        **kwargs,
    }
    if request_hook is not None:
        request_hook(request)
    response = client.responses.create(**request)
    text = (response.output_text or "").strip()
    if not text:
        raise ValueError("Generation model returned no speaker script")
    return ModelResult(text=text, usage=response_usage(response))
