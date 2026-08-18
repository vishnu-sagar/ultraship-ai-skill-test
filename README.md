# UltraShip Skill Test — Part 1: Document Extraction

A small, dependency-light pipeline that turns the raw text of a freight rate
confirmation into the structured JSON schema specified in the take-home.

> Part 2 (Evaluation & Reliability) is answered in
> [PART2-EVALUATION-AND-RELIABILITY.md](PART2-EVALUATION-AND-RELIABILITY.md).

## How each spec requirement is met

**1. "Use an LLM API of your choice (Anthropic, OpenAI, or local model)."**
Anthropic Claude (`claude-sonnet-4-5-20250929`), via [`extraction/llm_client.py`](extraction/llm_client.py).
The call uses forced tool-use (`tool_choice={"type": "tool", ...}`) so the
model must respond by filling in a JSON-schema-shaped tool input rather than
writing free-form JSON in prose — this removes most of the "model wrapped the
JSON in markdown/explanation text" failure mode before it can even happen.

**2. "Enforce the schema — malformed model output should never crash the
pipeline or silently produce bad data."**
Four layers, in [`extraction/pipeline.py`](extraction/pipeline.py) and
[`extraction/schema.py`](extraction/schema.py):
- Structured tool-use output (above) reduces malformed output at the source.
- The result is still treated as untrusted and independently re-validated
  against a `pydantic` model (`safe_parse`), which **never raises** — it
  returns `(None, errors)` on failure instead of throwing.
- If validation fails, the errors are fed back to the model as a repair
  prompt and retried (bounded, `MAX_REPAIR_ATTEMPTS = 2`).
- If it still fails (or the API call itself errors — auth/network/rate
  limit), the pipeline returns an explicit, schema-shaped, all-null result
  with `confidence: "low"` — never a crash, never a guess.

**3. "Implement the confidence field with real logic, not vibes... how you
decide when extraction is trustworthy enough to auto-populate a load vs.
flag for human review."**
See "Confidence field: how it's decided" below for the full rule. Short
version: `confidence` is computed deterministically in
[`extraction/confidence.py`](extraction/confidence.py) from field
completeness + validation warnings + whether a repair retry was needed — it
is never self-reported by the LLM, because LLM self-reported confidence
isn't calibrated. **Only `high` should auto-populate a load without review;
`medium` and `low` should be routed to a human-in-the-loop queue.**

**4. "Handle at least these failure cases explicitly: missing fields,
conflicting totals (line haul + fuel ≠ total), and dates written
ambiguously (e.g., '3/4/26')."**
See "Failure cases handled explicitly" below for the full list (this also
covers two extra cases beyond the minimum: equipment-type synonyms and
hallucinated origin/destination on multi-stop docs). Short version:
- Missing fields → `find_missing_fields` walks dotted paths and downgrades confidence.
- Conflicting totals → `check_conflicting_totals`; a real mismatch forces `confidence: low`.
- Ambiguous dates → `is_ambiguous_date_string` detects e.g. `3/4/26` and the
  prompt resolves it via US `MM/DD/YYYY` convention rather than inventing an
  unstated date.

## Layout

```
samples/                    3 real sample rate confirmations, as actual PDFs
                             (split from the original take-home PDF's pages) +
                             1 synthetic edge-case .txt fixture +
                             2 synthetic .eml fixtures (body-only, and body +
                             PDF attachment -- the common "see attached" case)
extraction/
  schema.py                 pydantic schema + safe_parse() (never raises)
  llm_client.py              Anthropic client, forced tool-use for structured output
  mock_llm.py                offline regex stand-in used only by tests (no API key)
  pdf_utils.py                 PDF -> raw text (pypdf), since brokers receive real PDFs
  email_utils.py               .eml -> raw text, incl. text from any PDF attachments
  equipment.py                 hardcoded equipment-type synonym normalization
  validators.py              business-rule checks (missing fields, conflicting totals,
                             ambiguous dates, unverified locations)
  confidence.py               deterministic confidence scoring
  pipeline.py                 orchestrates client -> schema -> validators -> confidence
cli.py                       run extraction from the command line (.pdf / .eml / .txt)
tests/                       unit tests (run offline via the mock provider)
```

