"""Business-rule validation for extracted rate confirmations.

Every check here is defensive: it inspects a plain dict (already schema-shaped)
and returns warning strings. Nothing raises -- the pipeline decides what to do
with the warnings (mainly: feed them into confidence scoring).
"""
from __future__ import annotations

import re
from typing import Optional

TOTAL_MISMATCH_TOLERANCE = 0.01

# Matches D/M/YY, D/M/YYYY, etc. where BOTH numbers could plausibly be a month
# (<=12), which is exactly the "3/4/26" ambiguity called out in the spec.
_AMBIGUOUS_NUMERIC_DATE_RE = re.compile(r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})$")


def find_missing_fields(data: dict, required_paths: list[str]) -> list[str]:
    """Return dotted paths (e.g. 'origin.city') that are null/empty."""
    missing = []
    for path in required_paths:
        parts = path.split(".")
        node = data
        for part in parts:
            node = node.get(part) if isinstance(node, dict) else None
        if node in (None, ""):
            missing.append(path)
    return missing


def check_conflicting_totals(data: dict) -> Optional[str]:
    """Flag when line_haul_rate + fuel_surcharge doesn't reconcile with total_rate.

    fuel_surcharge is treated as 0 when null (many carriers roll it into the
    base rate) but that relaxes the check, so an unreconciled total in that
    case is reported as a softer "unaccounted_charges" warning rather than a
    hard conflict -- there may be legitimate accessorial charges the schema
    doesn't have a field for (see sample LD64408: Base Rate + Carrier Charge).
    """
    total = data.get("total_rate")
    line_haul = data.get("line_haul_rate")
    fuel = data.get("fuel_surcharge")

    if total is None or line_haul is None:
        return None

    expected = line_haul + (fuel or 0)
    if abs(expected - total) <= TOTAL_MISMATCH_TOLERANCE:
        return None

    if fuel is None:
        return "unaccounted_charges"  # total includes charges beyond line haul that we can't attribute
    return "conflicting_totals"


def is_ambiguous_date_string(raw_date_str: str) -> bool:
    """True if a raw (pre-normalization) date string is genuinely ambiguous,
    e.g. '3/4/26' could be March 4 or April 3 with no other context.
    """
    match = _AMBIGUOUS_NUMERIC_DATE_RE.match(raw_date_str.strip())
    if not match:
        return False
    first, second, _year = match.groups()
    return int(first) <= 12 and int(second) <= 12 and int(first) != int(second)


def find_unverified_locations(data: dict, source_text: str) -> list[str]:
    """Code-enforced hallucination guard: on multi-stop documents the model
    has to pick which pickup is the "origin" and which drop is the
    "destination" -- that choice is still prompt-driven, but we can at least
    verify in code that the city it picked is actually mentioned somewhere in
    the source text, rather than trusting it blindly. Returns which of
    origin/destination failed that check.
    """
    unverified = []
    text_lower = source_text.lower()
    for role in ("origin", "destination"):
        city = (data.get(role) or {}).get("city")
        if city and city.lower() not in text_lower:
            unverified.append(role)
    return unverified


def validate(data: dict, source_text: Optional[str] = None) -> list[str]:
    """Run all checks and return a flat list of warning codes."""
    warnings: list[str] = []

    missing = find_missing_fields(data, [
        "load_id", "origin.city", "origin.state", "destination.city",
        "destination.state", "pickup_date", "total_rate", "equipment_type",
    ])
    if missing:
        warnings.append("missing_fields:" + ",".join(missing))

    total_flag = check_conflicting_totals(data)
    if total_flag:
        warnings.append(total_flag)

    if source_text is not None:
        unverified = find_unverified_locations(data, source_text)
        if unverified:
            warnings.append("unverified_location:" + ",".join(unverified))

    return warnings
