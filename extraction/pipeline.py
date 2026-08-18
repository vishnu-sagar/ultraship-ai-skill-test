"""Orchestrates: LLM call -> schema validation (+ repair retry) -> business
rule validation -> confidence scoring.

The public contract is `extract()`, which NEVER raises and NEVER returns
malformed data -- worst case it returns an all-null, "low" confidence result
plus diagnostics explaining why.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .confidence import compute_confidence
from .equipment import normalize_equipment_type
from .llm_client import AnthropicExtractor, LLMError
from .mock_llm import MockExtractor
from .schema import empty_result, safe_parse
from .validators import validate

MAX_REPAIR_ATTEMPTS = 2


@dataclass
class ExtractionResult:
    data: dict
    warnings: list[str] = field(default_factory=list)
    attempts: int = 1
    ok: bool = True


def _get_client(provider: str, **kwargs):
    if provider == "anthropic":
        return AnthropicExtractor(**kwargs)
    if provider == "mock":
        return MockExtractor()
    raise ValueError(f"Unknown provider: {provider!r}")


def extract(document_text: str, provider: str = "anthropic", **client_kwargs) -> ExtractionResult:
    client = _get_client(provider, **client_kwargs)

    parsed = None
    repair_note = None
    last_error = "unknown error"
    attempts = 0

    for attempts in range(1, MAX_REPAIR_ATTEMPTS + 2):  # 1 initial + N repairs
        try:
            raw = client.extract_raw(document_text, repair_note=repair_note)
        except LLMError as e:
            last_error = str(e)
            break  # transport/auth failures are not worth retrying blindly

        if isinstance(raw, dict):
            # Code-enforced normalization, not left purely to prompt compliance.
            raw["equipment_type"] = normalize_equipment_type(raw.get("equipment_type"))

        model, errors = safe_parse(raw)
        if model is not None:
            parsed = model
            break

        last_error = "; ".join(errors)
        repair_note = f"schema validation failed: {last_error}"

    if parsed is None:
        return ExtractionResult(
            data=empty_result(),
            warnings=[f"extraction_failed:{last_error}"],
            attempts=attempts,
            ok=False,
        )

    data = parsed.model_dump()
    warnings = validate(data, source_text=document_text)
    used_repair = attempts > 1
    data["confidence"] = compute_confidence(data, warnings, used_repair_retry=used_repair)

    return ExtractionResult(data=data, warnings=warnings, attempts=attempts, ok=True)
