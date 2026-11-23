#!/usr/bin/env python3
"""Download selected MIT OpenCourseWare slide decks and record metadata.

The downloader discovers PDF links from four course slide-index pages instead
of maintaining a copy of the PDFs in Git. Poppler's ``pdfinfo`` and
``pdftotext`` are used when available to record page counts and whether text
extraction succeeds.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse


LICENSE = "CC BY-NC-SA 4.0"
LICENSE_URL = "https://ocw.mit.edu/pages/privacy-and-terms-of-use/"
DEFAULT_OUTPUT = Path("data/slides/mit_ocw")
PDF_MAGIC = b"%PDF"


@dataclass(frozen=True)
class Course:
    directory: str
    code: str
    title: str
    domain: str
    instructors: str
    source_page: str


COURSES = (
    Course(
        "6_0001_intro_cs_python",
        "6.0001",
        "Introduction to Computer Science and Programming in Python",
        "Computer Science / Programming",
        "Dr. Ana Bell; Prof. Eric Grimson; Prof. John Guttag",
        "https://ocw.mit.edu/courses/6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016/pages/lecture-slides-code/",
    ),
    Course(
        "cms_595_learning_media_technology",
        "CMS.595",
        "Learning, Media, and Technology",
        "Education / Learning Sciences / Media Technology",
        "Prof. Justin Reich",
        "https://ocw.mit.edu/courses/cms-595-learning-media-and-technology-spring-2024/lists/lecture-slides/",
    ),
    Course(
        "6_011_signals_systems_inference",
        "6.011",
        "Signals, Systems and Inference",
        "Electrical Engineering / Signals and Systems",
        "Prof. George Verghese; Prof. Alan V. Oppenheim; Prof. Peter Hagelstein",
        "https://ocw.mit.edu/courses/6-011-signals-systems-and-inference-spring-2018/pages/lecture-slides/",
    ),
    Course(
        "21h_336_roman_emperor",
        "21H.336",
        "The Making of a Roman Emperor",
        "History / Roman History",
        "Prof. William Broadhead",
        "https://ocw.mit.edu/courses/21h-336-the-making-of-a-roman-emperor-spring-2023/lists/lecture-slides/",
    ),
)


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def curl_bytes(url: str) -> bytes:
    command = [
        "curl",
        "-L",
        "--fail",
        "--silent",
        "--show-error",
        "--retry",
        "4",
        "--retry-all-errors",
        "--connect-timeout",
        "30",
        "--max-time",
        "300",
        url,
    ]
    return subprocess.run(command, check=True, capture_output=True).stdout


def discover_pdfs(source_page: str) -> list[str]:
    parser = LinkParser()
    parser.feed(curl_bytes(source_page).decode("utf-8", errors="replace"))
    urls = {
        urljoin(source_page, href)
        for href in parser.links
        if urlparse(urljoin(source_page, href)).path.lower().endswith(".pdf")
    }
    return sorted(urls)


def clean_filename(url: str) -> str:
    name = unquote(Path(urlparse(url).path).name)
    return re.sub(r"^[0-9a-f]{32}_", "", name, flags=re.IGNORECASE)


def valid_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return path.stat().st_size > len(PDF_MAGIC) and handle.read(4) == PDF_MAGIC
    except OSError:
        return False


def download(url: str, destination: Path) -> str:
    if valid_pdf(destination):
        return "skipped"
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    part.write_bytes(curl_bytes(url))
    if not valid_pdf(part):
        part.unlink(missing_ok=True)
        raise RuntimeError(f"download did not produce a valid PDF: {url}")
    os.replace(part, destination)
    return "downloaded"


def inspect_pdf(path: Path) -> tuple[int | None, bool | None, int | None]:
    if not shutil.which("pdfinfo") or not shutil.which("pdftotext"):
        return None, None, None

    info = subprocess.run(
        ["pdfinfo", str(path)], capture_output=True, text=True, check=False
    )
    pages = None
    if info.returncode == 0:
        match = re.search(r"^Pages:\s+(\d+)$", info.stdout, re.MULTILINE)
        pages = int(match.group(1)) if match else None

    text = subprocess.run(
        ["pdftotext", str(path), "-"], capture_output=True, check=False
    )
    characters = len(text.stdout.decode("utf-8", errors="replace").strip())
    return pages, text.returncode == 0 and characters > 0, characters


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--courses",
        help="Comma-separated course codes; default: all configured courses",
    )
    args = parser.parse_args()

    selected_codes = (
        {code.strip().lower() for code in args.courses.split(",")}
        if args.courses
        else None
    )
    selected = [
        course
        for course in COURSES
        if selected_codes is None or course.code.lower() in selected_codes
    ]
    if not selected:
        raise SystemExit("no configured courses matched --courses")

    records: list[dict[str, object]] = []
    for course in selected:
        urls = discover_pdfs(course.source_page)
        if not urls:
            raise RuntimeError(f"no PDF links found on {course.source_page}")
        print(f"{course.code}: found {len(urls)} PDFs")
        course_records: list[dict[str, object]] = []
        for index, url in enumerate(urls, start=1):
            destination = args.out / course.directory / clean_filename(url)
            status = download(url, destination)
            pages, extracted, characters = inspect_pdf(destination)
            print(f"  [{index}/{len(urls)}] {status.upper():10} {destination.name}")
            record: dict[str, object] = {
                "file_name": destination.name,
                "local_path": str(destination),
                "source_url": url,
                "source_page_url": course.source_page,
                "course_code": course.code,
                "course_title": course.title,
                "course_domain": course.domain,
                "author_instructor": course.instructors,
                "license": LICENSE,
                "license_url": LICENSE_URL,
                "file_format": "PDF",
                "download_date": date.today().isoformat(),
                "number_of_slides": pages,
                "text_extraction_succeeded": extracted,
                "extracted_text_characters": characters,
            }
            records.append(record)
            course_records.append(record)

        course_manifest = args.out / course.directory / "metadata.csv"
        write_csv(course_manifest, course_records)

    write_csv(args.out / "metadata.csv", records)
    with (args.out / "metadata.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = {
        "download_date": date.today().isoformat(),
        "course_count": len(selected),
        "pdf_count": len(records),
        "slide_count": sum(
            int(record["number_of_slides"] or 0) for record in records
        ),
        "text_extraction_success_count": sum(
            record["text_extraction_succeeded"] is True for record in records
        ),
    }
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


def write_csv(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


if __name__ == "__main__":
    raise SystemExit(main())
