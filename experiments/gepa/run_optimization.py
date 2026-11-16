"""Optimize the multimodal speaker-script system prompt with GEPA 0.1.4.

Importing this module makes no model calls. Calling ``main`` runs a paid
experiment: generation + evaluation for GEPA metric calls. The held-out test
split is deliberately left to ``run_evaluation.py`` after prompt selection.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

from app.speaker_scripts import load_generation_instructions
from evaluation.run_evaluator import load_evaluator_instructions
from experiments.gepa.dataset import SlideExample, load_manifest
from experiments.gepa.pipeline import ModelSettings, score_example


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBJECTIVE = (
    "Improve a reusable system prompt that writes one spoken speaker script from a "
    "target research slide image, neighboring slide images, and optional supplied context. "
    "Optimize the fixed seven-dimension rubric score while avoiding unsupported claims."
)
BACKGROUND = (
    "The target slide image is primary evidence. Neighbor images support transitions; "
    "they are not evidence that a claim appears on the target slide. Optional notes or "
    "source excerpts may add context. The evaluator penalizes critical grounding errors "
    "with a zero per-example scalar score. The candidate must be a complete system "
    "instruction that can replace the current one without changing user inputs."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed-prompt", type=Path, default=PROJECT_ROOT / "prompts/speaker_script_gen/seed_v1_multimodal.md")
    parser.add_argument("--evaluator-prompt", type=Path, default=PROJECT_ROOT / "prompts/gepa_eval/evaluator_prompt.md")
    parser.add_argument("--rubric", type=Path, default=PROJECT_ROOT / "evaluation/speaker_script_rubric.yaml")
    parser.add_argument("--generation-model", required=True)
    parser.add_argument("--evaluator-model", required=True)
    parser.add_argument("--reflection-model", required=True)
    parser.add_argument("--generation-reasoning-effort", default=None)
    parser.add_argument("--evaluator-reasoning-effort", default=None)
    parser.add_argument("--reflection-reasoning-effort", default=None)
    parser.add_argument("--generation-max-output-tokens", type=int, default=1600)
    parser.add_argument("--evaluator-max-output-tokens", type=int, default=5000)
    parser.add_argument("--max-metric-calls", type=int, required=True)
    parser.add_argument("--seed", type=int, default=0)
    return parser


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_revision() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _require_nonempty_splits(splits: object) -> None:
    for name in ("train", "val", "test"):
        if not getattr(splits, name):
            raise SystemExit(f"Manifest has no {name} examples")


def main() -> None:
    args = build_parser().parse_args()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key or key.startswith("your-"):
        raise SystemExit("OPENAI_API_KEY must be set before optimization")
    if args.max_metric_calls < 1:
        raise SystemExit("--max-metric-calls must be positive")
    if args.generation_max_output_tokens < 1 or args.evaluator_max_output_tokens < 1:
        raise SystemExit("Output token limits must be positive")

    # GEPA's 0.1.4 public API has dataset + valset, but no test_set. The test
    # split stays out of GEPA and is evaluated only after the prompt is frozen.
    from gepa.optimize_anything import EngineConfig, GEPAConfig, ReflectionConfig, optimize_anything

    splits = load_manifest(args.manifest, args.image_root)
    _require_nonempty_splits(splits)
    seed_prompt = load_generation_instructions(args.seed_prompt)
    settings = ModelSettings(
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
    (output_dir / "seed_prompt.txt").write_text(seed_prompt + "\n", encoding="utf-8")
    (output_dir / "evaluator_instructions.txt").write_text(
        settings.evaluator_instructions + "\n", encoding="utf-8"
    )

    reflection_model = args.reflection_model
    if "/" not in reflection_model:
        reflection_model = f"openai/{reflection_model}"
    reflection_kwargs = (
        {"reasoning_effort": args.reflection_reasoning_effort}
        if args.reflection_reasoning_effort
        else None
    )
    _write_json(
        output_dir / "run_config.json",
        {
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_revision": _git_revision(),
            "manifest_path": str(args.manifest.resolve()),
            "manifest_sha256": _sha256(args.manifest),
            "image_root": str(args.image_root.resolve()),
            "train_count": len(splits.train),
            "val_count": len(splits.val),
            "test_count": len(splits.test),
            "seed_prompt_sha256": _sha256(args.seed_prompt),
            "evaluator_prompt_sha256": _sha256(args.evaluator_prompt),
            "rubric_sha256": _sha256(args.rubric),
            "generation_model": args.generation_model,
            "evaluator_model": args.evaluator_model,
            "reflection_model": reflection_model,
            "generation_reasoning_effort": args.generation_reasoning_effort,
            "evaluator_reasoning_effort": args.evaluator_reasoning_effort,
            "reflection_reasoning_effort": args.reflection_reasoning_effort,
            "generation_max_output_tokens": args.generation_max_output_tokens,
            "evaluator_max_output_tokens": args.evaluator_max_output_tokens,
            "max_metric_calls": args.max_metric_calls,
            "seed": args.seed,
            "image_detail": "high",
            "gepa_version": _package_version("gepa"),
            "openai_version": _package_version("openai"),
        },
    )

    client = OpenAI()
    optimization_records = output_dir / "optimization_evaluations.jsonl"

    def evaluator(candidate: str, example: SlideExample) -> tuple[float, dict]:
        scored = score_example(candidate, example, client=client, settings=settings)
        # GEPA is configured sequentially below; append one durable line per
        # completed example so interrupted experiments remain inspectable.
        with optimization_records.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(scored.to_record("train_or_val", "gepa"), ensure_ascii=False) + "\n")
        return scored.score, scored.feedback_for_gepa()

    config = GEPAConfig(
        engine=EngineConfig(
            run_dir=str(output_dir / "gepa_state"),
            seed=args.seed,
            max_metric_calls=args.max_metric_calls,
            parallel=False,
            max_workers=1,
            raise_on_exception=True,
        ),
        reflection=ReflectionConfig(
            reflection_lm=reflection_model,
            reflection_lm_kwargs=reflection_kwargs,
        ),
    )
    result = optimize_anything(
        seed_candidate=seed_prompt,
        evaluator=evaluator,
        dataset=list(splits.train),
        valset=list(splits.val),
        objective=OBJECTIVE,
        background=BACKGROUND,
        config=config,
    )
    best_prompt = result.best_candidate
    if not isinstance(best_prompt, str) or not best_prompt.strip():
        raise RuntimeError("GEPA did not return a nonempty string prompt")
    (output_dir / "best_prompt.txt").write_text(best_prompt + "\n", encoding="utf-8")
    _write_json(
        output_dir / "optimization_summary.json",
        {
            "best_idx": result.best_idx,
            "best_val_score": result.val_aggregate_scores[result.best_idx],
            "val_aggregate_scores": result.val_aggregate_scores,
            "num_candidates": result.num_candidates,
            "total_metric_calls": result.total_metric_calls,
        },
    )
    _write_json(output_dir / "gepa_result.json", result.to_dict())

    print(f"Saved GEPA prompt and optimization record in {output_dir}")


if __name__ == "__main__":
    main()
