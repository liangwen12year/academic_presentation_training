"""Export saved baseline request audits into per-slide prompt logs; no API calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from experiments.baseline.run_baseline import write_request_log


def load_audits(results_path: Path) -> list[dict[str, Any]]:
    """Validate all completed records before writing any log files."""

    audits: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    with results_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                raise ValueError(f"Blank result line {line_number}")
            record = json.loads(line)
            example_id = record.get("example_id")
            if not isinstance(example_id, str) or example_id in seen_ids:
                raise ValueError(f"Missing or duplicate example ID on line {line_number}")
            seen_ids.add(example_id)
            requests = record.get("request_audit")
            if not isinstance(requests, list) or len(requests) != 2:
                raise ValueError(f"Missing generation/evaluation audits for {example_id}")
            if [request.get("stage") for request in requests] != ["generation", "evaluation"]:
                raise ValueError(f"Unexpected request stage order for {example_id}")
            if any(request.get("example_id") != example_id for request in requests):
                raise ValueError(f"Request audit does not match result ID: {example_id}")
            audits.extend(requests)
    if not audits:
        raise ValueError(f"No results in {results_path}")
    return audits


def export_logs(results_path: Path, output_dir: Path) -> int:
    """Write one generator and one evaluator log pair per completed example."""

    audits = load_audits(results_path)
    for audit in audits:
        write_request_log(output_dir, audit)
    return len(audits) // 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True, help="Completed evaluations.jsonl")
    parser.add_argument("--output-dir", type=Path, help="Run directory; defaults to the results file's parent")
    args = parser.parse_args()
    output_dir = args.output_dir or args.results.parent
    count = export_logs(args.results, output_dir)
    print(f"Exported generator and evaluator prompt logs for {count} examples to {output_dir / 'log'}")


if __name__ == "__main__":
    main()
