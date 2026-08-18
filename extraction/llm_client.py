"""Anthropic-backed extraction client.

Uses tool-use (forced tool_choice) instead of free-form JSON parsing -- Claude
must fill in a JSON-schema-shaped tool input, which removes most of the "model
wrapped the JSON in prose" failure mode. We still treat the result as
untrusted input and re-validate it against our own pydantic schema afterward.
"""
from __future__ import annotations

import os
from typing import Optional

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

_TOOL_NAME = "emit_rate_confirmation"

SYSTEM_PROMPT = """You are a freight document extraction assistant for a Transportation \
Management System. You will be given the raw text of a carrier rate confirmation \
(extracted from a PDF or email, so formatting/line breaks may be irregular).

Extract ONLY facts that are explicitly present in the text. Rules:
- Never guess or fabricate a value. If a field is not present, or you are not sure, \
use null.
- Dates: normalize to YYYY-MM-DD. If a date is ambiguous (e.g. numeric with both parts \
<=12, like "3/4/26", and there is no other context such as a month name, day-of-week, \
or an unambiguous sibling date to infer the format from), still produce your best \
guess assuming US convention (MM/DD/YYYY) but do not invent a date that is not written \
in the source text.
- equipment_type must be one of "van", "reefer", "flatbed", "other", or null. Map \
synonyms (e.g. "Dry Van" -> "van", "Reefer"/"Refrigerated" -> "reefer").
- Money fields are numbers (no currency symbols, no commas).
- line_haul_rate is the base/line-haul carrier rate. fuel_surcharge is only filled in \
if the source text explicitly itemizes a fuel surcharge/FSC line -- do NOT lump other \
accessorial or carrier charges into fuel_surcharge just to make totals reconcile.
- Do not fill in a "confidence" value; that is computed separately.
"""

_LOCATION_SCHEMA = {
    "type": "object",
    "properties": {
        "city": {"type": ["string", "null"]},
        "state": {"type": ["string", "null"]},
        "zip": {"type": ["string", "null"]},
    },
    "required": ["city", "state", "zip"],
}


def _build_tool_schema() -> dict:
    return {
        "name": _TOOL_NAME,
        "description": "Emit the structured fields extracted from the rate confirmation document.",
        "input_schema": {
            "type": "object",
            "properties": {
                "load_id": {"type": ["string", "null"]},
                "origin": _LOCATION_SCHEMA,
                "destination": _LOCATION_SCHEMA,
                "pickup_date": {"type": ["string", "null"], "description": "YYYY-MM-DD or null"},
                "delivery_date": {"type": ["string", "null"], "description": "YYYY-MM-DD or null"},
                "equipment_type": {
                    "type": ["string", "null"],
                    "enum": ["van", "reefer", "flatbed", "other", None],
                },
                "line_haul_rate": {"type": ["number", "null"]},
                "fuel_surcharge": {"type": ["number", "null"]},
                "total_rate": {"type": ["number", "null"]},
                "weight_lbs": {"type": ["number", "null"]},
                "commodity": {"type": ["string", "null"]},
            },
            "required": [
                "load_id", "origin", "destination", "pickup_date", "delivery_date",
                "equipment_type", "line_haul_rate", "fuel_surcharge", "total_rate",
                "weight_lbs", "commodity",
            ],
        },
    }


class LLMError(Exception):
    """Raised for any LLM call failure (auth, network, rate limit, bad response shape)."""


def _build_user_prompt(document_text: str, repair_note: Optional[str]) -> str:
    prompt = f"Rate confirmation document text:\n---\n{document_text}\n---\n"
    if repair_note:
        prompt += (
            f"\nYour previous attempt was invalid: {repair_note}\n"
            "Call the tool again with corrected values."
        )
    return prompt


class AnthropicExtractor:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        max_retries: int = 5,
        timeout: float = 30.0,
    ):
        # max_retries/timeout are passed straight through to the SDK, which
        # already retries connection errors, 408/409, 429 (rate limit), and
        # 5xx responses with exponential backoff + jitter. We just make that
        # explicit and tunable instead of relying on its default of 2.
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise LLMError("The 'anthropic' package is not installed") from e
        self._client = Anthropic(api_key=api_key, max_retries=max_retries, timeout=timeout)
        self._model = model

    def extract_raw(self, document_text: str, repair_note: Optional[str] = None) -> dict:
        user_content = _build_user_prompt(document_text, repair_note)
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                temperature=0,
                system=SYSTEM_PROMPT,
                tools=[_build_tool_schema()],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as e:
            # The SDK already exhausted its own retries/backoff for transient
            # errors (429/5xx/connection) by the time this is raised -- this
            # is a final, non-retryable failure from the pipeline's point of view.
            raise LLMError(f"Anthropic API call failed: {e}") from e

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == _TOOL_NAME:
                return block.input
        raise LLMError("Model response did not include the expected tool_use block")
