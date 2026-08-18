"""Deterministic confidence scoring.

This is the "real logic, not vibes" required by the spec: confidence is a
function of (a) how complete the critical fields are, (b) whether validation
raised any red flags, and (c) whether the model needed a repair retry to
produce valid JSON at all. No field of this logic comes from asking the LLM
"how confident are you" -- self-reported LLM confidence is not calibrated and
is explicitly not trusted here.
"""
from __future__ import annotations

from .schema import REQUIRED_FOR_AUTO_BOOK
from .validators import find_missing_fields

# Warnings that are severe enough to force "low" regardless of completeness --
# these represent cases where auto-booking could move real freight on bad data.
HARD_FAIL_WARNINGS = {"conflicting_totals"}


def score_completeness(data: dict) -> float:
    missing = find_missing_fields(data, REQUIRED_FOR_AUTO_BOOK)
    return 1 - (len(missing) / len(REQUIRED_FOR_AUTO_BOOK))


def compute_confidence(data: dict, warnings: list[str], used_repair_retry: bool) -> str:
    completeness = score_completeness(data)
    warning_codes = {w.split(":", 1)[0] for w in warnings}

    if warning_codes & HARD_FAIL_WARNINGS:
        return "low"
    if completeness < 0.5:
        return "low"

    soft_flags = bool(warning_codes - HARD_FAIL_WARNINGS) or used_repair_retry
    if soft_flags or completeness < 0.85:
        return "medium"

    return "high"
