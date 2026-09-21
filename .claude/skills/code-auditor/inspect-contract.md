# Inspect-mode output contract

Read when running `--inspect`. Inspect mode **scores and ranks**; it does not judge. The reader
is asking what to fix first, and that question is literally a sort. This is the one place a
number earns its keep — a merge decision wants a judgment, a backlog wants an order.

## Scoring

Four axes per item:

- **Severity** — what goes wrong if this is never fixed.
- **Confidence** — carried through from the verifier's verdict, unchanged. A plausible finding is
  never scored as a confirmed one. Both plausible kinds score the same here; the distinction
  between them is a review-mode routing concern, not a scoring one.
- **Blast radius** — how much is touched: one function, one module, every caller of a shared
  helper.
- **Effort** — what fixing it costs, including the tests it needs.

Use a **three- or four-level ordinal scale** and **print its legend at the top of the plan**,
with one line of criteria per level. Any consistent scale works; an unstated one does not,
because two runs then produce output that cannot be compared or merged.

Rank by severity and confidence together, discounted by effort, so cheap high-value fixes surface
instead of being buried under a rewrite. **Severity alone is the wrong sort** — it puts the
six-week refactor above the one-line fix that closes a live hole. Show the axes, not just the
rank: a reader who disagrees with the order must be able to see which input they disagree with.

## Grain

**The item chooses its own grain.** One bad line is one item. Nine copies of the same logic is
one item at theme grain, not nine. A subsystem with no tests is one item, not one per file.

Grain is free; **schema is fixed**. Whatever its size, every item carries the same fields, so a
refactoring theme and a single defect sort against each other honestly:

```
### <title>
Class:      defect | opportunity | absence
Grain:      finding | file | theme
Where:      <one location, or the full set — list them, never "and others">
What:       <the problem>
Why now:    <consequence of leaving it; for an opportunity, the cost being carried>
Evidence:   <file:line, plus the reproduction / cost-benefit / silent-failure per class>
Severity:   <level>
Confidence: <verifier verdict>
Blast:      <scope touched>
Effort:     <level>
Fix:        <the concrete first step, not a plan>
```

Class and grain are independent, and the cross cases are the interesting ones. A *defect* at
*theme* grain is one bug reproduced across many sites — the same unchecked index in nine
handlers, which is one fix decision and one item. An *opportunity* at *finding* grain is a single
function worth deleting.

## What the plan must contain

- **Legend** — the ordinal scale and its criteria.
- **Summary** — what this repo is and what shape it is in, in a few sentences. **No overall score
  for the repo.** A single health number is exactly the arithmetic-laundering this skill avoids.
- **Remediation plan** — the items, ranked. The order is the product.
- **Tests** — coverage state, modules with no tests at all, untested paths that matter and why,
  and any test whose assertions discard the property its name claims.
- **Duplication census** — what the corpus scan found, which clones are worth collapsing, which
  are coincidence, and **whether the census ran at all**. If no similarity tool was available,
  say so and say what was done instead.
- **Conventions honored** — declared conventions applied, and what each suppressed.
- **Coverage** — units audited, units skipped and why, files read, anything executed, and what a
  re-run should look at that this one did not.

## Re-runs

Inspect output is **diffed, never regenerated**. People annotate these plans, and one that
silently loses last month's notes is one they stop annotating.

For a re-run to find the previous plan, it has to be findable: write each plan to the run's
output directory as `<repo-name>-plan-<YYYY-MM-DD>.md`, and treat the most recent one for that
repo name as the baseline. On a re-run:

- A finding that persists **keeps its identity and its annotations**.
- A finding that is gone is **marked resolved**, not deleted. The record that it was fixed is
  worth keeping.
- New findings are **marked new**, so a reader sees what moved without re-reading everything.

## Rules

**One repo per run.**

**Corpus-level sweeps run once** across the whole target, not per unit. Per-unit duplication
scanning both duplicates work and misses every clone that spans units, which are the ones worth
finding.

**Findings accumulate to a findings ledger as units complete** — distinct from the coverage
ledger, which records what was read. A unit whose agent dies is re-dispatched; nothing depends on
the dead agent handing anything over.
