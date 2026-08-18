"""Pydantic schema for the rate confirmation extraction output.

Note: `confidence` is intentionally NOT filled in by the LLM. It is computed
deterministically by `extraction.confidence` from validation results, because
the spec requires "real logic, not vibes" for trust decisions.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError, field_validator

EquipmentType = Literal["van", "reefer", "flatbed", "other"]
ConfidenceLevel = Literal["high", "medium", "low"]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Location(BaseModel):
    # city/state are relaxed to Optional so a genuinely missing location never
    # crashes the pipeline -- it just surfaces as a missing-field warning instead.
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None


class RateConfirmation(BaseModel):
    load_id: Optional[str] = None
    origin: Location = Location()
    destination: Location = Location()
    pickup_date: Optional[str] = None
    delivery_date: Optional[str] = None
    equipment_type: Optional[EquipmentType] = None
    line_haul_rate: Optional[float] = None
    fuel_surcharge: Optional[float] = None
    total_rate: Optional[float] = None
    weight_lbs: Optional[float] = None
    commodity: Optional[str] = None
    confidence: ConfidenceLevel = "low"

    @field_validator("pickup_date", "delivery_date")
    @classmethod
    def _validate_iso_date(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _DATE_RE.match(v):
            raise ValueError(f"date must be YYYY-MM-DD, got {v!r}")
        return v


# Fields used to judge "is this extraction complete enough to trust".
REQUIRED_FOR_AUTO_BOOK = [
    "load_id",
    "origin.city",
    "origin.state",
    "destination.city",
    "destination.state",
    "pickup_date",
    "total_rate",
    "equipment_type",
]


def safe_parse(raw: dict) -> tuple[Optional[RateConfirmation], list[str]]:
    """Validate `raw` against the schema.

    Never raises. Returns (model_or_None, errors). On failure the caller is
    expected to retry with a repair prompt or fall back to an all-null result.
    """
    try:
        return RateConfirmation.model_validate(raw), []
    except ValidationError as e:
        return None, [str(err) for err in e.errors()]


def empty_result() -> dict:
    """A safe, schema-shaped fallback (all nulls, low confidence) used when
    extraction fails outright. Keeps the output contract exact -- callers that
    need the failure reason should read it from the pipeline's diagnostics,
    not from this dict.
    """
    result = RateConfirmation().model_dump()
    result["confidence"] = "low"
    return result
