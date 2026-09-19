# Review-mode output contract

Read when running `--review`. Review mode **judges**; it never scores. The reader is deciding
whether to ship a change, and a number in place of a judgment strands good changes behind an
arbitrary line while giving bad ones something to argue with.

## The verdict

Exactly one, in plain words:

- **SHIP** — nothing found that should stop it. Non-blocking suggestions do not downgrade this;
  note them and still say ship. The bar is "safe and good", not "perfect".
- **FIX FIRST** — a specific, concrete blocker. Name exactly what must change for this to become
  SHIP, precisely enough that the author does not have to guess.
- **RETHINK** — wrong in a way a small change will not fix. Say why, and what direction would
  work.

The routing rule below decides which findings block; this verdict is the one-line judgment that
follows from what it produced. If you are genuinely unsure, say so in words and let the
uncertainty inform the verdict honestly — a reviewer who is mostly confident a change is safe still ships it and flags the
residual unknown. Never convert uncertainty into a number.

## Verdict to section — the routing rule

Every candidate arrives carrying a verifier verdict. Route it:

- **CONFIRMED** → *Blockers* if the consequence is any of: incorrect behaviour reaching a user,
  bad data persisted, a security boundary crossed, or the change not doing what it claims.
  Otherwise → *Worth fixing*. Apply the list; do not weigh it.
- **PLAUSIBLE (trigger)** → the **same list as CONFIRMED**, with the unproven trigger stated
  alongside. This label already means the mechanism holds and the boundary is shown, so an
  unproven trigger is not an absent one — it does not earn a weaker route than a confirmed finding
  with the same consequence. No special case, no second condition for the router to evaluate.
- **PLAUSIBLE (unread)** → *Unsettled*, never *Blockers*. The reason here is that a caller or file
  was not examined, which is a coverage limit rather than a risk signal; promoting it would
  convert "I did not read far enough" into "do not ship".
- **REFUTED** → omitted from the report entirely, and logged to the rebuttal record.
- **CAN'T-CONFIRM** → *Unsettled*, with what would settle it.
- **Downgraded by the security pass** — a pattern present but not shown reachable → *Noticed, not
  blocking*, labelled as a downgrade, with what blocks reachability or what could not be traced.

Nothing reaches the report unrouted, and **nothing is published as a finding without a verdict** —
an unverified candidate presented as real is the confident-false-positive failure. Downgrades are
the one thing that reaches the page without one, and that is why they are published as *not
findings*: a note that a pattern was looked at and found unreachable. Never promote one into a
finding without sending it through verification first.

## What the report must contain

Lay it out however reads best for the change in hand. These must all be present:

- **The verdict**, with one sentence of why.
- **Blockers** — findings that must change before this ships: confirmed ones, plus the one
  plausible case above. Each carries its evidence class satisfied (a defect shows its
  reproduction, an opportunity its cost and benefit, an absence what breaks silently), a
  `file:line`, and what would fix it. Say explicitly when there are none.
- **Worth fixing** — findings the routing rule did not send to Blockers or Unsettled. The
  author's call.
- **Unsettled** — what could not be confirmed from source, each with what would settle it.
- **Noticed, not blocking** — two things, labelled so a reader can tell them apart: case-1
  pre-existing problems, listed for the backlog; and security downgrades, patterns that were
  examined and not shown reachable. Neither is counted against the change. Recording the second is
  what makes "no security findings" mean something.
- **Tests** — always present, because the gate always fires. What the repo has, what this change
  did or did not add, which changed symbols are untested, and whether that matters here.
- **Conventions honored** — which declared conventions were applied and what each suppressed.
  Present whenever the repo carries a review-context file.
- **Coverage** — what was read, what was not and why, what was delegated, and whether anything
  was executed. Also name any gate that could not run, and why.

## Rules

**Independent confirmations are worth stating.** When your pass and the delegated pass reach the
same finding without seeing each other's reasoning, say so — but only once both have been
verified. Two unverified candidates agreeing is not evidence.

**Disagreement is reported, not resolved silently.** Where the passes differ on whether something
is real or how bad it is, show both positions rather than picking one and hiding the other.

**Coverage is never omitted.** A report without it cannot be distinguished from one produced by
reading almost nothing, and "no issues found" is not a claim until the scope is stated.
