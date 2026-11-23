"""Serve a local, read-only viewer for saved baseline scripts and evaluations.

No model calls are made. Start with ``python -m experiments.baseline.viewer --help``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from evaluation.evaluator_schema import DIMENSION_NAMES, EvaluationResult
from evaluation.scoring import calculate_score
from experiments.gepa.dataset import SlideExample, load_manifest

ROOT = Path(__file__).resolve().parents[2]
ASSETS = Path(__file__).with_name("viewer_static")
DEFAULT_MANIFEST = ROOT / "data/gepa/baseline/manifest.json"
DEFAULT_IMAGE_ROOT = ROOT / "data/gepa/baseline/images"
DEFAULT_RESULTS = ROOT / "data/gepa/runs/baseline_002_swapped/evaluations.jsonl"
DEFAULT_BASELINE_1_RESULTS = ROOT / "data/gepa/runs/baseline_001_eval_v1_1/evaluations.jsonl"
DEFAULT_BASELINE_1_GENERATION = ROOT / "data/gepa/runs/baseline_001/evaluations.jsonl"
IMAGE_FIELDS = {
    "preceding": "preceding_slide_image",
    "target": "target_slide_image",
    "following": "following_slide_image",
}
PROMPT_FIELDS = (
    "Presentation title",
    "Intended audience",
    "Target speaking time",
    "Target slide number",
    "Speaker notes or raw script",
    "Relevant paper or source excerpt",
)


def _prompt_parameters(audit: dict[str, Any] | None, example: SlideExample) -> dict[str, str]:
    """Read the values that were actually submitted in the generator message."""

    if audit:
        for block in audit.get("user_content", []):
            if block.get("type") != "text":
                continue
            body = block.get("text", "")
            if not body.startswith("Presentation title: "):
                continue
            found = {}
            for index, key in enumerate(PROMPT_FIELDS):
                marker = f"{key}: "
                start = body.find(marker)
                if start < 0:
                    break
                start += len(marker)
                if index + 1 < len(PROMPT_FIELDS):
                    end = body.find(f"\n{PROMPT_FIELDS[index + 1]}: ", start)
                    if end < 0:
                        break
                else:
                    end = len(body)
                found[key] = body[start:end].strip()
            if len(found) == len(PROMPT_FIELDS):
                return found

    # Historical results may lack a generator audit. This fallback is labeled
    # in the API so it cannot be mistaken for a recorded request.
    return {
        "Presentation title": example.presentation_title or "Not provided",
        "Intended audience": example.intended_audience or "Not provided",
        "Target speaking time": (
            f"{example.target_duration_seconds:g} seconds"
            if example.target_duration_seconds is not None else "Not provided"
        ),
        "Target slide number": str(example.slide_number),
        "Speaker notes or raw script": example.speaker_notes or "Not provided",
        "Relevant paper or source excerpt": example.source_excerpt or "Not provided",
    }


def _load_data(results_path: Path, manifest_path: Path, image_root: Path) -> tuple[dict[str, dict], dict[str, SlideExample]]:
    splits = load_manifest(manifest_path, image_root)
    examples = {example.example_id: example for split in (splits.train, splits.val, splits.test, splits.baseline) for example in split}
    records: dict[str, dict] = {}
    with results_path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            example_id = record.get("example_id")
            if example_id not in examples:
                raise ValueError(f"Result line {number}: example ID is absent from the manifest: {example_id}")
            if example_id in records:
                raise ValueError(f"Result line {number}: duplicate example ID: {example_id}")
            example = examples[example_id]
            if record.get("deck_id") != example.deck_id or record.get("slide_number") != example.slide_number:
                raise ValueError(f"Result line {number}: deck or slide number differs from the manifest")
            evaluation = EvaluationResult.model_validate(record["evaluation"])
            score = record.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                raise ValueError(f"Result line {number}: invalid aggregate score")
            if abs(float(score) - calculate_score(evaluation)) > 1e-9:
                raise ValueError(f"Result line {number}: aggregate score disagrees with dimension ratings")
            audit = next(
                (item for item in record.get("request_audit", []) if item.get("stage") == "generation"),
                None,
            )
            if audit:
                logged = [Path(block["path"]).resolve() for block in audit.get("user_content", []) if block.get("type") == "image"]
                expected = [path for path in (
                    example.preceding_slide_image, example.target_slide_image, example.following_slide_image,
                ) if path is not None]
                if logged and logged != expected:
                    raise ValueError(f"Result line {number}: generator images differ from the manifest")
            records[example_id] = record
    if not records:
        raise ValueError(f"No completed evaluations in {results_path}")
    return records, examples


def _generation_audits(records: dict[str, dict]) -> dict[str, dict[str, Any]]:
    return {
        example_id: audit
        for example_id, record in records.items()
        if (audit := next(
            (item for item in record.get("request_audit", []) if item.get("stage") == "generation"),
            None,
        )) is not None
    }


def _original_generation_audits(path: Path, results: dict[str, dict]) -> dict[str, dict[str, Any]]:
    """Recover generation requests from baseline 1 without using its old scores."""

    audits = {}
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            example_id = record.get("example_id")
            if example_id not in results:
                raise ValueError(f"Original generation line {number}: unknown example ID")
            if example_id in audits:
                raise ValueError(f"Original generation line {number}: duplicate example ID")
            if (record.get("script") != results[example_id]["script"]
                    or record.get("candidate_sha256") != results[example_id].get("candidate_sha256")):
                raise ValueError(f"Original generation line {number}: script or seed prompt differs from the reevaluated run")
            audit = next(
                (item for item in record.get("request_audit", []) if item.get("stage") == "generation"),
                None,
            )
            if audit is None:
                raise ValueError(f"Original generation line {number}: no generator request audit")
            audits[example_id] = audit
    if set(audits) != set(results):
        raise ValueError("Original generation run and reevaluated baseline 1 have different examples")
    return audits


def create_app(
    results_path: Path,
    manifest_path: Path,
    image_root: Path,
    *,
    baseline1_results_path: Path | None = None,
    baseline1_generation_path: Path | None = None,
) -> FastAPI:
    """Create a viewer app limited to images named in the supplied manifest."""

    records, examples = _load_data(results_path, manifest_path, image_root)
    default_key = "baseline_2" if baseline1_results_path else "selected"
    runs: dict[str, dict[str, Any]] = {
        default_key: {
            "label": "Baseline 2" if baseline1_results_path else results_path.parent.name,
            "results_name": results_path.parent.name,
            "records": records,
            "generation_audits": _generation_audits(records),
        },
    }
    if baseline1_results_path is not None:
        prior_records, prior_examples = _load_data(baseline1_results_path, manifest_path, image_root)
        if prior_examples.keys() != examples.keys():
            raise ValueError("Baseline 1 and baseline 2 must use the same manifest")
        prior_audits = (
            _original_generation_audits(baseline1_generation_path, prior_records)
            if baseline1_generation_path is not None
            else _generation_audits(prior_records)
        )
        runs["baseline_1"] = {
            "label": "Baseline 1",
            "results_name": baseline1_results_path.parent.name,
            "records": prior_records,
            "generation_audits": prior_audits,
        }
    app = FastAPI(title="Speaker script baseline viewer", docs_url=None, redoc_url=None)
    app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")

    def selected_run(run: str | None) -> dict[str, Any]:
        key = run or default_key
        if key not in runs:
            raise HTTPException(status_code=404, detail="Unknown baseline run")
        return runs[key]

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(ASSETS / "index.html")

    @app.get("/api/runs")
    def list_runs() -> dict[str, Any]:
        return {
            "default_run": default_key,
            "runs": [
                {"key": key, "label": run["label"], "results_name": run["results_name"],
                 "count": len(run["records"])}
                for key, run in runs.items()
            ],
        }

    @app.get("/api/examples")
    def list_examples(run: str | None = None) -> dict[str, Any]:
        selected = selected_run(run)
        rows = []
        for example_id, record in selected["records"].items():
            dimensions = record["evaluation"]["dimensions"]
            rows.append({
                "example_id": example_id,
                "deck_id": record["deck_id"],
                "slide_number": record["slide_number"],
                "position": record.get("position"),
                "slide_type": record.get("slide_type"),
                "score": record["score"],
                "ratings": {
                    name: dimensions[name]["score"] if dimensions[name]["applicable"] else None
                    for name in DIMENSION_NAMES
                },
            })
        return {"results_name": selected["results_name"], "count": len(rows), "examples": rows}

    @app.get("/api/examples/{example_id}")
    def get_example(example_id: str, run: str | None = None) -> dict[str, Any]:
        selected = selected_run(run)
        record = selected["records"].get(example_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Unknown example")
        example = examples[example_id]
        generation_audit = selected["generation_audits"].get(example_id)
        evaluation_audit = next(
            (item for item in record.get("request_audit", []) if item.get("stage") == "evaluation"),
            None,
        )
        run_key = run or default_key
        return {
            "run": run_key,
            "example_id": example_id,
            "deck_id": record["deck_id"],
            "slide_number": record["slide_number"],
            "position": record.get("position"),
            "slide_type": record.get("slide_type"),
            "score": record["score"],
            "script": record["script"],
            "evaluation": record["evaluation"],
            "evaluation_model": evaluation_audit.get("model") if evaluation_audit else None,
            "dimension_order": DIMENSION_NAMES,
            "images": {
                role: f"/api/images/{example_id}/{role}?run={run_key}" if getattr(example, field) is not None else None
                for role, field in IMAGE_FIELDS.items()
            },
            "generation": {
                "source": (
                    "original generator request" if generation_audit and run_key == "baseline_1"
                    else "recorded request" if generation_audit
                    else "manifest fallback; request unavailable"
                ),
                "provider": generation_audit.get("provider") if generation_audit else None,
                "model": generation_audit.get("model") if generation_audit else None,
                "settings": generation_audit.get("settings") if generation_audit else None,
                "parameters": _prompt_parameters(generation_audit, example),
                "system_text": generation_audit.get("system_text") if generation_audit else None,
                "user_content": generation_audit.get("user_content") if generation_audit else None,
            },
        }

    @app.get("/api/images/{example_id}/{role}")
    def get_image(example_id: str, role: str, run: str | None = None) -> FileResponse:
        selected = selected_run(run)
        example = examples.get(example_id)
        field = IMAGE_FIELDS.get(role)
        if example_id not in selected["records"] or example is None or field is None:
            raise HTTPException(status_code=404, detail="Unknown slide image")
        path = getattr(example, field)
        if path is None:
            raise HTTPException(status_code=404, detail="Slide image not provided")
        audit = selected["generation_audits"].get(example_id)
        if audit:
            logged = next((block for block in audit.get("user_content", []) if block.get("type") == "image" and Path(block["path"]).resolve() == path), None)
            if logged and hashlib.sha256(path.read_bytes()).hexdigest() != logged["sha256"]:
                raise HTTPException(status_code=409, detail="Slide image changed since the generator request")
        return FileResponse(path)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--baseline-1-results", type=Path, default=DEFAULT_BASELINE_1_RESULTS)
    parser.add_argument("--baseline-1-generation", type=Path, default=DEFAULT_BASELINE_1_GENERATION)
    parser.add_argument("--single-run", action="store_true", help="Show only --results")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--image-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    parser.add_argument("--host", default="127.0.0.1", help="Local interface; default 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    app = create_app(
        args.results, args.manifest, args.image_root,
        baseline1_results_path=None if args.single_run else args.baseline_1_results,
        baseline1_generation_path=None if args.single_run else args.baseline_1_generation,
    )
    print(f"Open http://{args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
