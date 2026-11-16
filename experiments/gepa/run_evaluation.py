"""Evaluate one or two fixed prompts on a manifest split (opt-in API run)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

from app.speaker_scripts import load_generation_instructions
from evaluation.run_evaluator import load_evaluator_instructions
from experiments.gepa.dataset import load_manifest
from experiments.gepa.pipeline import ModelSettings, evaluate_set, summarize


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "val", "test"), required=True)
    parser.add_argument("--allow-test", action="store_true", help="Explicitly unlock the held-out test split")
    parser.add_argument("--prompt", type=Path, default=PROJECT_ROOT / "prompts/speaker_script_gen/seed_v1_multimodal.md")
    parser.add_argument("--compare-prompt", type=Path, default=None)
    parser.add_argument("--evaluator-prompt", type=Path, default=PROJECT_ROOT / "prompts/gepa_eval/evaluator_prompt.md")
    parser.add_argument("--rubric", type=Path, default=PROJECT_ROOT / "evaluation/speaker_script_rubric.yaml")
    parser.add_argument("--generation-model", required=True)
    parser.add_argument("--evaluator-model", required=True)
    parser.add_argument("--generation-reasoning-effort", default=None)
    parser.add_argument("--evaluator-reasoning-effort", default=None)
    parser.add_argument("--generation-max-output-tokens", type=int, default=1600)
    parser.add_argument("--evaluator-max-output-tokens", type=int, default=5000)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key or key.startswith("your-"):
        raise SystemExit("OPENAI_API_KEY must be set before evaluation")
    if args.split == "test" and not args.allow_test:
        raise SystemExit("The test split is held out; pass --allow-test only for final evaluation")
    if args.generation_max_output_tokens < 1 or args.evaluator_max_output_tokens < 1:
        raise SystemExit("Output token limits must be positive")

    splits = load_manifest(args.manifest, args.image_root)
    examples = getattr(splits, args.split)
    if not examples:
        raise SystemExit(f"Manifest has no {args.split} examples")
    candidate = load_generation_instructions(args.prompt)
    comparison_candidate = (
        load_generation_instructions(args.compare_prompt)
        if args.compare_prompt is not None
        else None
    )
    model_settings = ModelSettings(
        generation_model=args.generation_model,
        evaluator_model=args.evaluator_model,
        evaluator_instructions=load_evaluator_instructions(args.evaluator_prompt, args.rubric),
        generation_max_output_tokens=args.generation_max_output_tokens,
        evaluator_max_output_tokens=args.evaluator_max_output_tokens,
        generation_reasoning_effort=args.generation_reasoning_effort,
        evaluator_reasoning_effort=args.evaluator_reasoning_effort,
    )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "generation_prompt.txt").write_text(candidate + "\n", encoding="utf-8")
    if comparison_candidate is not None:
        (output_dir / "comparison_prompt.txt").write_text(
            comparison_candidate + "\n", encoding="utf-8"
        )
    (output_dir / "evaluator_instructions.txt").write_text(
        model_settings.evaluator_instructions + "\n", encoding="utf-8"
    )
    (output_dir / "run_config.json").write_text(
        json.dumps(
            {
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "manifest_path": str(args.manifest.resolve()),
                "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
                "image_root": str(args.image_root.resolve()),
                "split": args.split,
                "example_count": len(examples),
                "generation_prompt_sha256": hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
                "comparison_prompt_sha256": (
                    hashlib.sha256(comparison_candidate.encode("utf-8")).hexdigest()
                    if comparison_candidate is not None
                    else None
                ),
                "evaluator_prompt_sha256": hashlib.sha256(args.evaluator_prompt.read_bytes()).hexdigest(),
                "rubric_sha256": hashlib.sha256(args.rubric.read_bytes()).hexdigest(),
                "generation_model": args.generation_model,
                "evaluator_model": args.evaluator_model,
                "generation_reasoning_effort": args.generation_reasoning_effort,
                "evaluator_reasoning_effort": args.evaluator_reasoning_effort,
                "generation_max_output_tokens": args.generation_max_output_tokens,
                "evaluator_max_output_tokens": args.evaluator_max_output_tokens,
                "image_detail": "high",
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    client = OpenAI()
    results = evaluate_set(
        candidate,
        examples,
        client=client,
        settings=model_settings,
        records_path=output_dir / "evaluations.jsonl",
        split=args.split,
        candidate_label=args.prompt.stem,
    )
    summary = summarize(results)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if comparison_candidate is not None:
        if comparison_candidate == candidate:
            comparison_results = results
            comparison_summary = summary
        else:
            comparison_results = evaluate_set(
                comparison_candidate,
                examples,
                client=client,
                settings=model_settings,
                records_path=output_dir / "evaluations.jsonl",
                split=args.split,
                candidate_label=args.compare_prompt.stem,
            )
            comparison_summary = summarize(comparison_results)
        comparison = {
            "prompts_match": comparison_candidate == candidate,
            "first": summary,
            "comparison": comparison_summary,
            "mean_score_delta": comparison_summary["mean_score"] - summary["mean_score"],
            "paired_examples": [
                {
                    "example_id": first.example_id,
                    "first_score": first.score,
                    "comparison_score": second.score,
                    "score_delta": second.score - first.score,
                    "first_critical_grounding_error": first.evaluation.critical_grounding_error.present,
                    "comparison_critical_grounding_error": second.evaluation.critical_grounding_error.present,
                }
                for first, second in zip(results, comparison_results, strict=True)
            ],
        }
        (output_dir / "comparison.json").write_text(
            json.dumps(comparison, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(comparison, indent=2))
    else:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
