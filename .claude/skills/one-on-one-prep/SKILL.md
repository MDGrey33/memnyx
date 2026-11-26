---
name: one-on-one-prep
description: Prepare 1:1 meeting notes by synthesizing a team member's recent activity into a structured meeting agenda
user_invocable: true
args: "Member name and optional time range. Examples: 'Alice Chen', 'Alice Chen last 2 weeks', 'Bob Smith 2026-03-28 to 2026-04-11'. Defaults to last 1 week."
---

# 1:1 Meeting Prep

Synthesize a team member's recent activity from daily activity files into a structured meeting prep document. This is a **synthesis skill** — it reads raw data collected by `/collect-team-activity`, it does not collect data itself.

## Model Selection

Advisory: this section does not switch the session model. See `.claude/skills/_shared/MODEL_SELECTION.md` for tier definitions.

- **Default model:** Sonnet. Turning raw activity into discussion points about a person is synthesis with consequences for how they are read.
- **Deterministic parts (no LLM):** finding the activity files for the member and date range.
- **Demote to Haiku when:** never.
- **Promote to Opus when:** the user asks for it, for example ahead of a performance or growth conversation.

## Privacy posture

Input files under `<workspace>/collected/` may contain private Slack channel content, internal Jira tickets, and other non-public material gathered by `/collect-team-activity`. The synthesised prep document this skill produces lands on the caller's local disk under `<workspace>/artifacts/one-on-one-prep/`. Intended for the caller's own 1:1 preparation with their direct reports — do not generate prep for members outside your direct report scope, and treat the output as confidential.

## Steps

**Setup — Resolve `<workspace>`**: The skill's base directory is `<workspace>/.claude/skills/one-on-one-prep/`; walk up three directory levels and validate that `<workspace>/.claude/.workspace` exists. Use this `<workspace>` for all path references below (identity, team, activity input, output). Abort with a setup-broken error if validation fails.

1. **Role guard**: Read `<workspace>/me/identity.md` and check the user's title/role.
   - If the role is clearly IC-equivalent with no reports, **stop**:
     ```
     This skill is for leadership roles with direct reports.
     ```
   - If ambiguous, proceed.

2. **Load team roster**: Read `<workspace>/me/team.md`.
   - If missing, **stop** with guidance:
     ```
     No team roster found at <workspace>/me/team.md
     Create one with your direct reports and their platform IDs.
     ```
   - Match the member name loosely (first name, full name, case-insensitive). If no match, list available names and ask.
   - Compute `member-slug`: the matched member's full name lowercased, with non-alphanumerics replaced by `-` (e.g., "Alice Chen" → `alice-chen`). Used in input and output paths.
   - Read the member's `**Level**:` field (e.g., `L5`).
     - **If present** → use it.
     - **If missing and interactive (user is at the keyboard)** → prompt: `"No level set for {Member Name} in team.md. What level are they? (e.g., L4)"`. After user responds, write the level back to team.md (fill-missing-only — never overwrite an existing value). Continue.
     - **If missing and non-interactive (agent-driven)** → invoke `/log` with `status=WARNING detail=Level missing for {member-slug} in team.md — synthesis ran without level calibration`. Continue without the level-context block.

3. **Load writing style**: Read the Writing Style section from `<workspace>/me/identity.md`. Apply it to all output. If no style is defined, default to clear and concise.

4. **Load level identity anchor**: Read `.claude/docs/level-expectations.md` (project-scoped, shared reference).
   - Extract the Identity Anchor for the member's level from the `## Identity anchors` table (one line). Used in the prep header alongside a link to the full file.
   - The local mirror is the contract — the skill does not fetch from any remote canonical at synthesis time.
   - If the file is missing, omit the identity anchor text and link from the header; log a `WARNING` via `/log` and continue.

5. **Determine time range**: Parse the arguments for a date range.
   - Explicit range (`YYYY-MM-DD to YYYY-MM-DD`): use as-is.
   - Relative range (e.g., "last 2 weeks", "last 5 days"): N units back from today (ending today, inclusive).
   - Default (no range argument): last 7 days back from today, inclusive.
   - The output is a list of every date in the range — **do not pre-filter to workdays**. If a member worked on a weekend, the activity file exists at that date, and pre-filtering would miss it.

