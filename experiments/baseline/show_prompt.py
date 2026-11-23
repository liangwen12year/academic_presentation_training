"""Show the recorded model requests for a completed baseline example; no API calls."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def load_record(path: Path, example_id: str | None) -> dict[str, Any]:
    """Find one result without loading all image or evaluation data into memory."""

    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            record = json.loads(line)
            if example_id is None or record.get("example_id") == example_id:
                return record
    raise ValueError(f"No matching result in {path}: {example_id or 'first result'}")


def format_request(audit: dict[str, Any]) -> str:
    """Render one audited request with image paths in place of base64 payloads."""

    lines = [
        f"=== {audit['stage'].upper()} | {audit['provider']} | {audit['model']} ===",
        "Settings: " + json.dumps(audit["settings"], ensure_ascii=False),
    ]
    if audit.get("output_schema"):
        lines.append("Structured output schema: " + json.dumps(audit["output_schema"]))
    lines.extend(["", "SYSTEM MESSAGE", audit["system_text"], "", "USER MESSAGE (ordered content blocks)"])
    for index, block in enumerate(audit["user_content"], start=1):
        if block["type"] == "text":
            lines.extend([f"[{index}] text", block["text"]])
        elif block["type"] == "image":
            path = Path(block["path"])
            if path.is_file():
                actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                status = "matches recorded SHA-256" if actual_hash == block["sha256"] else "CHANGED since request"
            else:
                status = "file unavailable"
            lines.append(
                f"[{index}] image: {path} ({block['media_type']}, {block['bytes']} bytes, "
                f"SHA-256 {block['sha256']}; {status})"
            )
        else:
            raise ValueError(f"Unexpected audited block type: {block['type']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True, help="Baseline evaluations.jsonl")
    parser.add_argument("--example-id", help="Example ID to inspect; defaults to the first completed example")
    parser.add_argument("--stage", choices=("generation", "evaluation", "both"), default="both")
    parser.add_argument("--list", action="store_true", help="List completed example IDs")
    args = parser.parse_args()

    if args.list:
        with args.results.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    print(json.loads(line)["example_id"])
        return

    record = load_record(args.results, args.example_id)
    audits = record.get("request_audit")
    if not audits:
        raise SystemExit("This result has no request audit; use a run made with the updated baseline runner")
    selected = [audit for audit in audits if args.stage == "both" or audit["stage"] == args.stage]
    if not selected:
        raise SystemExit(f"No {args.stage} request audit for {record['example_id']}")
    print(f"Example: {record['example_id']}")
    print("Recorded application-level SDK arguments; image payloads are shown as paths and hashes.\n")
    print("\n\n".join(format_request(audit) for audit in selected))


if __name__ == "__main__":
    main()
