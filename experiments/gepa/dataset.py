"""Read and validate a local, deck-split manifest of rendered slide images.

The manifest is JSON with an ``examples`` array. Each example has a ``split``
(``train``, ``val``, or ``test``), ``example_id``, ``deck_id``, a one-based
``slide_number``, and ``target_slide_image``. Image paths are relative to the
explicit ``image_root`` argument. Optional fields are listed in ``SlideExample``.

This module only reads a manifest and checks image paths. Rendering is a
separate preparation step; importing this module does not render slides or
contact a model provider.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SplitName = Literal["train", "val", "test"]
_SPLITS: tuple[SplitName, ...] = ("train", "val", "test")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True, slots=True)
class SlideExample:
    """One target slide and the available evidence for its speaker script."""

    example_id: str
    deck_id: str
    slide_number: int  # One-based page number within the deck.
    target_slide_image: Path
    preceding_slide_image: Path | None = None
    following_slide_image: Path | None = None
    presentation_title: str | None = None
    intended_audience: str | None = None
    target_duration_seconds: float | None = None
    speaker_notes: str | None = None
    source_excerpt: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetSplits:
    """Examples partitioned by deck for optimization and final comparison."""

    train: tuple[SlideExample, ...]
    val: tuple[SlideExample, ...]
    test: tuple[SlideExample, ...]


def _required_text(record: dict, key: str, row: int) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Example {row}: {key} must be nonempty text")
    return value.strip()


def _optional_text(record: dict, key: str, row: int) -> str | None:
    value = record.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Example {row}: {key} must be text or null")
    return value.strip() or None


def _image_path(record: dict, key: str, row: int, root: Path, required: bool) -> Path | None:
    value = record.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Example {row}: {key} must be a relative image path")
    relative_path = Path(value)
    if relative_path.is_absolute():
        raise ValueError(f"Example {row}: {key} must be relative to image_root")
    image_path = (root / relative_path).resolve()
    if not image_path.is_relative_to(root):
        raise ValueError(f"Example {row}: {key} leaves image_root")
    if image_path.suffix.lower() not in _IMAGE_SUFFIXES:
        raise ValueError(f"Example {row}: {key} must point to a PNG, JPEG, or WebP image")
    if not image_path.is_file():
        raise FileNotFoundError(f"Example {row}: {key} image is missing: {image_path}")
    return image_path


def _read_example(record: dict, row: int, root: Path) -> SlideExample:
    slide_number = record.get("slide_number")
    if isinstance(slide_number, bool) or not isinstance(slide_number, int) or slide_number < 1:
        raise ValueError(f"Example {row}: slide_number must be a positive integer (one-based)")

    duration = record.get("target_duration_seconds")
    if duration is not None:
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 < duration < float("inf"):
            raise ValueError(f"Example {row}: target_duration_seconds must be positive and finite")
        duration = float(duration)

    target = _image_path(record, "target_slide_image", row, root, required=True)
    assert target is not None  # The required-path branch above has already checked this.
    return SlideExample(
        example_id=_required_text(record, "example_id", row),
        deck_id=_required_text(record, "deck_id", row),
        slide_number=slide_number,
        target_slide_image=target,
        preceding_slide_image=_image_path(record, "preceding_slide_image", row, root, required=False),
        following_slide_image=_image_path(record, "following_slide_image", row, root, required=False),
        presentation_title=_optional_text(record, "presentation_title", row),
        intended_audience=_optional_text(record, "intended_audience", row),
        target_duration_seconds=duration,
        speaker_notes=_optional_text(record, "speaker_notes", row),
        source_excerpt=_optional_text(record, "source_excerpt", row),
    )


def load_manifest(manifest_path: Path | str, image_root: Path | str) -> DatasetSplits:
    """Load local examples and reject duplicate targets or deck split leakage.

    Relative ``image_root`` paths are interpreted from the current working
    directory. All image paths inside the manifest are relative to that root.
    Neither rendered slides nor a manifest are created by this function.
    """

    manifest = Path(manifest_path)
    root = Path(image_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"image_root does not exist: {root}")

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("examples"), list):
        raise ValueError("Manifest must be a JSON object with an examples array")

    split_lists: dict[str, list[SlideExample]] = {name: [] for name in _SPLITS}
    seen_ids: set[str] = set()
    seen_target_images: set[Path] = set()
    seen_deck_slides: set[tuple[str, int]] = set()
    deck_splits: dict[str, SplitName] = {}

    for row, item in enumerate(payload["examples"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Example {row} must be a JSON object")
        split = item.get("split")
        if split not in _SPLITS:
            raise ValueError(f"Example {row}: split must be train, val, or test")
        example = _read_example(item, row, root)
        if example.example_id in seen_ids:
            raise ValueError(f"Duplicate example_id: {example.example_id}")
        if example.target_slide_image in seen_target_images:
            raise ValueError(f"Duplicate target slide image: {example.target_slide_image}")
        deck_slide = (example.deck_id, example.slide_number)
        if deck_slide in seen_deck_slides:
            raise ValueError(f"Duplicate deck slide: {example.deck_id}, {example.slide_number}")
        previous_split = deck_splits.get(example.deck_id)
        if previous_split is not None and previous_split != split:
            raise ValueError(f"Deck {example.deck_id!r} appears in both {previous_split} and {split}")

        seen_ids.add(example.example_id)
        seen_target_images.add(example.target_slide_image)
        seen_deck_slides.add(deck_slide)
        deck_splits[example.deck_id] = split
        split_lists[split].append(example)

    if not seen_ids:
        raise ValueError("Manifest contains no examples")
    return DatasetSplits(
        train=tuple(split_lists["train"]),
        val=tuple(split_lists["val"]),
        test=tuple(split_lists["test"]),
    )
