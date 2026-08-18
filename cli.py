#!/usr/bin/env python
"""CLI entrypoint: extract structured JSON from a rate confirmation file.

Usage:
    python cli.py samples/rate_con_1_LD64392.pdf
    python cli.py samples/rate_con_5_email_body.eml
    python cli.py samples/*.pdf --provider mock   # offline, no API key needed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from extraction.email_utils import extract_text_from_eml
from extraction.pdf_utils import extract_text_from_pdf
from extraction.pipeline import extract


def _read_document_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(path)
    if suffix == ".eml":
        return extract_text_from_eml(path)
    return path.read_text()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="Path(s) to rate confirmation .pdf or .txt file(s)")
    parser.add_argument(
        "--provider", default="anthropic", choices=["anthropic", "mock"],
        help="LLM provider to use (default: anthropic). Use 'mock' to run offline without an API key.",
    )
    parser.add_argument("--show-warnings", action="store_true", help="Also print validation warnings")
    args = parser.parse_args()

    exit_code = 0
    for file_path in args.files:
        text = _read_document_text(Path(file_path))
        result = extract(text, provider=args.provider)
        if not result.ok:
            exit_code = 1
        output = dict(result.data)
        if args.show_warnings:
            output["_warnings"] = result.warnings
        print(f"--- {file_path} ---")
        print(json.dumps(output, indent=2))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
