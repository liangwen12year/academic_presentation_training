"""Run a fixed 90-script ArcBench baseline with Luna and Claude; paid API calls.

This runner never invokes GEPA. It requires a rendered positional baseline
manifest and explicit OpenAI and Anthropic API keys in the environment. The
--swap flag uses Claude for generation and Luna for evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from openai import OpenAI

from app.anthropic_speaker_scripts import generate_script_claude
from app.speaker_scripts import SlideContext, generate_script, load_generation_instructions
from evaluation.anthropic_evaluator import evaluate_script_claude
from evaluation.evaluator_schema import EvaluationResult
from evaluation.run_evaluator import evaluate_script, load_evaluator_instructions
from evaluation.scoring import calculate_score
from experiments.baseline.request_audit import summarize_request
from experiments.baseline.show_prompt import format_request
from experiments.gepa.dataset import SlideExample, load_manifest
from experiments.gepa.pipeline import ScoredExample, as_slide_context, summarize

ROOT = Path(__file__).resolve().parents[2]
SEED_PROMPT = ROOT / "prompts/speaker_script_gen/seed_v1_multimodal.md"
EVALUATOR_PROMPT = ROOT / "prompts/gepa_eval/evaluator_prompt.md"
RUBRIC = ROOT / "evaluation/speaker_script_rubric.yaml"
GENERATION_MODEL = "gpt-5.6-luna"
EVALUATOR_MODEL = "claude-haiku-5-5"
EFFORT = "medium"
POSITIONS = {"beginning", "middle", "penultimate_page"}
SLIDE_TYPES = {"text", "chart", "table", "diagram", "equation", "image", "mixed", "other"}
MAX_CLAUDE_BASE64_BYTES = 10_000_000


def validate_baseline_manifest(manifest_path: Path, image_root: Path) -> tuple[SlideExample, ...]:
    """Refuse incomplete or position-mislabeled baseline samples."""

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if raw.get("render_dpi") != 200:
        raise ValueError("Baseline slides must be rendered at 200 DPI")
    splits = load_manifest(manifest_path, image_root)
    if splits.train or splits.val or splits.test:
        raise ValueError("Baseline manifest must contain only baseline examples")
    examples = splits.baseline
    if len(examples) != 90:
        raise ValueError(f"Baseline requires 90 target slides; found {len(examples)}")
    decks: dict[str, list[SlideExample]] = defaultdict(list)
    for example in examples:
        if example.position not in POSITIONS:
            raise ValueError(f"Example {example.example_id} lacks a valid position")
        if example.slide_type is not None and example.slide_type not in SLIDE_TYPES:
            raise ValueError(f"Example {example.example_id} has an invalid slide_type")
        decks[example.deck_id].append(example)
    if len(decks) != 30:
        raise ValueError(f"Baseline requires 30 decks; found {len(decks)}")
    for deck_id, slides in decks.items():
        if len(slides) != 3 or {slide.position for slide in slides} != POSITIONS:
            raise ValueError(f"Deck {deck_id} must have one slide at each baseline position")
        if len({slide.slide_number for slide in slides}) != 3:
            raise ValueError(f"Deck {deck_id} has repeated target page numbers")
        pages = {slide.position: slide.slide_number for slide in slides}
        if not (pages["beginning"] < pages["middle"] < pages["penultimate_page"]):
            raise ValueError(f"Deck {deck_id} has baseline positions out of page order")
    image_paths = {
        path
        for example in examples
        for path in (
            example.preceding_slide_image,
            example.target_slide_image,
            example.following_slide_image,
        )
        if path is not None
    }
    for path in image_paths:
        encoded_size = 4 * ((path.stat().st_size + 2) // 3)
        if encoded_size > MAX_CLAUDE_BASE64_BYTES:
            raise ValueError(f"Slide image exceeds Claude's 10 MB base64 limit: {path}")
    return examples


def score_baseline_example(
    example: SlideExample,
    *,
    generation_client: OpenAI | Anthropic,
    evaluator_client: Anthropic | OpenAI,
    generation_instructions: str,
    evaluator_instructions: str,
    generation_max_output_tokens: int,
    evaluator_max_output_tokens: int,
    swap: bool = False,
    request_audit: Callable[[str, dict[str, Any], SlideContext], None] | None = None,
) -> ScoredExample:
    """Generate once with the seed and evaluate once with the fixed rubric."""

    slide = as_slide_context(example)
    generation_hook = (lambda request: request_audit("generation", request, slide)) if request_audit else None
    evaluation_hook = (lambda request: request_audit("evaluation", request, slide)) if request_audit else None
    if swap:
        generated = generate_script_claude(
            generation_instructions, slide, client=generation_client,
            model=EVALUATOR_MODEL, max_output_tokens=generation_max_output_tokens,
            effort=EFFORT, request_hook=generation_hook,
        )
        evaluated = evaluate_script(
            generated.text, slide, client=evaluator_client,
            instructions=evaluator_instructions, model=GENERATION_MODEL,
            max_output_tokens=evaluator_max_output_tokens,
            reasoning_effort=EFFORT, request_hook=evaluation_hook,
        )
    else:
        generated = generate_script(
            generation_instructions, slide, client=generation_client,
            model=GENERATION_MODEL, max_output_tokens=generation_max_output_tokens,
            reasoning_effort=EFFORT, request_hook=generation_hook,
        )
        evaluated = evaluate_script_claude(
            generated.text, slide, client=evaluator_client,
            instructions=evaluator_instructions, model=EVALUATOR_MODEL,
            max_output_tokens=evaluator_max_output_tokens,
            effort=EFFORT, request_hook=evaluation_hook,
        )
    return ScoredExample(
        example_id=example.example_id,
        deck_id=example.deck_id,
        slide_number=example.slide_number,
        candidate_sha256=hashlib.sha256(generation_instructions.encode("utf-8")).hexdigest(),
        script=generated.text,
        evaluation=evaluated.result,
        score=calculate_score(evaluated.result),
        generation_usage=generated.usage,
        evaluator_usage=evaluated.usage,
        position=example.position,
        slide_type=example.slide_type,
    )


def _completed_records(path: Path, examples: tuple[SlideExample, ...], prompt_hash: str) -> list[ScoredExample]:
    """Load a contiguous prefix of validated results for safe resumption."""

    if not path.exists():
        return []
    completed: list[ScoredExample] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            raise ValueError(f"Blank result line {index + 1}")
        if index >= len(examples):
            raise ValueError("Result file has more than 90 examples")
        record = json.loads(line)
        example = examples[index]
        if (
            record.get("example_id") != example.example_id
            or record.get("deck_id") != example.deck_id
            or record.get("slide_number") != example.slide_number
            or record.get("position") != example.position
            or record.get("slide_type") != example.slide_type
            or record.get("candidate_sha256") != prompt_hash
            or record.get("split") != "baseline"
        ):
            raise ValueError(f"Result line {index + 1} does not match this baseline manifest")
        evaluation = EvaluationResult.model_validate(record["evaluation"])
        if abs(float(record["score"]) - calculate_score(evaluation)) > 1e-9:
            raise ValueError(f"Result line {index + 1} has an inconsistent score")
        completed.append(ScoredExample(
            example_id=example.example_id,
            deck_id=example.deck_id,
            slide_number=example.slide_number,
            candidate_sha256=prompt_hash,
            script=record["script"],
            evaluation=evaluation,
            score=float(record["score"]),
            generation_usage=record["generation_usage"],
            evaluator_usage=record["evaluator_usage"],
            position=example.position,
            slide_type=example.slide_type,
        ))
    return completed


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def write_request_log(output_dir: Path, audit: dict[str, Any]) -> None:
    """Save readable and structured copies before the corresponding SDK call."""

    example_id = audit["example_id"]
    if re.fullmatch(r"[A-Za-z0-9_-]+", example_id) is None:
        raise ValueError(f"Unsafe example ID for request log: {example_id}")
    stage_dir = {"generation": "generator", "evaluation": "evaluator"}.get(audit["stage"])
    if stage_dir is None:
        raise ValueError(f"Unknown request stage: {audit['stage']}")
    directory = output_dir / "log" / stage_dir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{example_id}.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (directory / f"{example_id}.txt").write_text(format_request(audit) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--generation-max-output-tokens", type=int, default=1600)
    parser.add_argument("--evaluator-max-output-tokens", type=int, default=8192)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--swap", action="store_true", help="Claude generates; GPT-5.6 Luna evaluates")
    args = parser.parse_args()
    if args.generation_max_output_tokens < 1 or args.evaluator_max_output_tokens < 1:
        raise SystemExit("Output token limits must be positive")

    examples = validate_baseline_manifest(args.manifest, args.image_root)
    generation_instructions = load_generation_instructions(SEED_PROMPT)
    evaluator_instructions = load_evaluator_instructions(EVALUATOR_PROMPT, RUBRIC)
    prompt_hash = hashlib.sha256(generation_instructions.encode("utf-8")).hexdigest()
    config = {
        "manifest_path": str(args.manifest.resolve()),
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "image_root": str(args.image_root.resolve()),
        "example_count": len(examples),
        "deck_count": len({example.deck_id for example in examples}),
        "seed_prompt_sha256": hashlib.sha256(SEED_PROMPT.read_bytes()).hexdigest(),
        "generation_instructions_sha256": prompt_hash,
        "evaluator_prompt_sha256": hashlib.sha256(EVALUATOR_PROMPT.read_bytes()).hexdigest(),
        "rubric_sha256": hashlib.sha256(RUBRIC.read_bytes()).hexdigest(),
        "generation_model": EVALUATOR_MODEL if args.swap else GENERATION_MODEL,
        "generation_provider": "anthropic" if args.swap else "openai",
        "generation_reasoning_effort": EFFORT,
        "generation_max_output_tokens": args.generation_max_output_tokens,
        "evaluator_model": GENERATION_MODEL if args.swap else EVALUATOR_MODEL,
        "evaluator_provider": "openai" if args.swap else "anthropic",
        "evaluator_effort": EFFORT,
        "evaluator_max_output_tokens": args.evaluator_max_output_tokens,
        "render_dpi": 200,
        "openai_sdk_version": _version("openai"),
        "anthropic_sdk_version": _version("anthropic"),
    }

    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        value = os.environ.get(name, "").strip()
        if not value or value.startswith("your-"):
            raise SystemExit(f"{name} must be set before running the baseline")

    output_dir = args.output_dir.resolve()
    config_path = output_dir / "run_config.json"
    if args.resume:
        if not config_path.is_file():
            raise FileNotFoundError(f"No baseline run to resume in {output_dir}")
        prior = json.loads(config_path.read_text(encoding="utf-8"))
        # Runs created before the swap option stored model names but not provider names.
        if not args.swap:
            prior.setdefault("generation_provider", "openai")
            prior.setdefault("evaluator_provider", "anthropic")
        if {key: prior.get(key) for key in config} != config:
            raise ValueError("Run configuration or input files changed; cannot resume safely")
    else:
        output_dir.mkdir(parents=True, exist_ok=False)
        config_path.write_text(
            json.dumps({**config, "started_at_utc": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / "generation_prompt.txt").write_text(generation_instructions + "\n", encoding="utf-8")
        (output_dir / "evaluator_instructions.txt").write_text(evaluator_instructions + "\n", encoding="utf-8")

    records_path = output_dir / "evaluations.jsonl"
    results = _completed_records(records_path, examples, prompt_hash)
    generation_client = Anthropic() if args.swap else OpenAI()
    evaluator_client = OpenAI() if args.swap else Anthropic()
    with records_path.open("a", encoding="utf-8") as stream:
        for example in examples[len(results):]:
            audit_records: list[dict[str, Any]] = []

            def capture_request(stage: str, request: dict[str, Any], slide: SlideContext) -> None:
                audit = summarize_request(
                    stage=stage, example_id=example.example_id, slide=slide, request=request,
                )
                write_request_log(output_dir, audit)
                audit_records.append(audit)

            scored = score_baseline_example(
                example,
                generation_client=generation_client,
                evaluator_client=evaluator_client,
                generation_instructions=generation_instructions,
                evaluator_instructions=evaluator_instructions,
                generation_max_output_tokens=args.generation_max_output_tokens,
                evaluator_max_output_tokens=args.evaluator_max_output_tokens,
                swap=args.swap,
                request_audit=capture_request,
            )
            if [record["stage"] for record in audit_records] != ["generation", "evaluation"]:
                raise ValueError(f"Incomplete request audit for {example.example_id}")
            record = scored.to_record("baseline", "seed_v1_multimodal")
            record["request_audit"] = audit_records
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            results.append(scored)
            print(f"Completed {len(results)}/90: {example.example_id}", flush=True)

    (output_dir / "summary.json").write_text(
        json.dumps(summarize(results), indent=2) + "\n", encoding="utf-8"
    )
    print(f"Completed baseline evaluation: {output_dir}")


if __name__ == "__main__":
    main()
