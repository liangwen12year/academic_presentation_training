"""Evaluate saved baseline scripts with the current rubric; paid Claude calls only.

Reads generated scripts from an existing baseline JSONL file. It never calls
the generation model and writes the new evaluations to a separate run directory.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from app.speaker_scripts import SlideContext
from evaluation.anthropic_evaluator import evaluate_script_claude
from evaluation.evaluator_schema import EvaluationResult, RUBRIC_VERSION
from evaluation.run_evaluator import load_evaluator_instructions
from evaluation.scoring import calculate_score
from experiments.baseline.request_audit import summarize_request
from experiments.baseline.run_baseline import (
    EFFORT,
    EVALUATOR_MODEL,
    EVALUATOR_PROMPT,
    RUBRIC,
    validate_baseline_manifest,
    write_request_log,
)
from experiments.gepa.dataset import SlideExample
from experiments.gepa.pipeline import ScoredExample, as_slide_context, summarize


def load_saved_scripts(path: Path, examples: tuple[SlideExample, ...]) -> tuple[dict[str, Any], ...]:
    """Require one nonempty saved script for every manifest target, in order."""

    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != len(examples):
        raise ValueError(f"Expected {len(examples)} saved scripts; found {len(lines)}")
    records = []
    for line_number, (line, example) in enumerate(zip(lines, examples, strict=True), start=1):
        if not line.strip():
            raise ValueError(f"Blank source result line {line_number}")
        record = json.loads(line)
        if any((
            record.get("split") != "baseline",
            record.get("candidate_label") != "seed_v1_multimodal",
            record.get("example_id") != example.example_id,
            record.get("deck_id") != example.deck_id,
            record.get("slide_number") != example.slide_number,
            record.get("position") != example.position,
            record.get("slide_type") != example.slide_type,
        )):
            raise ValueError(f"Source result line {line_number} does not match the manifest")
        if not isinstance(record.get("script"), str) or not record["script"].strip():
            raise ValueError(f"Source result line {line_number} has no script")
        if not isinstance(record.get("candidate_sha256"), str):
            raise ValueError(f"Source result line {line_number} has no prompt hash")
        if not isinstance(record.get("evaluation"), dict) or not isinstance(record["evaluation"].get("rubric_version"), str):
            raise ValueError(f"Source result line {line_number} lacks evaluation provenance")
        records.append(record)
    return tuple(records)


def evaluate_saved_example(
    example: SlideExample,
    source: dict[str, Any],
    *,
    client: Anthropic,
    instructions: str,
    model: str,
    effort: str,
    max_output_tokens: int,
    output_dir: Path,
) -> tuple[ScoredExample, dict[str, Any]]:
    """Send the unchanged saved script and slide images to the evaluator."""

    slide = as_slide_context(example)
    request_audit: dict[str, Any] | None = None

    def capture_request(request: dict[str, Any]) -> None:
        nonlocal request_audit
        request_audit = summarize_request(
            stage="evaluation", example_id=example.example_id, slide=slide, request=request,
        )
        write_request_log(output_dir, request_audit)

    evaluated = evaluate_script_claude(
        source["script"], slide,
        client=client,
        instructions=instructions,
        model=model,
        max_output_tokens=max_output_tokens,
        effort=effort,
        request_hook=capture_request,
    )
    if request_audit is None:
        raise ValueError(f"Missing evaluator request audit for {example.example_id}")
    scored = ScoredExample(
        example_id=example.example_id,
        deck_id=example.deck_id,
        slide_number=example.slide_number,
        candidate_sha256=source["candidate_sha256"],
        script=source["script"],
        evaluation=evaluated.result,
        score=calculate_score(evaluated.result),
        generation_usage={},
        evaluator_usage=evaluated.usage,
        position=example.position,
        slide_type=example.slide_type,
    )
    return scored, request_audit


def completed_results(
    path: Path,
    examples: tuple[SlideExample, ...],
    source_records: tuple[dict[str, Any], ...],
) -> list[ScoredExample]:
    """Validate a contiguous result prefix before skipping any saved scripts."""

    if not path.exists():
        return []
    completed = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip() or index >= len(examples):
            raise ValueError(f"Invalid evaluation-only result line {index + 1}")
        record = json.loads(line)
        example = examples[index]
        source = source_records[index]
        if any((
            record.get("split") != "baseline",
            record.get("candidate_label") != source["candidate_label"],
            record.get("example_id") != example.example_id,
            record.get("deck_id") != example.deck_id,
            record.get("slide_number") != example.slide_number,
            record.get("position") != example.position,
            record.get("slide_type") != example.slide_type,
            record.get("candidate_sha256") != source["candidate_sha256"],
            record.get("script") != source["script"],
            record.get("source_rubric_version") != source["evaluation"]["rubric_version"],
        )):
            raise ValueError(f"Result line {index + 1} does not match the saved script")
        audits = record.get("request_audit")
        if not isinstance(audits, list) or len(audits) != 1 or audits[0].get("stage") != "evaluation":
            raise ValueError(f"Result line {index + 1} lacks its evaluator request audit")
        evaluation = EvaluationResult.model_validate(record["evaluation"])
        score = calculate_score(evaluation)
        if abs(float(record["score"]) - score) > 1e-9:
            raise ValueError(f"Result line {index + 1} has an inconsistent score")
        completed.append(ScoredExample(
            example_id=example.example_id,
            deck_id=example.deck_id,
            slide_number=example.slide_number,
            candidate_sha256=source["candidate_sha256"],
            script=source["script"],
            evaluation=evaluation,
            score=score,
            generation_usage={},
            evaluator_usage=record["evaluator_usage"],
            position=example.position,
            slide_type=example.slide_type,
        ))
    return completed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-results", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--evaluator-model", default=EVALUATOR_MODEL)
    parser.add_argument("--evaluator-effort", default=EFFORT)
    parser.add_argument("--evaluator-max-output-tokens", type=int, default=8192)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.evaluator_max_output_tokens < 1:
        raise SystemExit("evaluator-max-output-tokens must be positive")

    examples = validate_baseline_manifest(args.manifest, args.image_root)
    source_records = load_saved_scripts(args.source_results, examples)
    instructions = load_evaluator_instructions(EVALUATOR_PROMPT, RUBRIC)
    manifest_sha256 = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    source_config_path = args.source_results.parent / "run_config.json"
    if source_config_path.is_file():
        source_config = json.loads(source_config_path.read_text(encoding="utf-8"))
        if source_config.get("manifest_sha256") != manifest_sha256:
            raise ValueError("Saved scripts were generated from a different manifest")
    config = {
        "run_kind": "evaluate_saved_scripts",
        "source_results_path": str(args.source_results.resolve()),
        "source_results_sha256": hashlib.sha256(args.source_results.read_bytes()).hexdigest(),
        "manifest_path": str(args.manifest.resolve()),
        "manifest_sha256": manifest_sha256,
        "image_root": str(args.image_root.resolve()),
        "example_count": len(examples),
        "evaluator_prompt_sha256": hashlib.sha256(EVALUATOR_PROMPT.read_bytes()).hexdigest(),
        "rubric_sha256": hashlib.sha256(RUBRIC.read_bytes()).hexdigest(),
        "rubric_version": RUBRIC_VERSION,
        "evaluator_model": args.evaluator_model,
        "evaluator_effort": args.evaluator_effort,
        "evaluator_max_output_tokens": args.evaluator_max_output_tokens,
        "anthropic_sdk_version": importlib.metadata.version("anthropic"),
    }

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or key.startswith("your-"):
        raise SystemExit("ANTHROPIC_API_KEY must be set before evaluation")

    output_dir = args.output_dir.resolve()
    config_path = output_dir / "run_config.json"
    if args.resume:
        if not config_path.is_file():
            raise FileNotFoundError(f"No evaluation-only run to resume in {output_dir}")
        prior = json.loads(config_path.read_text(encoding="utf-8"))
        if {name: prior.get(name) for name in config} != config:
            raise ValueError("Run configuration or input files changed; cannot resume safely")
    else:
        output_dir.mkdir(parents=True, exist_ok=False)
        config_path.write_text(
            json.dumps({**config, "started_at_utc": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / "evaluator_instructions.txt").write_text(instructions + "\n", encoding="utf-8")

    records_path = output_dir / "evaluations.jsonl"
    results = completed_results(records_path, examples, source_records)
    client = Anthropic()
    with records_path.open("a", encoding="utf-8") as stream:
        for example, source in zip(examples[len(results):], source_records[len(results):], strict=True):
            scored, audit = evaluate_saved_example(
                example, source,
                client=client,
                instructions=instructions,
                model=args.evaluator_model,
                effort=args.evaluator_effort,
                max_output_tokens=args.evaluator_max_output_tokens,
                output_dir=output_dir,
            )
            record = scored.to_record("baseline", source["candidate_label"])
            record["source_rubric_version"] = source["evaluation"]["rubric_version"]
            record["source_score"] = source.get("score")
            record["request_audit"] = [audit]
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            results.append(scored)
            print(f"Evaluated {len(results)}/{len(examples)}: {example.example_id}", flush=True)

    (output_dir / "summary.json").write_text(
        json.dumps(summarize(results), indent=2) + "\n", encoding="utf-8"
    )
    print(f"Completed evaluation-only run: {output_dir}")


if __name__ == "__main__":
    main()
