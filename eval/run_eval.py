#!/usr/bin/env python
"""Eval harness implementing the Part 2 proposal in code: run the real
pipeline against hand-labeled ground truth and report per-field accuracy,
record-level accuracy, and confidence calibration.

Usage:
    python -m eval.run_eval                      # real Anthropic API
    python -m eval.run_eval --provider mock       # offline, no API key
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from extraction.email_utils import extract_text_from_eml
from extraction.pdf_utils import extract_text_from_pdf
from extraction.pipeline import extract

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = REPO_ROOT / "samples"
GROUND_TRUTH_PATH = Path(__file__).resolve().parent / "ground_truth.json"

NUMERIC_TOLERANCE = 0.01
NUMERIC_FIELDS = {"line_haul_rate", "fuel_surcharge", "total_rate", "weight_lbs"}


def _read_document_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(path)
    if suffix == ".eml":
        return extract_text_from_eml(path)
    return path.read_text()


def _get_field(data: dict, dotted_path: str):
    node = data
    for part in dotted_path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def _values_match(field: str, actual, expected) -> bool:
    if expected is None:
        return actual is None
    if field in NUMERIC_FIELDS:
        return actual is not None and abs(actual - expected) <= NUMERIC_TOLERANCE
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.strip().lower() == expected.strip().lower()
    return actual == expected


def _score_field(field: str, actual, spec) -> Optional[bool]:
    """Returns True/False, or None if the field is marked 'skip' (excluded)."""
    if isinstance(spec, dict) and spec.get("skip"):
        return None
    if isinstance(spec, dict) and "any_of" in spec:
        return any(_values_match(field, actual, option) for option in spec["any_of"])
    return _values_match(field, actual, spec)


def run_eval(provider: str) -> int:
    ground_truth = json.loads(GROUND_TRUTH_PATH.read_text())
    ground_truth.pop("_note", None)

    total_scored = 0
    total_correct = 0
    record_perfect = 0
    confidence_matches = 0
    high_confidence_records = 0
    high_confidence_all_correct = 0

    for filename, spec in ground_truth.items():
        path = SAMPLES_DIR / filename
        text = _read_document_text(path)
        result = extract(text, provider=provider)
        data = result.data

        print(f"\n--- {filename} ---")

        record_had_miss = False
        for field, field_spec in spec["fields"].items():
            actual = _get_field(data, field)
            outcome = _score_field(field, actual, field_spec)
            if outcome is None:
                reason = field_spec.get("reason", "ambiguous")
                print(f"  SKIP   {field}: ({reason})")
                continue
            total_scored += 1
            if outcome:
                total_correct += 1
                print(f"  PASS   {field}: {actual!r}")
            else:
                record_had_miss = True
                print(f"  FAIL   {field}: got {actual!r}, expected {field_spec!r}")

        if not record_had_miss:
            record_perfect += 1

        expected_confidence = spec["expected_confidence"]
        actual_confidence = data.get("confidence")
        if actual_confidence == expected_confidence:
            confidence_matches += 1
        print(f"  confidence: got {actual_confidence!r}, expected {expected_confidence!r}")

        if actual_confidence == "high":
            high_confidence_records += 1
            if not record_had_miss:
                high_confidence_all_correct += 1

    n = len(ground_truth)
    print("\n=== Summary ===")
    print(f"Records evaluated:        {n}")
    print(f"Per-field accuracy:       {total_correct}/{total_scored} "
          f"({100 * total_correct / total_scored:.1f}%)" if total_scored else "n/a")
    print(f"Record-level accuracy:    {record_perfect}/{n} ({100 * record_perfect / n:.1f}%)")
    print(f"Confidence label match:   {confidence_matches}/{n} ({100 * confidence_matches / n:.1f}%)")
    if high_confidence_records:
        print(f"'high' confidence calibration: {high_confidence_all_correct}/{high_confidence_records} "
              f"of 'high'-confidence records had every scored field correct "
              f"({100 * high_confidence_all_correct / high_confidence_records:.1f}%)")
    else:
        print("'high' confidence calibration: n/a (no 'high'-confidence records this run)")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider", default="anthropic", choices=["anthropic", "mock"],
        help="LLM provider to evaluate (default: anthropic).",
    )
    args = parser.parse_args()
    return run_eval(args.provider)


if __name__ == "__main__":
    raise SystemExit(main())
