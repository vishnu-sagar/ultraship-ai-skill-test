"""Deterministic, regex-based stand-in for the LLM, used only for offline
tests and local development without an API key (provider="mock").

This is NOT the submission's extraction strategy -- it exists so the schema
enforcement, validation, and confidence layers can be exercised in CI without
network access or a paid API call. The real path is AnthropicExtractor.
"""
from __future__ import annotations

import re
from typing import Optional


def _search(pattern: str, text: str, group: int = 1) -> Optional[str]:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(group).strip() if m else None


def _to_number(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    cleaned = raw.replace("$", "").replace(",", "").replace("USD", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


_MONTH_ABBR = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def _normalize_date(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    raw = raw.strip()

    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})$", raw)  # 28-Jul-2026
    if m:
        day, mon, year = m.groups()
        return f"{year}-{_MONTH_ABBR.get(mon.lower(), '01')}-{int(day):02d}"

    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", raw)  # 07/30/2026 (assume MM/DD/YYYY)
    if m:
        mon, day, year = m.groups()
        year = year if len(year) == 4 else f"20{year}"
        return f"{year}-{int(mon):02d}-{int(day):02d}"

    return None


class MockExtractor:
    """Same interface as AnthropicExtractor.extract_raw, no network calls."""

    def extract_raw(self, document_text: str, repair_note: Optional[str] = None) -> dict:
        text = document_text

        load_id = _search(r"Reference ID:?\s*([A-Za-z0-9\-]+)", text) or _search(
            r"Load #:?\s*([A-Za-z0-9\-]+)", text
        )

        equipment_raw = (_search(r"EQUIPMENT:?\s*([A-Za-z ]+)", text) or "").lower()
        equipment_map = {"flatbed": "flatbed", "reefer": "reefer", "van": "van"}
        equipment_type = next((v for k, v in equipment_map.items() if k in equipment_raw), None)
        if equipment_type is None:
            # Real PDF-extracted text often separates the "EQUIPMENT" column
            # header from its value (table layout collapses oddly), so fall
            # back to a bare keyword search anywhere in the document.
            keyword_match = re.search(r"\b(flatbed|reefer|van)\b", text, re.IGNORECASE)
            equipment_type = equipment_map.get(keyword_match.group(1).lower()) if keyword_match else None

        pickup_raw = _search(r"Shipping Date & Time:?\s*([0-9/\-A-Za-z]+)", text) or _search(
            r"Pickup Date:?\s*([0-9/\-A-Za-z]+)", text
        )
        delivery_raw = _search(r"Delivery Date & Time:?\s*([0-9/\-A-Za-z]+)", text)

        line_haul = _to_number(
            _search(r"Base Carrier Rate:?\s*([\d,.$]+)", text)
            or _search(r"Line Haul:?\s*([\d,.$]+)", text)
        )
        fuel_surcharge = _to_number(_search(r"Fuel Surcharge:?\s*([\d,.$]+)", text))
        total_rate = _to_number(
            _search(r"Total(?: Rate Due)?:?\s*([\d,.$]+)", text)
        )
        weight_lbs = _to_number(_search(r"Weight:?\s*([\d,.]+)\s*lbs", text))
        commodity = _search(r"Commodity:?\s*([A-Za-z ]+)", text)

        origin_city, origin_state = None, None
        dest_city, dest_state = None, None
        pickup_match = re.search(r"Pickup:?\s*([A-Za-z .]+),\s*([A-Z]{2})\b", text)
        if pickup_match:
            origin_city, origin_state = pickup_match.group(1).strip(), pickup_match.group(2)
        stop_city_match = re.search(
            r"([A-Za-z .]+),\s*([A-Z]{2})\s*\d{0,5}(?:-\d{4})?,\s*USA", text
        )
        if stop_city_match and origin_city is None:
            origin_city, origin_state = stop_city_match.group(1).strip(), stop_city_match.group(2)

        return {
            "load_id": load_id,
            "origin": {"city": origin_city, "state": origin_state, "zip": None},
            "destination": {"city": dest_city, "state": dest_state, "zip": None},
            "pickup_date": _normalize_date(pickup_raw),
            "delivery_date": _normalize_date(delivery_raw),
            "equipment_type": equipment_type,
            "line_haul_rate": line_haul,
            "fuel_surcharge": fuel_surcharge,
            "total_rate": total_rate,
            "weight_lbs": weight_lbs,
            "commodity": commodity,
        }