## Running it

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-...
python cli.py samples/rate_con_1_LD64392.pdf --show-warnings
python cli.py samples/rate_con_6_email_with_pdf_attachment.eml --show-warnings

# or fully offline, no API key, for a quick smoke test:
python cli.py samples/rate_con_2_LD64408.pdf --provider mock --show-warnings

python -m unittest discover -s tests -v
```

## Prompt design

The system prompt instructs the model to:
- Only extract facts explicitly present in the text — never guess or fabricate.
- Normalize dates to `YYYY-MM-DD`, defaulting to US `MM/DD/YYYY` convention for
  ambiguous numeric dates (e.g. `3/4/26`), but never invent a date not present.
- Map equipment synonyms (`Dry Van` → `van`, `Refrigerated` → `reefer`) to the
  closed enum.
- Only populate `fuel_surcharge` when a fuel/FSC line is explicitly itemized —
  it must not lump other accessorial charges in just to make totals reconcile
  (see "conflicting totals" below).
- **Not** self-report a `confidence` value. LLM self-reported confidence is not
  calibrated, so that field is computed deterministically by our own code
  instead (see below).

## Schema enforcement strategy

1. **Structured output, not free-form JSON parsing.** The Anthropic call uses
   forced tool-use (`tool_choice={"type": "tool", "name": ...}`) with a JSON
   schema for the tool input. This removes most of the "model wrapped the
   JSON in markdown/prose" failure mode.
2. **Independent re-validation.** The tool call's output is still treated as
   untrusted input and re-validated against our own `pydantic` model
   (`schema.py`). A model that technically respects the tool schema could
   still emit a bad enum value or a non-ISO date string; pydantic catches
   that (`safe_parse` never raises — it returns `(None, errors)`).
3. **Repair retries.** If validation fails, we send the validation errors back
   to the model as a repair prompt and retry (bounded, `MAX_REPAIR_ATTEMPTS =
   2`). If it still fails, or the API call itself errors out (auth, network,
   rate limit), the pipeline returns an all-null, schema-shaped fallback
   result with `confidence: "low"` — **it never raises or crashes the caller**,
   and never silently fabricates data.

## Confidence field: how it's decided

`confidence.py` computes confidence deterministically from three signals, not
from asking the model:

1. **Completeness** — fraction of fields we consider load-critical for
   auto-booking (`load_id`, origin city/state, destination city/state,
   `pickup_date`, `total_rate`, `equipment_type`) that are actually populated.
2. **Validation flags** — anything `validators.py` raised (missing fields,
   conflicting/unaccounted totals).
3. **Whether a repair retry was needed** to get valid output at all.

Rule (see `compute_confidence`):
- Any **hard-fail** flag (`conflicting_totals` — a real line-haul+fuel vs.
  total mismatch) → always `low`, regardless of completeness. This is the
  cost-asymmetry-driven design: a load that auto-books on a wrong rate is far
  worse than one flagged for review.
- Completeness `< 0.5` → `low`.
- Any soft flag (missing non-critical field, unaccounted charges, a repair
  retry was needed) or completeness `< 0.85` → `medium`.
- Otherwise → `high`.

**Only `high` should auto-populate a load without review; `medium` and `low`
should be routed to a human-in-the-loop queue.** `medium` is deliberately a
large bucket — anything even slightly off should be reviewed rather than risk
booking real freight on a bad number.

## Failure cases handled explicitly

- **Missing fields** — `validators.find_missing_fields` walks dotted paths
  (e.g. `origin.city`) and reports which load-critical fields are null; this
  directly lowers confidence rather than being silently ignored.
- **Conflicting totals** (`line_haul + fuel ≠ total`) — `check_conflicting_totals`
  compares `line_haul_rate + (fuel_surcharge or 0)` against `total_rate`.
  - If `fuel_surcharge` is known and the numbers don't reconcile → hard
    `conflicting_totals` flag, forces `confidence: low`.
  - If `fuel_surcharge` is `null` (common — many carrier docs don't itemize
    it) and the total still doesn't match the line haul alone, we can't tell
    whether that's a real conflict or an unmodeled accessorial charge, so it's
    downgraded to a softer `unaccounted_charges` warning instead of a hard
    failure. Sample `LD64408` (Base Carrier Rate 500 + Carrier Charge 200 =
    Total 700) exercises exactly this path — see `tests/test_pipeline.py`.
- **Ambiguous dates** (e.g. `3/4/26`) — `is_ambiguous_date_string` flags
  numeric dates where both the day and month positions are `<= 12` and there's
  no disambiguating context. The prompt tells the model to still resolve
  these using US `MM/DD/YYYY` convention (rather than emitting `null` and
  losing the data), but the ambiguity is a known, tested case
  (`tests/test_validators.py::TestAmbiguousDates`) — a stricter deployment
  could instead choose to null these out and force human review.
- **Equipment-type synonyms** — normalized by a hardcoded lookup table
  (`extraction/equipment.py`), applied to the raw LLM output *before* schema
  validation. Code-enforced, not just a prompt instruction: an unrecognized
  phrasing still deterministically maps to `"other"` instead of depending on
  the model getting it right every time.
- **Hallucinated origin/destination on multi-stop docs** — which pickup
  becomes `origin` and which drop becomes `destination` is still a prompt
  convention (first pickup / last drop), but `validators.find_unverified_locations`
  adds a code-level guard: if the city the model picked doesn't literally
  appear anywhere in the source text, it's flagged (`unverified_location`)
  and confidence is downgraded, rather than silently trusting an invented city.
- **Transient API failures** (rate limits, 5xx, connection errors) —
  `AnthropicExtractor` passes explicit `max_retries`/`timeout` to the SDK,
  which retries these with exponential backoff before ever raising; a
  failure that still reaches the pipeline is treated as non-retryable and
  routed to the safe all-null/`low`-confidence fallback rather than crashing.

## Live test evidence

Ran end-to-end against the real Anthropic API (`claude-sonnet-4-5-20250929`)
against all 4 samples. Raw output captured in
[`samples/live_test_output.json`](samples/live_test_output.json). Highlights:

- Samples 1 & 3 (single pickup/drop, clean totals): extracted perfectly,
  `confidence: "high"`, zero warnings.
- Sample 2 (LD64408, multi-stop, unitemized `Carrier Charge`): correctly
  extracted origin as the *first* pickup and destination as the *final* drop
  across 3 stops; `total_rate` (700) doesn't reconcile with `line_haul_rate`
  alone (500) since `fuel_surcharge` isn't itemized → `unaccounted_charges`
  warning, `confidence` downgraded to `"medium"`.
- Sample 4 (synthetic edge-case fixture): in one run, the live model
  correctly (a) resolved the ambiguous `3/4/26` date to `2026-03-04` per the
  US-convention instruction, (b) left `destination` null because the document
  genuinely doesn't state one, and (c) reported `fuel_surcharge: 150` which,
  added to `line_haul_rate` (1200), doesn't match the stated `total_rate`
  (1500) → hard `conflicting_totals` flag → `confidence` forced to `"low"`.
  This is the exact cost-asymmetry scenario the spec calls out: a $150
  discrepancy that would otherwise auto-book at the wrong rate is instead
  routed to human review.

Known gaps / things not implemented:
- Multi-stop *ordering* (deciding which of several pickups is chronologically
  first, which drop is last) is still a prompt convention, not independently
  re-derived in code. What *is* code-enforced is a hallucination guard
  (`find_unverified_locations`) that flags/downgrades confidence if the city
  the model picked isn't literally present in the source text at all.
- The repair-retry loop (for schema validation failures) is separate from
  the SDK's transport-level retry/backoff (for rate limits/5xx/connection
  errors) — by design, since they retry different failure modes, but it does
  mean a request could take up to `MAX_REPAIR_ATTEMPTS x SDK max_retries`
  attempts in the worst case before falling back.

## Mock provider (`--provider mock`)

`extraction/mock_llm.py` is a naive regex-based extractor with the same
interface as the Anthropic client. It exists **only** so `tests/` can run
offline/without an API key/in CI. It is not the submission's extraction
strategy and its output quality is intentionally not representative (e.g. it
can misattribute the mailing address as the origin city) — the pipeline
plumbing around it (schema enforcement, validators, confidence) is what's
being demonstrated by the tests, not the mock's parsing accuracy.
