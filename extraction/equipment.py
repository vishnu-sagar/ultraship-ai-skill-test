"""Code-enforced normalization applied to raw LLM output before schema
validation. This is deliberately NOT left purely to the prompt: a hardcoded
lookup means an unrecognized phrasing still maps deterministically instead of
depending on the model's judgment every time.
"""
from __future__ import annotations

from typing import Optional

_EQUIPMENT_SYNONYMS = {
    "van": "van", "dry van": "van", "dryvan": "van", "box truck": "van", "box": "van",
    "reefer": "reefer", "refrigerated": "reefer", "refrigerator": "reefer", "temp-controlled": "reefer",
    "flatbed": "flatbed", "flat bed": "flatbed", "flat": "flatbed", "stepdeck": "flatbed",
    "step deck": "flatbed", "lowboy": "flatbed", "rgn": "flatbed", "conestoga": "flatbed",
}


def normalize_equipment_type(raw: Optional[str]) -> Optional[str]:
    """Map a free-form equipment string to the closed schema enum.

    Returns None if raw is None/empty, the mapped enum value if recognized,
    or "other" if a value was given but isn't a known synonym -- never
    crashes and never invents a value that wasn't present.
    """
    if not raw:
        return None
    if raw in {"van", "reefer", "flatbed", "other"}:
        return raw
    cleaned = raw.strip().lower()
    return _EQUIPMENT_SYNONYMS.get(cleaned, "other")
