"""Plot the completed 90-script baseline from its saved JSONL results; no API calls."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from evaluation.evaluator_schema import DIMENSION_NAMES, EvaluationResult
from evaluation.scoring import calculate_score

POSITIONS = ("beginning", "middle", "penultimate_page")


def read_results(path: Path) -> list[dict]:
    """Require exactly one valid result per target in the finished baseline."""

    rows = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        row = json.loads(line)
        if row.get("split") != "baseline" or row.get("candidate_label") != "seed_v1_multimodal":
            raise ValueError(f"Line {line_number} is not a seed baseline result")
        example_id = row.get("example_id")
        if not isinstance(example_id, str) or example_id in seen_ids:
            raise ValueError(f"Missing or duplicate example ID on line {line_number}")
        seen_ids.add(example_id)
        evaluation = EvaluationResult.model_validate(row["evaluation"])
        score = row["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise ValueError(f"Invalid score on line {line_number}")
        if abs(score - calculate_score(evaluation)) > 1e-9:
            raise ValueError(f"Inconsistent score on line {line_number}")
        if row.get("position") not in POSITIONS:
            raise ValueError(f"Missing page-position metadata on line {line_number}")
        rows.append(row)
    if len(rows) != 90 or len({row["deck_id"] for row in rows}) != 30:
        raise ValueError(f"Expected 90 scripts from 30 decks; found {len(rows)} scripts")
    return rows


def summarize_distributions(rows: list[dict]) -> dict:
    """Count aggregate-score bins and 1–5 ratings, preserving N/A counts."""

    score_labels = [
        f"[{lower:.1f}, {lower + 0.1:.1f})"
        for lower in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
    ] + ["[0.9, 1.0]"]
    aggregate_counts = Counter({label: 0 for label in score_labels})
    dimension_counts = {
        name: Counter({str(score): 0 for score in range(1, 6)} | {"N/A": 0})
        for name in DIMENSION_NAMES
    }
    scores_by_position: dict[str, list[float]] = defaultdict(list)
    scores = []
    for row in rows:
        score = float(row["score"])
        scores.append(score)
        scores_by_position[row["position"]].append(score)
        evaluation = row["evaluation"]
        if not 0.2 <= score <= 1.0:
            raise ValueError(f"Unexpected aggregate score: {score}")
        index = min(7, int((score - 0.2 + 1e-10) / 0.1))
        aggregate_counts[score_labels[index]] += 1
        for name in DIMENSION_NAMES:
            result = evaluation["dimensions"][name]
            label = str(result["score"]) if result["applicable"] else "N/A"
            dimension_counts[name][label] += 1
    return {
        "script_count": len(rows),
        "deck_count": len({row["deck_id"] for row in rows}),
        "mean_aggregate_score": mean(scores),
        "median_aggregate_score": median(scores),
        "aggregate_score_bins": dict(aggregate_counts),
        "dimension_rating_counts": {name: dict(counts) for name, counts in dimension_counts.items()},
        "by_position": {
            position: {"n": len(values), "mean_aggregate_score": mean(values)}
            for position, values in scores_by_position.items()
        },
    }


def plot_distributions(summary: dict, output_dir: Path) -> None:
    """Create shareable PNG plots from a validated summary."""

    output_dir.mkdir(parents=True, exist_ok=True)
    counts = summary["aggregate_score_bins"]
    figure, axis = plt.subplots(figsize=(11, 5.2))
    bars = axis.bar(list(counts), list(counts.values()), color="#31588b")
    axis.bar_label(bars, labels=[str(value) for value in counts.values()], padding=3)
    axis.set(
        title=f"Seed prompt: aggregate scores across {summary['script_count']} scripts",
        xlabel="Normalized aggregate score interval",
        ylabel="Number of scripts",
    )
    axis.set_ylim(0, max(counts.values()) * 1.2 + 1)
    axis.tick_params(axis="x", rotation=30)
    axis.text(
        0.02, 0.96,
        f"Mean: {summary['mean_aggregate_score']:.3f}\nMedian: {summary['median_aggregate_score']:.3f}",
        transform=axis.transAxes,
        va="top",
        bbox={"boxstyle": "round,pad=0.4", "facecolor": "white", "edgecolor": "#b8c4d0"},
    )
    provenance_note = summary.get("provenance_note")
    if provenance_note:
        figure.text(0.02, 0.01, provenance_note, fontsize=8)
    figure.tight_layout(rect=(0, 0.04 if provenance_note else 0, 1, 1))
    figure.savefig(output_dir / "aggregate_score_distribution.png", dpi=160)
    plt.close(figure)

    figure, axes = plt.subplots(4, 2, figsize=(11, 13))
    for axis, name in zip(axes.flat, DIMENSION_NAMES):
        ratings = summary["dimension_rating_counts"][name]
        labels = ["1", "2", "3", "4", "5", "N/A"]
        axis.bar(labels, [ratings[label] for label in labels], color="#31588b")
        axis.set(title=name.replace("_", " ").title(), xlabel="Rubric rating", ylabel="Number of scripts")
        axis.set_ylim(bottom=0)
    axes.flat[-1].set_visible(False)
    figure.suptitle("Seed prompt: seven rubric dimensions across 90 scripts")
    if provenance_note:
        figure.text(0.02, 0.01, provenance_note, fontsize=8)
    figure.tight_layout(rect=(0, 0.03 if provenance_note else 0, 1, 0.97))
    figure.savefig(output_dir / "dimension_rating_distributions.png", dpi=160)
    plt.close(figure)

    (output_dir / "distribution_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = summarize_distributions(read_results(args.results))
    plot_distributions(summary, args.output_dir)
    print(f"Saved baseline distributions in {args.output_dir}")


if __name__ == "__main__":
    main()