6. **Read activity files**: For each date in the range, look for:
   - `<workspace>/collected/collect-team-activity/<member-slug>/YYYY-MM-DD-<member-slug>-activity.md`

   For each file found: parse the Markdown to extract the `Status:` header, the `## Summary` text, and each `## Activity` item with its category, time, sources, and context.

   **Source-file `## Gaps` are collection metadata** — which sources were inaccessible at fetch time, runtime issues, "out of scope" notes. Do **not** propagate them into the prep. They are not 1:1 content. The activity items themselves are the synthesis material.

   **Files with `Status: PARTIAL`** contribute their captured items to the synthesis exactly like SUCCESS files. PARTIAL is a **coverage signal**, not a discussion point — surface it in the output's `**Activity data**:` header (e.g., `5/5 dates covered (partial coverage on 2026-04-29: Confluence)`). Do not fabricate concerns about the failed source.

   **Track missing dates** — dates in the range where no file exists. Quiet days, PTO, weekends, and "not collected" are all the same to this skill: the file isn't there.

   **Status semantics**:
   - **SUCCESS** — the skill produced an output file, regardless of how many dates had activity files. Partial coverage of the requested period is normal; reported in the output header, not the Status field.
   - **FAILED** — the skill could not produce an output file: member not found in `team.md`, no activity files exist anywhere in the requested period, or the output path is unwritable. If no activity files exist at all, **stop** and report:
     ```
     No activity data found for {member} in the requested period.
     Run /collect-team-activity {member} for the missing dates first.
     ```

