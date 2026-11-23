"""Select 30 ArcBench decks and three page positions per deck; no model calls.

The positional sample can be rendered without manual review. Review and slide
type labels remain optional metadata for later analysis.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

from experiments.gepa.prepare_pilot import _page_count

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "data/slides/arcbench/slides"
DEFAULT_OUTPUT = ROOT / "data/gepa/baseline_selection_draft.json"
_FILE_ID = re.compile(r"^slide(\d+)_")


def proposed_pages(page_count: int) -> dict[str, int]:
    """Use page 2, the midpoint, and the penultimate PDF page."""

    if page_count < 5:
        raise ValueError("At least five pages are needed for three distinct candidates")
    pages = {
        "beginning": 2,
        "middle": (page_count + 1) // 2,
        "penultimate_page": page_count - 1,
    }
    if len(set(pages.values())) != 3:
        raise ValueError(f"Proposed pages are not distinct: {pages}")
    return pages


def build_draft(source_root: Path, *, seed: int = 33, expected_pdfs: int = 100) -> dict:
    """Sample 30 eligible PDFs using a fixed seed and propose three pages each."""

    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"ArcBench slides directory does not exist: {source_root}")
    pdfs = sorted(source_root.glob("*.pdf"), key=lambda path: path.name)
    if len(pdfs) != expected_pdfs:
        raise ValueError(f"Expected {expected_pdfs} ArcBench PDFs, found {len(pdfs)}")

    eligible: list[tuple[Path, int, dict[str, int]]] = []
    for pdf in pdfs:
        page_count = _page_count(pdf)
        if page_count >= 5:
            eligible.append((pdf, page_count, proposed_pages(page_count)))
    if len(eligible) < 30:
        raise ValueError(f"Need 30 decks with at least five pages; found {len(eligible)}")

    selected = random.Random(seed).sample(eligible, 30)
    decks = []
    seen_ids: set[str] = set()
    for pdf, page_count, pages in selected:
        match = _FILE_ID.match(pdf.name)
        if match is None:
            raise ValueError(f"ArcBench PDF lacks a slide index prefix: {pdf.name}")
        deck_id = f"arcbench_{int(match.group(1)):03d}"
        if deck_id in seen_ids:
            raise ValueError(f"Duplicate ArcBench deck index: {deck_id}")
        seen_ids.add(deck_id)
        decks.append({
            "deck_id": deck_id,
            "pdf": pdf.name,
            "split": "baseline",
            "page_count": page_count,
            "target_duration_seconds": 30,
            "reviewed": False,
            "slides": [
                {"position": position, "slide_number": page, "slide_type": None}
                for position, page in pages.items()
            ],
        })
    decks.sort(key=lambda deck: deck["deck_id"])
    return {
        "schema_version": "1.0.0",
        "selection_kind": "arcbench_30_decks_3_slides",
        "selection_seed": seed,
        "source_pdf_count": len(pdfs),
        "selection_note": (
            "Pages are selected by position only: page 2, the midpoint, and the "
            "penultimate PDF page. Manual review and slide_type labels are optional."
        ),
        "decks": decks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=33)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Selection already exists: {args.output}")
    draft = build_draft(args.source_root, seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote 30-deck selection draft: {args.output}")


if __name__ == "__main__":
    main()
