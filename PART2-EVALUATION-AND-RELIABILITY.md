# Part 2 — Evaluation & Reliability

## 1. Building an eval set

Ground truth comes from hand-labeling documents against the Part 1 schema —
but I wouldn't trust a single labeler here. Multi-stop docs genuinely confuse
humans too (which pickup counts as "the" origin isn't always obvious), so
every document gets labeled by two people, and a third person breaks ties.

For size, I'd rather have 50–100 well-chosen documents than 500 random ones.
"Well-chosen" means deliberately covering the stuff we already know breaks
things: multi-stop vs. single-stop, itemized vs. lumped-in fuel surcharge,
clean dates vs. ambiguous ones, PDFs vs. email bodies vs. emails with a PDF
attached, different shippers and carriers. And it shouldn't stay static —
every time a human corrects something in production, that document becomes a
new eval case. The set should basically grow itself out of real mistakes.

On scoring, whole-record pass/fail is too blunt — "right rate, wrong date" is
a very different failure than "everything's wrong," and lumping them together
hides that. So I'd score field by field: exact match (after normalizing) for
things like load ID and city/state, a small tolerance for money and weight
(rounding shouldn't count as an error), and categorical match for equipment
type. Then report both per-field accuracy and full-record accuracy, plus one
more thing that matters more than either: how well confidence is calibrated.
If a document is marked "high" confidence, it should basically always be
right — if the "high" bucket has a real error rate, that's a bug in the
confidence logic, not the extraction.

## 2. Which metric matters most, and why

The one I'd actually lose sleep over is the false-auto-book rate — how often
a load marked "high confidence" (i.e., cleared to go straight into the
system) turns out to have a wrong rate or date. The spec basically hands you
this answer: a wrong number that books itself is worse than a load that sits
in a review queue for two extra minutes. So this is a precision problem, not
a recall problem — I'd rather under-trust and route more to review than
over-trust and let a bad number slip through.

Coverage — what percentage of loads even reach "high" confidence — matters
too, because if it's too low, humans are reviewing everything and the
automation isn't buying anyone anything. But I'd take a system that
auto-books 40% of loads with almost no false positives over one that
auto-books 90% with a hidden error rate. The first one is boring and
trustworthy; the second one is a lawsuit waiting to happen.

## 3. Detecting drift or regressions in production

The cheapest, earliest signal isn't "is the data wrong" — it's watching the
confidence distribution per shipper/carrier over time. If a specific sender
suddenly starts generating way more medium/low results than it used to,
that's a red flag before you've even confirmed anything's actually wrong.
Same idea with warning codes — a spike in one specific warning (say,
conflicting totals) for one sender tells you roughly what changed, not just
that something did.

The most honest signal, though, is what humans actually correct. Every time
a reviewer edits a field the pipeline filled in, that diff should get logged.
If corrections on one field start climbing — say pickup dates are suddenly
wrong across a bunch of loads — that's ground truth that something broke, no
eval set required.

For model updates specifically: I'm already pinning to a dated snapshot
(`claude-sonnet-4-5-20250929`) rather than a "latest" alias, precisely
because I don't want behavior to change under me without warning. Before
moving to a new snapshot, I'd re-run the eval set and compare accuracy and
confidence distribution against the current one — any regression blocks the
upgrade, it doesn't get discovered by an angry broker later. Ideally you'd
also run a new model or prompt version in shadow mode against real traffic
first (not user-facing) and diff its output against production before ever
cutting over.

## 4. Human-in-the-loop moment

Nothing below "high" confidence auto-populates, full stop — it goes into a
review queue that lives inside the load-creation screen brokers already use,
not some separate tool they have to remember exists. When a broker opens a
flagged load, the form is already filled in from the extraction, but the
specific field that triggered the flag is highlighted with a plain-English
reason next to it — something like "expected $1,350 based on line haul + fuel,
but the document says $1,500" — with the original document sitting right
next to it so they're confirming against the source, not hunting for it.
Most of the time the flag will turn out to be a non-issue, so a one-click
"looks fine, book it" should be the fastest path. If they do edit a field,
the conflicting-totals/missing-field checks should re-run immediately, so
they get instant feedback instead of submitting and hoping.
