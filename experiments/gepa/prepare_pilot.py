"""Render explicitly selected PDF pages for a GEPA pilot or fixed baseline.

This command is intentionally opt-in. It reads ``example_selection.json`` (or
another selection file), validates every deck and one-based page number, then
renders selected target pages and their immediate neighbors at 200 DPI. The
output contains ``images/`` and a ``manifest.json`` accepted by
``load_manifest(manifest_path, image_root)`` in ``dataset.py``.

Example, from the repository root::

    python -m experiments.gepa.prepare_pilot \
        --selection experiments/gepa/example_selection.json \
        --output-root data/gepa/pilot

Baseline selections carry page-position metadata; manual review and slide-type
labels are optional. The command does not call any model API. It requires Poppler's ``pdfinfo`` and
``pdftoppm`` executables and refuses to overwrite an existing output directory.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from experiments.gepa.dataset import load_manifest

_DECK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_SPLITS = {"train", "val", "test", "baseline"}
_BASELINE_POSITIONS = {"beginning", "middle", "penultimate_page", "penultimate_substantive"}
_SLIDE_TYPES = {"text", "chart", "table", "diagram", "equation", "image", "mixed", "other"}
_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SOURCE = _ROOT / "data" / "slides" / "arcbench" / "slides"
_DEFAULT_SELECTION = _ROOT / "experiments" / "gepa" / "example_selection.json"
_ALLOWED_OUTPUT_ROOT = _ROOT / "data" / "gepa"
_DEFAULT_OUTPUT = _ALLOWED_OUTPUT_ROOT / "pilot"


@dataclass(frozen=True, slots=True)
class SelectedDeck:
    deck_id: str
    pdf_path: Path
    split: str
    slide_numbers: tuple[int, ...]
    page_count: int
    presentation_title: str | None
    intended_audience: str | None
    target_duration_seconds: float | None
    slide_metadata: tuple[tuple[int, str, str | None], ...]
    reviewed: bool


def _optional_text(value: object, field: str, deck_id: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Deck {deck_id}: {field} must be text or null")
    return value.strip() or None


def _page_count(pdf_path: Path) -> int:
    try:
        result = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("pdfinfo is required to validate PDF page numbers") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"pdfinfo failed for {pdf_path}: {exc.stderr.strip()}") from exc

    match = re.search(r"^Pages:\s*(\d+)\s*$", result.stdout, re.MULTILINE)
    if match is None or int(match.group(1)) < 1:
        raise ValueError(f"Could not read a positive page count from {pdf_path}")
    return int(match.group(1))


def _selection_decks(selection_path: Path, source_root: Path) -> tuple[SelectedDeck, ...]:
    source_root = source_root.resolve()
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if not isinstance(selection, dict) or not isinstance(selection.get("decks"), list):
        raise ValueError("Selection must be a JSON object with a decks array")
    if selection.get("schema_version") != "1.0.0":
        raise ValueError("Selection schema_version must be 1.0.0")

    decks: list[SelectedDeck] = []
    seen_deck_ids: set[str] = set()
    seen_pdfs: set[Path] = set()
    for row, raw_deck in enumerate(selection["decks"], start=1):
        if not isinstance(raw_deck, dict):
            raise ValueError(f"Deck {row} must be a JSON object")
        deck_id = raw_deck.get("deck_id")
        if not isinstance(deck_id, str) or _DECK_ID.fullmatch(deck_id) is None:
            raise ValueError(f"Deck {row}: deck_id must contain only letters, digits, _ or -")
        if deck_id in seen_deck_ids:
            raise ValueError(f"Duplicate deck_id: {deck_id}")

        split = raw_deck.get("split")
        if split not in _SPLITS:
            raise ValueError(f"Deck {deck_id}: split must be train, val, test, or baseline")

        pdf_name = raw_deck.get("pdf")
        if not isinstance(pdf_name, str) or not pdf_name.strip():
            raise ValueError(f"Deck {deck_id}: pdf must be a relative PDF path")
        relative_path = Path(pdf_name)
        if relative_path.is_absolute():
            raise ValueError(f"Deck {deck_id}: pdf must be relative to source_root")
        pdf_path = (source_root / relative_path).resolve()
        if not pdf_path.is_relative_to(source_root):
            raise ValueError(f"Deck {deck_id}: pdf leaves source_root")
        if pdf_path.suffix.lower() != ".pdf" or not pdf_path.is_file():
            raise FileNotFoundError(f"Deck {deck_id}: PDF not found: {pdf_path}")
        if pdf_path in seen_pdfs:
            raise ValueError(f"PDF selected more than once: {pdf_path}")

        raw_selected_slides = raw_deck.get("slides")
        slide_metadata: tuple[tuple[int, str, str], ...] = ()
        reviewed = raw_deck.get("reviewed") is True
        if split == "baseline":
            if not isinstance(raw_selected_slides, list) or len(raw_selected_slides) != 3:
                raise ValueError(f"Deck {deck_id}: baseline requires exactly three selected slides")
            if raw_deck.get("slide_numbers") is not None:
                raise ValueError(f"Deck {deck_id}: use slides, not slide_numbers, for baseline")
            metadata: list[tuple[int, str, str | None]] = []
            for raw_slide in raw_selected_slides:
                if not isinstance(raw_slide, dict):
                    raise ValueError(f"Deck {deck_id}: each slide must be an object")
                position = raw_slide.get("position")
                slide_type = raw_slide.get("slide_type")
                if not isinstance(position, str) or position not in _BASELINE_POSITIONS:
                    raise ValueError(f"Deck {deck_id}: invalid baseline position: {position}")
                if slide_type is not None and (not isinstance(slide_type, str) or slide_type not in _SLIDE_TYPES):
                    raise ValueError(f"Deck {deck_id}: invalid slide_type: {slide_type}")
                if position == "penultimate_substantive":
                    position = "penultimate_page"  # Accept selection drafts made before review became optional.
                metadata.append((raw_slide.get("slide_number"), position, slide_type))
            if {position for _, position, _ in metadata} != {"beginning", "middle", "penultimate_page"}:
                raise ValueError(f"Deck {deck_id}: one slide is required for each position")
            slide_metadata = tuple(metadata)
            raw_pages = [page for page, _, _ in metadata]
        else:
            if raw_selected_slides is not None:
                raise ValueError(f"Deck {deck_id}: slides metadata is only supported for baseline")
            raw_pages = raw_deck.get("slide_numbers")
        if not isinstance(raw_pages, list) or not raw_pages:
            raise ValueError(f"Deck {deck_id}: slide_numbers must be a nonempty array")
        if any(isinstance(page, bool) or not isinstance(page, int) or page < 1 for page in raw_pages):
            raise ValueError(f"Deck {deck_id}: slide_numbers must contain positive integers")
        if len(set(raw_pages)) != len(raw_pages):
            raise ValueError(f"Deck {deck_id}: slide_numbers contains duplicate pages")
        if split == "baseline":
            by_position = {position: page for page, position, _ in slide_metadata}
            if not (
                by_position["beginning"]
                < by_position["middle"]
                < by_position["penultimate_page"]
            ):
                raise ValueError(f"Deck {deck_id}: baseline positions must follow page order")
        page_count = _page_count(pdf_path)
        declared_page_count = raw_deck.get("page_count")
        if declared_page_count is not None and declared_page_count != page_count:
            raise ValueError(f"Deck {deck_id}: PDF page count changed since selection")
        if any(page > page_count for page in raw_pages):
            raise ValueError(f"Deck {deck_id}: page number exceeds PDF's {page_count} pages")

        duration = raw_deck.get("target_duration_seconds")
        if duration is not None:
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 < duration < float("inf"):
                raise ValueError(f"Deck {deck_id}: target_duration_seconds must be positive and finite")
            duration = float(duration)

        decks.append(
            SelectedDeck(
                deck_id=deck_id,
                pdf_path=pdf_path,
                split=split,
                slide_numbers=tuple(sorted(raw_pages)),
                page_count=page_count,
                presentation_title=_optional_text(raw_deck.get("presentation_title"), "presentation_title", deck_id),
                intended_audience=_optional_text(raw_deck.get("intended_audience"), "intended_audience", deck_id),
                target_duration_seconds=duration,
                slide_metadata=slide_metadata,
                reviewed=reviewed,
            )
        )
        seen_deck_ids.add(deck_id)
        seen_pdfs.add(pdf_path)

    if not decks:
        raise ValueError("Selection contains no decks")
    return tuple(decks)


def _render_page(pdf_path: Path, page_number: int, output_prefix: Path) -> None:
    try:
        subprocess.run(
            [
                "pdftoppm", "-f", str(page_number), "-l", str(page_number),
                "-r", "200", "-png", "-singlefile", str(pdf_path), str(output_prefix),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("pdftoppm is required to render slide images") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Could not render page {page_number} of {pdf_path}: {exc.stderr.strip()}") from exc
    if not output_prefix.with_suffix(".png").is_file():
        raise RuntimeError(f"No PNG was produced for page {page_number} of {pdf_path}")


def prepare_pilot(selection_path: Path, source_root: Path, output_root: Path) -> Path:
    """Validate, render selected pages, and write a loader-compatible manifest."""

    source_root = source_root.resolve()
    output_root = output_root.resolve()
    allowed_root = _ALLOWED_OUTPUT_ROOT.resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"source_root does not exist: {source_root}")
    if output_root == allowed_root or not output_root.is_relative_to(allowed_root):
        raise ValueError(f"output_root must be a child of {allowed_root}")
    if output_root.exists():
        raise FileExistsError(f"output_root already exists; choose a new path: {output_root}")

    decks = _selection_decks(selection_path, source_root)
    output_images = output_root / "images"
    output_images.mkdir(parents=True)

    examples: list[dict] = []
    for deck in decks:
        deck_dir = output_images / deck.deck_id
        deck_dir.mkdir()
        metadata_by_page = {
            page: (position, slide_type)
            for page, position, slide_type in deck.slide_metadata
        }
        needed_pages = {
            neighbor
            for page in deck.slide_numbers
            for neighbor in (page - 1, page, page + 1)
            if 1 <= neighbor <= deck.page_count
        }
        for page in sorted(needed_pages):
            _render_page(deck.pdf_path, page, deck_dir / f"slide_{page:04d}")

        def relative_image(page: int) -> str:
            return f"{deck.deck_id}/slide_{page:04d}.png"

        for page in deck.slide_numbers:
            example = {
                "split": deck.split,
                "example_id": f"{deck.deck_id}_slide_{page:04d}",
                "deck_id": deck.deck_id,
                "slide_number": page,
                "target_slide_image": relative_image(page),
                "preceding_slide_image": relative_image(page - 1) if page > 1 else None,
                "following_slide_image": relative_image(page + 1) if page < deck.page_count else None,
                "presentation_title": deck.presentation_title,
                "intended_audience": deck.intended_audience,
                "target_duration_seconds": deck.target_duration_seconds,
                "position": metadata_by_page.get(page, (None, None))[0],
                "slide_type": metadata_by_page.get(page, (None, None))[1],
                "source_pdf": str(deck.pdf_path.relative_to(source_root)),
                "source_page_count": deck.page_count,
            }
            examples.append(example)

    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps({
            "schema_version": "1.0.0",
            "render_dpi": 200,
            "selection_reviewed": all(deck.reviewed for deck in decks),
            "examples": examples,
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    load_manifest(manifest_path, output_images)
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=_DEFAULT_SELECTION)
    parser.add_argument("--source-root", type=Path, default=_DEFAULT_SOURCE)
    parser.add_argument("--output-root", type=Path, default=_DEFAULT_OUTPUT)
    args = parser.parse_args()
    path = prepare_pilot(args.selection, args.source_root, args.output_root)
    print(f"Prepared pilot manifest: {path}")


if __name__ == "__main__":
    main()
