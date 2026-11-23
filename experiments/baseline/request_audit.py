"""Readable, size-bounded audit of the request passed to each model SDK.

System text and user text are preserved verbatim. Image payloads are replaced
by their local file paths and SHA-256 hashes so the audit does not duplicate
hundreds of megabytes of base64 data.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from app.speaker_scripts import SlideContext


def _image_bytes(block: dict[str, Any], provider: str) -> tuple[str, bytes, str | None]:
    if provider == "openai":
        prefix, separator, encoded = block["image_url"].partition(",")
        if not separator or not prefix.startswith("data:") or not prefix.endswith(";base64"):
            raise ValueError("Unexpected OpenAI image content")
        return prefix[5:-7], base64.b64decode(encoded, validate=True), block.get("detail")
    source = block["source"]
    if source["type"] != "base64":
        raise ValueError("Unexpected Claude image source")
    return source["media_type"], base64.b64decode(source["data"], validate=True), None


def summarize_request(
    *,
    stage: str,
    example_id: str,
    slide: SlideContext,
    request: dict[str, Any],
) -> dict[str, Any]:
    """Capture exactly the text and image bytes passed to the SDK call."""

    if stage not in {"generation", "evaluation"}:
        raise ValueError(f"Unknown request stage: {stage}")
    if "input" in request and "messages" not in request:
        provider = "openai"
        system_text = request["input"][0]["content"]
        raw_blocks = request["input"][1]["content"]
        settings = {
            "max_output_tokens": request["max_output_tokens"],
            "reasoning": request.get("reasoning"),
            "store": request.get("store"),
        }
        schema_type = request.get("text_format")
    elif "messages" in request and "input" not in request:
        provider = "anthropic"
        system_text = request["system"]
        raw_blocks = request["messages"][0]["content"]
        settings = {
            "max_tokens": request["max_tokens"],
            "output_config": request.get("output_config"),
        }
        schema_type = request.get("output_format")
    else:
        raise ValueError("Unknown request provider shape")
    output_schema = (
        {
            "name": schema_type.__name__,
            "sha256": hashlib.sha256(
                json.dumps(schema_type.model_json_schema(), sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }
        if schema_type is not None else None
    )

    image_paths = [
        path for path in (
            slide.preceding_slide_image,
            slide.target_slide_image,
            slide.following_slide_image,
        ) if path is not None
    ]
    image_index = 0
    user_content: list[dict[str, Any]] = []
    for block in raw_blocks:
        if block["type"] in {"input_text", "text"}:
            user_content.append({"type": "text", "text": block["text"]})
        elif block["type"] in {"input_image", "image"}:
            if image_index >= len(image_paths):
                raise ValueError("Request contains more images than the slide context")
            path = Path(image_paths[image_index])
            media_type, image, detail = _image_bytes(block, provider)
            if image != path.read_bytes():
                raise ValueError(f"Request image differs from slide file: {path}")
            entry: dict[str, Any] = {
                "type": "image",
                "path": str(path.resolve()),
                "media_type": media_type,
                "bytes": len(image),
                "sha256": hashlib.sha256(image).hexdigest(),
            }
            if detail is not None:
                entry["detail"] = detail
            user_content.append(entry)
            image_index += 1
        else:
            raise ValueError(f"Unexpected request content type: {block['type']}")
    if image_index != len(image_paths):
        raise ValueError("Request is missing a slide image")

    return {
        "example_id": example_id,
        "stage": stage,
        "provider": provider,
        "model": request["model"],
        "system_text": system_text,
        "system_sha256": hashlib.sha256(system_text.encode("utf-8")).hexdigest(),
        "user_content": user_content,
        "settings": settings,
        "output_schema": output_schema,
    }
