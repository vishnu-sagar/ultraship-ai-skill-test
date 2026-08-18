# Part 2 — Evaluation & Reliability

## 1. Building an eval set

**Ground truth**: hand-labeled JSON per document, using the exact Part 1
schema. Two independent labelers per document, with disagreements reconciled
by a third adjudicator — a single labeler isn't reliable here because
multi-stop origin/destination selection has genuine ambiguity even for a
human.

**Size**: start with 50–100 documents, deliberately stratified across the
axes we already know cause trouble, not picked randomly: single vs. multi-stop,
itemized vs. non-itemized fuel surcharge, clean vs. ambiguous dates, PDF vs.
email-body vs. email-with-PDF-attachment, and a spread of equipment types and
shippers/carriers. Treat it as a living set, not a one-time deliverable —
every real production mismatch a human corrects gets added as a new eval
case, so the set grows exactly where the pipeline is actually weak.

**Partial correctness scoring**: score per field, not just exact-whole-record
match, since "right rate, wrong date" and "everything wrong" are very
different failures:
- Structural fields (`load_id`, dates, city/state) → exact match after normalization.
- Numeric fields (rates, weight) → tolerance-based match (e.g. within $0.01).
- `equipment_type` → categorical match.
- Report both **exact-record accuracy** and **per-field accuracy**, plus
  **confidence calibration**: for each confidence bucket, what fraction of
  records actually had every load-critical field correct? `high` should be
  ~100%; if it isn't, the confidence rule (not the extraction prompt) needs
  fixing.

## 2. Which metric matters most, and why

**False-auto-book rate**: the fraction of `confidence: "high"` records where
a load-critical field (rate, dates, origin/destination) is actually wrong.
This must be near zero, even at the cost of routing more loads to review.
Given the spec's own framing — a wrong rate that auto-books is worse than a
flagged-for-review load — this is a precision-of-the-trust-decision metric,
not a recall-of-extraction metric.

Coverage (the fraction of loads that reach `high` confidence at all) is a
real secondary metric — too low and ops is manually reviewing everything,
defeating the point of automation — but it's secondary. I'd rather ship a
system that auto-books 40% of loads with a near-zero false-auto-book rate
than one that auto-books 90% with a real, silent error rate baked in.

## 3. Detecting drift or regressions in production

- **Confidence distribution per source** (shipper/carrier, or sender domain
  for emails): a new shipper suddenly producing far more `low`/`medium` than
  the historical baseline is the earliest, cheapest signal of an unhandled
  format — visible before you even know if the extracted values are wrong.
- **Warning-code rates per source**: a spike in a specific code (e.g.
  `conflicting_totals`, `unverified_location`) points at *what* changed, not
  just *that* something did.
- **Human-correction rate**: log every diff when a reviewer corrects a field.
  A rising correction rate concentrated on one field (e.g. `pickup_date`
  suddenly wrong across many loads) is ground truth that something regressed.
- **Model version pinning + gating**: already pinned to a dated snapshot
  (`claude-sonnet-4-5-20250929`), not a floating alias. Before bumping to a
  new snapshot, re-run the fixed eval set and diff per-field accuracy and
  confidence distribution against the current version — treat any
  regression as a release blocker, not a surprise discovered in prod.
- **Shadow/canary mode**: run prompt or model changes against live traffic in
  parallel (not user-facing), diff outputs against the currently-live
  version, and alert on deltas beyond a threshold before cutover.

## 4. Human-in-the-loop moment

Anything below `confidence: "high"` never silently auto-populates — it lands
in a review queue in the load-creation screen the broker already uses, not a
separate tool. The moment itself: the extracted JSON pre-fills the load form
with the *specific* flagged field(s) visually highlighted and annotated with
why (e.g. "conflicting totals: $1,350 expected vs. $1,500 stated"), next to a
side-by-side preview of the source document so the reviewer is confirming or
correcting, not re-deriving from scratch. A one-click "confirm as-is" handles
the common false-positive case, and editing any field re-runs the
conflicting-totals/missing-field checks live, so the reviewer gets instant
feedback instead of submitting blind.
