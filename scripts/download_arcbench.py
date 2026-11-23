#!/usr/bin/env python3
"""Download ArcBench slide and paper PDFs from their original source URLs.

The script fetches ArcBench's small CSV manifest from Hugging Face, then stores
the linked PDFs under data/slides/arcbench. Downloads are resumable: an existing
file is kept when it starts with the PDF signature.

ArcBench's MIT license covers its metadata and code. It does not automatically
cover the linked papers and slide decks, which remain subject to their original
authors' and hosts' terms.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


MANIFEST_URL = (
    "https://huggingface.co/datasets/ArcDeck/ArcBench/resolve/main/benchmark.csv"
)
DEFAULT_OUTPUT = Path("data/slides/arcbench")
PDF_MAGIC = b"%PDF"


def valid_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return path.stat().st_size > len(PDF_MAGIC) and handle.read(4) == PDF_MAGIC
    except OSError:
        return False


def run_curl(url: str, destination: Path) -> tuple[bool, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    command = [
        "curl",
        "-L",
        "--fail",
        "--silent",
        "--show-error",
        "--retry",
        "4",
        "--retry-delay",
        "2",
        "--retry-all-errors",
        "--connect-timeout",
        "30",
        "--max-time",
        "300",
        "--user-agent",
        "ArcBench-local-downloader/1.0",
        url,
        "-o",
        str(part),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        part.unlink(missing_ok=True)
        return False, result.stderr.strip() or f"curl exited {result.returncode}"
    if not valid_pdf(part):
        part.unlink(missing_ok=True)
        return False, "response was not a valid PDF"
    os.replace(part, destination)
    return True, ""


def fetch_manifest(url: str, destination: Path, refresh: bool) -> None:
    if destination.exists() and not refresh:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "curl",
        "-L",
        "--fail",
        "--silent",
        "--show-error",
        url,
        "-o",
        str(destination),
    ]
    subprocess.run(command, check=True)


def sanitize_title(title: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE)
    return cleaned.replace(" ", "_")


def filename(kind: str, index: int, row: dict[str, str]) -> str:
    title = sanitize_title(row["Paper Title"])
    return f"{kind}{index}_{title}_{row['Conference']}_{row['Year']}.pdf"


def parse_indices(value: str | None, row_count: int) -> list[int]:
    if value is None:
        return list(range(row_count))
    try:
        indices = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as error:
        raise SystemExit("--indices must contain comma-separated integers") from error
    invalid = [index for index in indices if not 0 <= index < row_count]
    if invalid:
        raise SystemExit(f"indices outside 0..{row_count - 1}: {invalid}")
    return indices


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest-url", default=MANIFEST_URL)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--type", choices=("slides", "papers", "both"), default="slides"
    )
    parser.add_argument("--indices", help="Comma-separated manifest row indices")
    parser.add_argument("--limit", type=int, help="Download only the first N rows")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--refresh-manifest", action="store_true")
    args = parser.parse_args()

    manifest = args.manifest or args.out / "benchmark.csv"
    if args.manifest is None:
        fetch_manifest(args.manifest_url, manifest, args.refresh_manifest)
    if not manifest.exists():
        raise SystemExit(f"manifest not found: {manifest}")

    with manifest.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {"Paper Title", "Conference", "Year", "Paper PDF URL", "Slides URL"}
    missing = required - set(rows[0] if rows else ())
    if missing:
        raise SystemExit(f"manifest is missing columns: {sorted(missing)}")

    indices = parse_indices(args.indices, len(rows))
    if args.limit is not None:
        if args.limit < 0:
            raise SystemExit("--limit must be non-negative")
        indices = indices[: args.limit]

    kinds = {
        "slides": (("slide", "Slides URL", "slides"),),
        "papers": (("paper", "Paper PDF URL", "papers"),),
        "both": (
            ("slide", "Slides URL", "slides"),
            ("paper", "Paper PDF URL", "papers"),
        ),
    }[args.type]
    jobs: list[tuple[int, str, str, Path]] = []
    for index in indices:
        for kind, url_column, directory in kinds:
            url = rows[index][url_column].strip()
            destination = args.out / directory / filename(kind, index, rows[index])
            jobs.append((index, kind, url, destination))

    results: list[dict[str, str | int]] = []

    def download_job(job: tuple[int, str, str, Path]) -> tuple[str, str]:
        _, _, url, destination = job
        if valid_pdf(destination):
            return "skipped", "already present"
        if not url:
            return "failed", "source URL is empty"
        succeeded, detail = run_curl(url, destination)
        return ("downloaded", "") if succeeded else ("failed", detail)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(download_job, job): job for job in jobs}
        for completed, future in enumerate(as_completed(futures), start=1):
            index, kind, url, destination = futures[future]
            status, detail = future.result()
            print(f"[{completed}/{len(jobs)}] {status.upper():10} {destination.name}")
            results.append(
                {
                    "index": index,
                    "type": kind,
                    "source_url": url,
                    "local_path": str(destination),
                    "status": status,
                    "detail": detail,
                }
            )

    results.sort(key=lambda item: (int(item["index"]), str(item["type"])))
    log_path = args.out / "download_results.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]) if results else [])
        if results:
            writer.writeheader()
            writer.writerows(results)

    failed = sum(result["status"] == "failed" for result in results)
    print(f"Finished {len(results)} files; {failed} failed. Log: {log_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