7. **Synthesize**: Analyze all collected activity across the date range and produce four sections.

   **Item-count discipline (applies to all sections):** Aim for the **5–10 most material items per section**, not an exhaustive log. A 1:1 prep is a starting point for conversation. If a section would exceed 10 items, group more aggressively or drop the lowest-impact ones.

   **Descriptive-only constraint (applies to Patterns & Observations and Discussion Candidates):** This skill surfaces patterns visible in the data; it does **not** prescribe actions. Do not write recommendations like "raise a ticket", "loop in X", "rotate the credentials first", "escalate to Y". The skill lacks the surrounding context (who's already on a thread, what the team member has been told, what their current priorities are, who owns what) to make those judgements. Describe what the data shows; the manager decides the action.

   **Completed Tasks & Achievements**
   - Group by project or theme, not by date or activity category
   - Each item: what was accomplished, why it matters, with date and source links
   - Highlight standout contributions

   **In Progress / Open Items**
   - Group by project or theme
   - Each item: current state, what's next (only as visible from the data), any blockers (only as flagged in the source items)
   - Use the `execution` flag from the `## Jira — Owned (assignee)` section to interpret assignee tickets:
     - `execution: status-change` — include as delivery evidence; the member drove this
     - `execution: commented` — lighter engagement signal; include if the comment shaped the outcome
     - `execution: none` — **awareness/planning signal only.** Do NOT surface as stalled delivery or "no movement." For leadership roles, tickets are frequently assigned for routing, awareness, or sprint-queue purposes, not for the assignee to execute personally. State the ticket is in queue if relevant; do not imply the member should have acted.
     - `execution: unverified` — the collector could not read every comment in the window. Treat it as unknown, never as `none`: leave it out of delivery evidence and don't raise it as inactivity.
   - **Reporter-only tickets** (`## Jira — Filed (reporter-only)` or `## Filed (reporter-only)` sections in the activity file) must NOT appear in Completed or In Progress. Surface them in a separate **Sprint Portfolio** section after Discussion Candidates — a brief table (key, summary, assignee, status). These are planning/oversight signals: the member created the work and delegated it to an IC. Delivery credit belongs on the IC's report.

   **Patterns & Observations**
   - Surface non-obvious patterns the data supports: stalled tickets, recurring categories, time-of-day patterns, cross-team coordination, sustained focus areas.
   - **Descriptive only.** State what the data shows. Do not propose actions, framings, or escalations.
   - Cite evidence (source links, date ranges, counts).
   - Don't fabricate. If a pattern isn't supported by the data, don't include it.

   **Discussion Candidates**
   - 3-5 topics surfaced by the data that the manager might consider raising — *might*, not *should*. The manager decides.
   - Each candidate: a one-line description + the underlying observation reference.
   - No prescribed order — order by data salience, not by category (blockers vs. recognition vs. growth — that's calibration the manager applies).
   - Surface; don't editorialise.

8. **Formatting rules**:
   - Add the specific date to each point — activity files always carry ISO `Time:` stamps. Use the **local-date portion** (the date in the timezone offset shown), not the UTC date. For an item at `2026-04-12T01:30:00+04:00`, the date is `2026-04-12`, not `2026-04-11`.
   - **Source link text: ticket key alone** (e.g., `[PLAT-808](url)`). Weave the title into the bullet text or context line where useful. Embedding full key+title in link text bloats bullets when titles are long.
   - **Slack permalinks: use exactly as provided in the activity file.** Thread reply permalinks include `?thread_ts=<parent_ts>&cid=<channel_id>` — never reconstruct or shorten them. A bare `p<timestamp>` URL without `?thread_ts=` will not navigate to the reply in Slack.
   - Every claim must have a source link. No exceptions.
   - Keep each bullet to 1-2 sentences max.
   - Writing tone follows `identity.md` — if not set, default to direct and clear.

9. **Write the output file**: Write to `<workspace>/artifacts/one-on-one-prep/<member-slug>/YYYY-MM-DD_to_YYYY-MM-DD.md` where `<member-slug>` is the slug computed in step 2 and the dates are the start and end of the activity period. Create parent directories if missing.

   **Re-run on the same (member, period)**: overwrite the file. Add a header line `**Re-synthesis**: previous run superseded YYYY-MM-DD HH:MM:SS` (UTC) below the title so the user can see this is not a fresh first run.

   ```markdown
   # 1:1 Prep: {Member Name}
   **Generated**: YYYY-MM-DD
   **Period**: YYYY-MM-DD to YYYY-MM-DD
   **Level**: {Level} — {Identity Anchor} · [L&E](.claude/docs/level-expectations.md)
   **Activity data**: {X}/{Y} dates covered ({list missing dates, if any})

   ## Completed Tasks & Achievements

   ### {Project / Theme}
   - **{What was accomplished}** ({date})
     - Sources: [PROJ-123](url), [Slack thread](permalink)
     - {Why it matters}

   ## In Progress / Open Items

   ### {Project / Theme}
   - **{Current state}** ({date})
     - Sources: [PROJ-456](url) (assigned to {Name})
     - Next: {what's visible from the data}

   ## Patterns & Observations

   - **{Observation}** — descriptive, no prescriptions
     - Evidence: {source links, dates, counts}

   ## Discussion Candidates

   1. {Topic surfaced by the data — manager decides whether to raise}
   2. {Second}
   3. {Third}
   ```

   If `Level:` is missing for the member or `.claude/docs/level-expectations.md` is not found, omit the identity anchor and link from the header — the rest of the prep stays useful.

10. **Report to user** (skip if invoked by another agent):
    ```
    1:1 prep ready: {Member Name} ({Level})
    ──────────────────────────────
    Period: YYYY-MM-DD to YYYY-MM-DD
    Coverage: {X}/{Y} dates with activity data
    Missing: {dates without data, or "none"}
    File: <workspace>/artifacts/one-on-one-prep/<member-slug>/YYYY-MM-DD_to_YYYY-MM-DD.md
    ```

11. **Logging**: On completion, invoke the `/log` skill:
    ```
    /log run_id=<run_id> skill=one-on-one-prep status=<SUCCESS|FAILED|WARNING> detail={member name}: {period}, {coverage}
    ```
    Use `manual` as run_id if invoked directly by the user. Use `WARNING` if the prep was produced but the level header is incomplete (missing `Level:` in team.md or missing local mirror).

## Important Rules

- **Synthesis only.** This skill reads from `collected/` files. It never queries Slack, Jira, or any other data source directly.
- **Descriptive, not prescriptive.** Surface patterns; the manager decides actions. No "raise a ticket", "loop in X", "rotate first" — the skill lacks the surrounding context to make those judgements.
- **Every claim needs a source link.** Inherited from the activity files. If an activity item has no link, flag it as unverified.
- **Don't fabricate observations.** Every Pattern & Observation must be supported by evidence in the activity files. No activity for a day is not a pattern — it might just mean the daily collection wasn't run.
- **Distinguish authorship from ownership.** When commenting on ticket movement, note whether the team member is the assignee or the reporter. Tickets the member filed but doesn't own are different from tickets the member owns.
- **Don't over-prepare.** A good 1:1 prep is a starting point for conversation, not a performance review. Keep it focused on what's worth discussing in person.
- **Missing data is a note, not a failure.** If some days have no activity files, say so and move on. The prep is still useful with partial data.
