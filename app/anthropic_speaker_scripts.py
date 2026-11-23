"""Claude multimodal speaker-script generation using the shared slide context."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from anthropic import Anthropic

from app.speaker_scripts import ModelResult, SlideContext, slide_content


def claude_slide_content(slide: SlideContext, script: str | None = None) -> list[dict[str, Any]]:
    """Translate the shared labeled slide message into Claude content blocks."""

    content: list[dict[str, Any]] = []
    for block in slide_content(slide, candidate_script=script):
        if block["type"] == "input_text":
            content.append({"type": "text", "text": block["text"]})
        elif block["type"] == "input_image":
            prefix, separator, encoded = block["image_url"].partition(",")
            if not separator or not prefix.startswith("data:") or not prefix.endswith(";base64"):
                raise ValueError("Slide image is not a base64 data URL")
            media_type = prefix[5:-7]
            if media_type not in {"image/png", "image/jpeg", "image/webp"}:
                raise ValueError(f"Unsupported Claude image type: {media_type}")
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": encoded},
            })
        else:
            raise ValueError(f"Unsupported slide content block: {block['type']}")
    return content


def generate_script_claude(
    instructions: str,
    slide: SlideContext,
    *,
    client: Anthropic,
    model: str,
    max_output_tokens: int = 1600,
    effort: str = "medium",
    request_hook: Callable[[dict[str, Any]], None] | None = None,
) -> ModelResult:
    """Generate a script with Claude, preserving the exact request for audit."""

    if not instructions.strip():
        raise ValueError("Generation instructions cannot be empty")
    if max_output_tokens < 1:
        raise ValueError("max_output_tokens must be positive")
    request: dict[str, Any] = {
        "model": model,
        "system": instructions,
        "messages": [{"role": "user", "content": claude_slide_content(slide)}],
        "max_tokens": max_output_tokens,
        "output_config": {"effort": effort},
    }
    if request_hook is not None:
        request_hook(request)
    response = client.messages.create(**request)
    if response.stop_reason != "end_turn":
        raise ValueError(f"Claude did not return a complete speaker script: {response.stop_reason}")
    script = "\n".join(block.text for block in response.content if block.type == "text").strip()
    if not script:
        raise ValueError("Claude returned no speaker script")
    usage = {
        "input_tokens": int(response.usage.input_tokens),
        "output_tokens": int(response.usage.output_tokens),
        "cache_read_input_tokens": int(getattr(response.usage, "cache_read_input_tokens", 0) or 0),
        "cache_creation_input_tokens": int(getattr(response.usage, "cache_creation_input_tokens", 0) or 0),
    }
    return ModelResult(text=script, usage=usage)
