"""Rescore a rubric 1.0.0 baseline from saved ratings, without model calls.

This is an exploratory comparison, not a fresh evaluation: the dimension
ratings were produced by an evaluator instructed with the old rubric.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from evaluation.evaluator_schema import EvaluationResult
from evaluation.scoring import calculate_score
from experiments.baseline.plot_results import plot_distributions, read_results, summarize_distributions


def convert_record(record: dict[str, Any]) -> dict[str, Any]:
    """Drop the old flag and use only the saved seven dimension ratings."""

    old = record["evaluation"]
    if old.get("rubric_version") != "1.0.0" or not isinstance(old.get("critical_grounding_error"), dict):
        raise ValueError(f"Expected a rubric 1.0.0 evaluation: {record.get('example_id')}")
    evaluation = EvaluationResult.model_validate({
        "rubric_version": "1.1.0",
        "dimensions": old["dimensions"],
    })
    original_score = record.get("score")
    if isinstance(original_score, bool) or not isinstance(original_score, (int, float)):
        raise ValueError(f"Invalid original score: {record.get('example_id')}")
    expected_original = (
        0.0 if old["critical_grounding_error"].get("present") else calculate_score(evaluation)
    )
    if not math.isclose(original_score, expected_original, abs_tol=1e-9):
        raise ValueError(f"Original score does not match old policy: {record.get('example_id')}")
    converted = dict(record)
    converted["evaluation"] = evaluation.model_dump(mode="json")
    converted["score"] = calculate_score(evaluation)
    converted["rescore_provenance"] = {
        "source_rubric_version": "1.0.0",
        "original_score": original_score,
        "method": "reuse_saved_dimension_ratings_without_model_calls",
    }
    return converted


def rescore_file(source: Path, output_dir: Path) -> dict[str, Any]:
    """Create a separate results directory and leave the original run intact."""

    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    source_lines = source.read_text(encoding="utf-8").splitlines()
    if not source_lines or any(not line.strip() for line in source_lines):
        raise ValueError("Source results must contain nonblank JSONL records")
    converted = [convert_record(json.loads(line)) for line in source_lines]
    if len(converted) != 90 or len({row["deck_id"] for row in converted}) != 30:
        raise ValueError("Expected 90 scripts from 30 decks")

    output_dir.mkdir(parents=True)
    results_path = output_dir / "evaluations.jsonl"
    results_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in converted) + "\n",
        encoding="utf-8",
    )
    note = "Rescored from rubric 1.0.0 dimension ratings; no new evaluator calls."
    summary = summarize_distributions(read_results(results_path))
    summary["provenance_note"] = note
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output_dir / "rescore_provenance.json").write_text(json.dumps({
        "source_results": str(source.resolve()),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_rubric_version": "1.0.0",
        "new_scoring_rubric_version": "1.1.0",
        "method": "reuse_saved_dimension_ratings_without_model_calls",
        "limitation": "Old evaluator instructions may have affected the dimension ratings; this is not a new evaluation.",
    }, indent=2) + "\n", encoding="utf-8")
    plot_distributions(summary, output_dir / "plots")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Original rubric 1.0.0 evaluations.jsonl")
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory for rescored results")
    args = parser.parse_args()
    summary = rescore_file(args.source, args.output_dir)
    print(f"Rescored {summary['script_count']} scripts without model calls: {args.output_dir}")


if __name__ == "__main__":
    main()
