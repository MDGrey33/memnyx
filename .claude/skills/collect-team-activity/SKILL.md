---
name: collect-team-activity
description: Collect a team member's daily work activity from Slack, Jira, Confluence, and GitHub
user_invocable: true
args: "Pick a scope based on user intent — orchestrator builds the (member × date) pair list from these shapes: no args = all members today; '<name>' = specific member today; '<date>' = all members on that date; '<date range>' (e.g., '2026-04-07 to 2026-04-11') = all members across that range; '<name> <date>' or '<name> <date range>' = specific member, scoped date(s). Match member name loosely against team.md (first name, full name, case-insensitive)."
---

# Collect Team Activity

Collect work activity for one or all team members for one or more days from Slack, Jira, Confluence, and GitHub. Designed for engineering leadership (EM, director, VP). Multi-pair scopes fan out to sub-agents — one sub-agent per (member, day) pair — for context isolation and parallelism.

## Model Selection

Advisory: this section does not switch the session model; it states policy for the executor sub-agents. See `.claude/skills/_shared/MODEL_SELECTION.md` for tier definitions.

- **Default model:** Sonnet, for the orchestrator and the executors. Step 7 sets no model override, so executors inherit the session's model; Sonnet is enough for them. Classifying a member's tickets by role and execution evidence, and framing activity by impact, is judgment work.
- **Deterministic parts (no LLM):** building the member × date pair list, date-boundary arithmetic, pagination loops, and the GitHub queries inside the shared `gh-activity.sh` script.
- **Demote to Haiku when:** never. Executor output feeds 1:1 prep and leadership reports, where a wrong `execution:` flag or role split becomes a claim about a person.
- **Promote to Opus when:** never for routine runs.

## Privacy posture

This skill reads from **private Slack channels** visible to the caller's Slack token (engineering, leadership, project channels) — not just public channels. Jira and Confluence access is bounded by the caller's Atlassian permissions; GitHub access uses the caller's gh identity (see "GitHub" section in the Executor Contract). Collected data lands on the caller's local disk under `<workspace>/collected/collect-team-activity/`. Intended for leadership oversight and 1:1 preparation with direct reports — do not run on members outside your direct report scope, and treat the output as confidential.

## Architecture

This skill has two roles:
- **Orchestrator** (steps 1–8): handles role guard, pre-flight, caller identity, team-roster load, scope parsing, per-member TZ resolution, fan-out, and aggregation. The orchestrator is what runs when a user invokes `/collect-team-activity`.
- **Executor** (steps E1–E4, see "Executor Contract" section): handles a single (member, day) pair end-to-end. The orchestrator spawns one executor sub-agent per pair via the Agent tool, in batches of 3–5 to respect MCP rate limits.

When scope resolves to exactly one (member, day) pair, the orchestrator runs the executor steps inline (no sub-agent spawn — overhead not worth it).

## Orchestrator Steps

**Setup — Resolve `<workspace>`**: The skill's base directory is `<workspace>/.claude/skills/collect-team-activity/`; walk up three directory levels and validate that `<workspace>/.claude/.workspace` exists. Use this `<workspace>` for all path references below (identity, team, output). Abort with a setup-broken error if validation fails. Sub-agents (executors) inherit `<workspace>` from the orchestrator — they do not re-resolve.


1. **Role guard**: Read `<workspace>/me/identity.md` and check the user's title/role.
   - If the role is clearly IC-equivalent (e.g., "Software Engineer", "Developer") with no reports, **stop**:
     ```
     This skill is for leadership roles with direct reports.
     Use /collect-my-activity for your own activity.
     ```
   - Leadership roles: Director, VP, Head of, Engineering Manager, Team Lead, Tech Lead, Principal (with reports), Staff (with reports).
   - If ambiguous, proceed — don't block on edge cases.

2. **Pre-flight checks**: Verify the environment before fanning out:
   - **Slack MCP**: Required. The tools load under an MCP-server prefix (e.g. `mcp__<server>__slack_search_public_and_private`) and may be **deferred** — registered by name but schema-unloaded until fetched. Three states, not two: (a) the tools are available → proceed; (b) only an `authenticate`/`complete_authentication` tool is present → the server is a claude.ai connector awaiting interactive sign-in, so ask the user to run `/mcp`, select the Slack connector, and authenticate, then continue — this is recoverable, do **not** abort; (c) genuinely absent → abort (see below).
   - **Atlassian MCP**: Required (covers Jira + Confluence). The tools load under an MCP-server prefix (e.g. `mcp__<server>__getJiraIssue`) and may be **deferred** — registered by name but schema-unloaded until fetched. Three states, not two: (a) the tools are available → proceed; (b) only an `authenticate`/`complete_authentication` tool is present → the server is a claude.ai connector awaiting interactive sign-in, so ask the user to run `/mcp`, select the Atlassian connector, and authenticate, then continue — this is recoverable, do **not** abort; (c) genuinely absent → abort (see below). On claude.ai the connector is Atlassian MCP (`claude_ai_Atlassian_MCP`, Atlassian's V2 endpoint); the older `claude_ai_Atlassian` and `claude_ai_Atlassian_Rovo` connectors run on Atlassian's V1 endpoint, which is being retired (removal 2027-03-01), and don't count as available. The Jira and Confluence steps below use that connector's tool names and parameters (`view`, `nextPageToken`, `cursor`); another Atlassian server needs them adapted.
   - **`gh` CLI**: Expected. If missing, log a warning via `/log` (`status=WARNING detail=gh CLI not available — GitHub data will be missing. Install with: brew install gh && gh auth login`), mark as a gap, and continue. Sub-agents will record the same gap in their output files.
   - **Sub-agent permissions**: sub-agents inherit project-level `.claude/settings.json` only — they cannot prompt for permissions. Verify the allowlist covers the MCP and CLI patterns sub-agents will call (Atlassian MCP `searchJiraIssuesUsingJql`, `listJiraIssueComments` and `searchConfluence`, Slack search/read, `gh auth status`, and `bash .claude/skills/_shared/scripts/gh-activity.sh *` for GitHub). A workspace whose `settings.json` predates the shared script lacks that rule; sync does not update `settings.json`, so add it by hand or every sub-agent's GitHub data is a gap.

   On required-tool failure, abort the run, surface a clear failure message to the user, and invoke `/log` with `status=FAILED` (see Logging section). No sentinel file — pre-flight failure means no pairs run, so there's no per-pair output to mark.

3. **Resolve caller identity — MCP first, identity.md as cache, user input as last fallback**:

   General principle: probe the connected MCPs for any caller-derived value before reading `identity.md`, and only ask the user when both fail. `identity.md` is a cache, not a gate. The caller-identity fields the orchestrator needs are `Timezone` (fallback when a member has no TZ in `team.md`) and `GitHub username` (for the multi-account guard below).

   - **Atlassian account ID** → `atlassianUserInfo` (caller).
   - **Google Workspace email** — primary: `atlassianUserInfo.email`; fallback: `slack_read_user_profile.profile.email`; ask the user only if both fail.
   - **GitHub username (caller)** — `gh` supports multiple authenticated accounts. Team queries use `--author <member-handle>` so no `@me` substitution happens, but the active `gh` session must still be authenticated to an account with org access. Resolve as follows:
     - If cached in `## Profile`, use it. Verify it's still authenticated via `gh auth status` (parse for `Logged in to github.com account <handle>`). If the cached handle isn't in `gh auth status`, **fail loud** (FAILED) with re-auth instructions: `gh auth login --hostname github.com`.
     - If not cached, parse `gh auth status` for `Logged in to github.com account <handle>` lines:
       - **One account** → resolve via `gh api user --jq .login`, write back to `## Profile`.
       - **Multiple accounts** → **fail loud** (FAILED): *"Multiple `gh` accounts detected. Set `GitHub username` manually in `<workspace>/me/identity.md` `## Profile` before re-running. Agents cannot disambiguate which is the business account."*
     - **Token-fetch pattern**: the orchestrator never modifies the active `gh` session. Sub-agents run the shared `gh-activity.sh` script, which reads the cached handle's token in its own process (see Executor Contract → GitHub). The cached handle name is the only thing the orchestrator passes through to sub-agents for the gh flow.

   **Write-back rule**: when MCP resolves a field that is missing from `identity.md`'s `## Profile` section, append it there. **Fill missing only — never overwrite an existing value.** A stale MCP handle could otherwise clobber the user's curated identity. If a resolved value differs from what's already there, log a `WARNING`, skip the write, and surface the discrepancy at the end of the run. **Identity write-back is orchestrator-only**; sub-agents must not touch `identity.md`.

4. **Load team roster**: Read `<workspace>/me/team.md`.
   - If missing, **stop** with guidance:
     ```
     No team roster found at <workspace>/me/team.md
     Create one with your direct reports and their platform IDs.
     See the template at the bottom of this skill for the expected format.
     ```
   - Parse each team member's name, role, timezone (optional, IANA), and platform IDs (Slack, Jira account ID, GitHub).

5. **Determine scope and build the (member, date) pair list**: Parse the arguments.
   - **Specific member + date**: `/collect-team-activity Alice Chen 2026-04-10`
   - **Specific member + date range**: `/collect-team-activity Alice Chen 2026-04-07 to 2026-04-11`
   - **Specific member, today**: `/collect-team-activity Alice Chen`
   - **All members + date**: `/collect-team-activity 2026-04-10`
   - **All members + date range**: `/collect-team-activity 2026-04-07 to 2026-04-11`
   - **All members, today**: `/collect-team-activity`

   Match the member name loosely against the team roster (first name, full name, or case-insensitive). If no match, list available names and ask.

   Cartesian-product the scoped members with the scoped dates → ordered list of (member, date) pairs. This list drives the fan-out.

6. **Resolve per-member timezone**:
   - Use the member's `Timezone` (IANA name) from `team.md` if recorded.
   - Otherwise fall back to the caller's `Timezone` from `identity.md`'s `## Profile`.
   - The resolved TZ for each pair is passed to the executor; the executor uses it to interpret the date, set output filename's local date, and stamp `Time:` fields with the right offset.

7. **Fan out**:

   - **Single (member, date) pair**: skip the spawn. Run steps E1–E4 inline. Sub-agent overhead is not worth it for one pair.

   - **Multi-pair**: spawn one Agent (sub-agent_type=`general-purpose`) per pair. **Batch by member, not by day.** The Slack MCP rate-limits per session — concurrent sub-agents querying different members' Slack simultaneously trip this limit and return 0 results. Safe pattern: run all dates for one member in parallel (different date windows, same user = no contention), then wait for that member to complete before starting the next member. Never include more than one member in the same parallel batch. Each member's dates emit as one Agent tool-call message (up to 5 dates in parallel), then wait before starting the next member.

   **Sub-agent prompt template** — fill in for each pair:

   ```
   You are an executor sub-agent for /collect-team-activity. Your job is steps
   E1–E4 of the collect-team-activity SKILL.md for exactly one (member, date)
   pair. Do not deviate from the executor contract.

   Inputs:
   - Member name:        {member_name}
   - Member slug:        {member_slug}
   - Member Slack ID:    {slack_id}
   - Member Jira ID:     {jira_account_id}
   - Member GitHub:      {github_handle}
   - Member timezone:    {iana_tz}
   - Jira cloud ID:      {jira_cloud_id}
   - Date (local):       {YYYY-MM-DD}
   - Output file path:   <workspace>/collected/collect-team-activity/{member_slug}/{YYYY-MM-DD}-{member_slug}-activity.md
   - Run ID:             {run_id}

   Read .claude/skills/collect-team-activity/SKILL.md and follow the
   "Executor Contract" section. Do not run the orchestrator steps.
   Write the output file. Call /log with status SUCCESS, PARTIAL, or
   FAILED. Return a one-line summary in the form:

       {SUCCESS|PARTIAL|FAILED} {member_slug} {YYYY-MM-DD}: {n} items, gaps: {list or "none"}

   Do not return MCP raw responses to the orchestrator — the output file
   is the durable artefact.
   ```

   **Permission inheritance reminder**: sub-agents inherit `.claude/settings.json` only. They cannot prompt for permissions. If a sub-agent fails with a permission error, the allowlist needs updating — do not retry as-is.

8. **Aggregate**:
   - Wait for the last batch to return.
   - For each (member, date) pair, read the output file at the pre-computed path.
   - Parse the `Status:` header (SUCCESS / PARTIAL / FAILED) and the `## Activity` count.
   - Build the summary report (see "Reporting" below).
   - Emit the orchestrator-level `/log` entry summarising the run.

## Executor Contract

This section describes the steps a sub-agent (or the orchestrator inline, in single-pair mode) follows for one (member, date) pair. **Inputs**: member name + slug, member Slack ID, member Jira account ID, member GitHub handle, member IANA timezone, Jira cloud ID (per-Atlassian-instance — sourced from `identity.md`'s `## Profile`, *not* from `team.md`, since it identifies the org's Atlassian instance and is shared across all members), single date (`YYYY-MM-DD`), pre-computed output file path, run ID.

**Status semantics** (apply consistently across the file's `Status:` header, the `/log` call, and the returned summary string):

- **SUCCESS** — every required source responded successfully, regardless of result count. Zero items is still SUCCESS. "Quiet day", "day in progress", "low coverage", "PTO", "weekend" are all SUCCESS with zero items.
- **PARTIAL** — at least one required source failed mid-collection (timeout, error, permission denied during pagination) after others had already returned data. The output file should record what was captured under `## Activity` and the failed source under `## Gaps` with the error reason. `/log` status is `WARNING`.
- **FAILED** — a required source (Slack MCP, Atlassian MCP) was unavailable from the start, or the pair couldn't be processed at all. The output file is written with empty `## Activity` and the failure reason under `## Gaps`. `/log` status is `FAILED`.

Do **not** use PARTIAL to signal "the day isn't over yet" or "I expected more data than I found". Coverage-time concerns belong in the `## Summary` prose, not in the Status field.

**E1. Collect from sources in parallel** (single member, single day):

**Pagination — required for every source.** Loop until exhausted; never trust the first page as the full result.

| Source | Mechanism |
|---|---|
| Slack | `cursor` — loop until no next cursor |
| Jira | `nextPageToken` — pass it back until `isLast: true` |
| Confluence | `cursor` — loop until no next cursor |
| GitHub (`gh`) | `--limit 100` per query is effectively always enough for a single day; warn-if-hit rather than paginate further |

**Stop-and-flag rule**: at single-day, single-member granularity, if pagination hits 5+ pages on any single source — stop and flag in `## Gaps`. 500 events from one source on one day for one person is anomalous — almost always a wrong date boundary or a wrong identity filter.

**On partial failure**: see Status semantics above — set Status=PARTIAL, /log status=WARNING, list the failed source under `## Gaps` with its error reason, capture what's available, do not abort.

**Date boundary handling** (consistent across sources):

The local-day window is `[date 00:00:00, next_day 00:00:00)` in the member's IANA TZ. Compute:
- `tz_offset` from the IANA name (e.g., `Asia/Dubai` → `+04:00`, `Europe/London` → `+01:00` BST or `+00:00` GMT depending on date).
- `local_start = {date}T00:00:00{tz_offset}` and `local_end = {next_day}T00:00:00{tz_offset}`.
- `utc_start = local_start.astimezone(UTC)` and `utc_end = local_end.astimezone(UTC)`.

Worked example for `date=2026-04-30`, `tz=Asia/Dubai`:
- `local_start = 2026-04-30T00:00:00+04:00` → `utc_start = 2026-04-29T20:00:00Z`
- `local_end   = 2026-05-01T00:00:00+04:00` → `utc_end   = 2026-04-30T20:00:00Z`

Per-source query parameters:
- **Slack** — `after = utc_start`, `before = utc_end` (Unix timestamps). Or use `from:<@id> on:{date}` query modifier; Slack interprets `on:` in the workspace TZ which is usually fine for GCC teams.
- **`gh search`** — pass full ISO timestamps with the offset, not bare dates: `--created "{local_start}..{local_end}"`. Bare `YYYY-MM-DD..YYYY-MM-DD` interprets dates in UTC and shifts the window by the TZ offset, missing/misattributing PRs at day boundaries.
- **Jira / Confluence** — pass `{date}` and `{next_day}` as `YYYY-MM-DD` strings with the half-open `>=` / `<` boundary (see Jira section). **Caveat**: Jira and Confluence evaluate JQL/CQL date literals in the *user's profile timezone*, not UTC — if the member's Jira profile TZ differs from the executor's resolved TZ, results drift by hours.

**Slack:**
- Search `slack_search_public_and_private` for messages from the member using `{slack_id}`. This surfaces all channels the caller has access to, including private leadership/engineering channels that are legitimately relevant to team activity collection.
- Use `detailed` response format (never `concise` — it drops timestamps and permalinks). Set `include_context: false` to keep response size manageable.
- Capture: channel, timestamp, message summary, **full permalink as returned by the MCP** (thread reply permalinks include `?thread_ts=<parent_ts>&cid=<channel_id>` — preserve this exactly; never reconstruct Slack URLs).
- Note threads with decisions, guidance, approvals.
- Fold low-signal items (reactions, acks) into the related activity they refer to.
- Paginate using `cursor`.
- **Selective thread reading**: after paginating all results, identify messages where `Reply count > 0` AND the message is question- or decision-shaped (contains "?", directly @-mentions someone with a request, or uses "can we / should we / please / could you"). For each such message (cap at 5 per day), call `slack_read_thread` and capture the last substantive non-bot reply as a `Thread outcome:` line on the activity item. This surfaces whether a request was actioned, a decision was made, or the question is still open — without reading all threads indiscriminately.
- DMs are not accessible via MCP and are out of scope.

**Jira:** Two queries:
1. **Updated**: `(assignee = "{jira_account_id}" OR reporter = "{jira_account_id}") AND updated >= "YYYY-MM-DD" AND updated < "next_day"`
2. **Created**: `creator = "{jira_account_id}" AND created >= "YYYY-MM-DD" AND created < "next_day"`

- **Date boundary**: `>= "YYYY-MM-DD" AND < "next_day"`.
- Request minimal fields: `summary, status, issuetype, priority, updated, assignee, reporter`, with `view: "evidence"`. The default compact view silently drops `reporter` and every `accountId`, so the role split below would read empty rather than fail.

**Classify each returned ticket before capturing:**

- **Reporter-only** (member is reporter, not assignee): light capture only — key, title, assignee name, current status. No description or context block. Label as "Filed by {member}; assigned to {assignee-name}." These are planning/oversight signals, not delivery signals. Group separately in the output under "Jira — Filed (reporter-only)".

- **Assignee** (member is assignee, with or without also being reporter): full detail. Then check for execution evidence:
  1. Status is In Progress or Done → flag `execution: status-change`. Strong delivery signal.
  2. Status unchanged but ticket was `updated` in the window → check whether the member's `{jira_account_id}` authored any comment created within the window. Read comments for all such tickets in one search, `key in (...)` with fields `comment` and `view: "evidence"` (compact drops comment authors' ids). If yes → flag `execution: commented`. If no → flag `execution: none` (awareness/planning — ticket is in queue, not acted on). The search returns only the newest comments; when a ticket reports more `remaining` and none of those shown fall before the window, read on with `listJiraIssueComments` (`view: "evidence"`, `orderBy: "-created"`, `startAt` = the number already shown; its compact view also drops authors' ids) until the comments predate the window, before concluding `none`. `getJiraIssue` is not a comment source: it reports a comment count, not the comments.
  - At most 5 tickets per executor get a `listJiraIssueComments` follow-up, with as many pages each as the window needs (comment paging is exempt from the stop-and-flag rule). A follow-up that fails also gets `execution: unverified`. If more tickets need one, prioritise the most recently updated and flag the rest `execution: unverified` rather than `none`.

- **Both** (member is assignee and reporter): treat as assignee for detail and execution evidence.

Output: group tickets as "Jira — Owned (assignee)" and "Jira — Filed (reporter-only)" so downstream synthesis can apply role-appropriate interpretation.

**Confluence:**
- Uses the same Atlassian MCP as Jira.
- `searchConfluence` (takes CQL): `contributor = "{jira_account_id}" AND lastmodified >= "YYYY-MM-DD" AND lastmodified < "next_day"`.
- The `contributor` field already covers comments — a comment is a Confluence contribution. No separate comment query needed.
- For each result: capture space, title, type of contribution (created vs. updated, page vs. comment), URL.

**GitHub:** Run `bash .claude/skills/_shared/scripts/gh-activity.sh <token-handle> <subject> <start> <end>` from the workspace root (the shell starts there; do not `cd`), with the cached caller handle as `<token-handle>`, the member's GitHub username as `<subject>`, and the day's window as full ISO timestamps with the member's TZ offset. The script reads the caller's token inside its own process: the token never appears in tool output, and the active gh account is untouched. Sub-agents cannot answer permission prompts, and Claude Code refuses a top-level `$(...)` even under an allow rule; the allow list permits this one script by its path relative to the workspace root, so do not wrap, rename or copy it, and never write your own GitHub script. Send the command bare: nothing before it (no `cd`, no env vars) and nothing after it (no `> file`, `2>&1`, `|`, `;`, `&&`, `$?`). Any addition stops the allow rule matching and the call is refused. Read the output and exit code from the tool result; save the output with the file tools if you need it. Never call `gh auth switch`.

**If the script call is refused or fails, GitHub is not collected or only partly collected.** Record it in `## Gaps` with the reason, and set `Sources checked` to match; on exit 4, keep the sections that finished and name the ones that did not (see the exit codes below). Never list GitHub items found some other way (a PR link in Slack, a Jira dev panel) as GitHub collection, and never write `Gaps: None` when GitHub was not collected.

Pre-flight (read-only): confirm the cached handle is logged in via `gh auth status`. If absent, fail with **PARTIAL** and record the gap with a re-auth hint (`gh auth login --hostname github.com`).

Use **full ISO timestamps with the member's TZ offset**, not bare `YYYY-MM-DD` (the script rejects bare dates). Bare dates are interpreted as UTC, so for non-UTC member TZs the window slips by the offset (e.g., for Asia/Dubai, `--created "2026-04-30..2026-04-30"` covers UTC 04-30 = local 04-30 04:00 → 05-01 04:00, missing 4 hours of local 04-30 and including 4 hours of local 05-01).

The script runs four `gh search` queries with `--limit 100` — PRs authored (`--created`), PRs reviewed (`--updated`), issues authored (`--created`), issues commented on (`--updated`) — and prints four sections, each a `== <name>` line followed by a JSON array: `prs_authored`, `prs_reviewed`, `issues_authored`, `issues_commented`. Reviewed PRs and commented issues carry `updatedAt`, the last activity on the item, which is not necessarily the time of the person's own review or comment; use it to order items, not as their action time. A section holding 100 items hit the limit and may be truncated (`gh search` has no `has_more` flag); record it as a gap. Script exit codes: `2` bad arguments: fix the call if you built it wrong; if the GitHub login itself is missing or malformed, record a GitHub gap; `3` no token for the handle (revoked grant, deleted handle): record a GitHub gap with the `gh auth login --hostname github.com` hint; `4` a search failed, after the script has already waited and retried once if GitHub rate-limited it (one wait per run): keep the sections printed before it, and record the failed section with gh's error quoted verbatim (often a rate limit or an unknown login, not an auth fault); `5` gh is not installed: record the gap and continue; `127` the script was not found because the shell is not at the workspace root: do not `cd` (the call would be refused); record GitHub as a gap: "the shell was not at the workspace root". Any other exit code is unexpected: record it as a GitHub gap with the code.

- **Range syntax `A..B` is inclusive on both ends** — different from Jira's half-open convention. Using `next_day T00:00:00` as the upper bound therefore includes events at exactly midnight local; this is a 1-second overlap with the next day's window, acceptable for daily granularity.
- For each result: capture repo, number, title, URL.
- If `gh` is not available, note this gap and continue.

**Google Drive:** Permanently out of scope for this skill. The Drive MCP's only date filters (`viewedByMeTime`, `list_recent_files orderBy: lastModifiedByMe`) are caller-perspective — they cannot surface another user's activity. The `owners` query field is unsupported. Without admin / Drive Audit access, the Drive MCP cannot answer "what did this team member do". This is a permanent property of the skill, not a per-pair gap — do **not** list it in the per-file `## Gaps` section (see "Gaps discipline" under E3). The aggregate report mentions it once if relevant.

**Oversized responses (50KB+):** Write a targeted extraction script on the fly based on the actual response structure. Don't use pre-baked scripts — MCP schemas change.

**E2. Categorize each item** into one or more of (categories are role-neutral — an IC, PM, EM, or director will naturally use different subsets):
- `engineering` — Writing code, debugging, code reviews, technical problem-solving
- `architecture` — Design decisions, technical direction, system design, RFCs, design docs
- `team` — Mentoring, feedback, hiring, 1:1s, process improvements, onboarding
- `infrastructure` — Infra, cost optimization, security, DevOps, incident response
- `delivery` — Sprint work, project tracking, unblocking dependencies, release management
- `product` — Requirements, user research, feature specs, stakeholder alignment, roadmap
- `operational` — Process improvements, monitoring, on-call, documentation, cross-team coordination
- `strategic` — Executive comms, OKRs, cross-org initiatives, vendor relationships, budget
- `ai-engineering` — AI tool adoption, AI-powered workflows, AI strategy
- `growth` — Learning, conferences, training, certifications, knowledge sharing

**Capture a timestamp per item**: For each activity item, record the **earliest underlying event's timestamp** as ISO 8601 with timezone offset (e.g., `2026-04-12T14:32:00+04:00`), using the resolved member TZ. When an item spans multiple events, use the earliest.

**E3. Write the output file** to the pre-computed path. Create parent directories if missing.

**Re-run on the same (member, date)**: overwrite the file. Add a header line `**Re-collection**: previous run superseded YYYY-MM-DD HH:MM:SS` (UTC) below the title.

**Gaps discipline**: `## Gaps` lists *inaccessible* sources only — sources that failed at runtime or were unavailable. A source returning **zero results** is **not** a gap; it's a successful query reflected in the absence of items under `## Activity`. Permanent skill-level out-of-scope sources (Drive, DMs) are documented in this SKILL and the orchestrator's aggregate report — do **not** repeat them in per-file `## Gaps`. Typical valid Gap entries: `gh CLI not available`, `Confluence: timed out on page 2 — partial coverage`, `Slack permission denied`. Most files should have an empty Gaps section.

```markdown
# {Member Name} Activity: YYYY-MM-DD

## Status: SUCCESS
**Sources checked**: Slack, Jira, Confluence, GitHub (gh CLI / N/A)

## Summary
[1-2 sentences: what was the focus that day. If a quiet day or PTO, say so.]

## Activity

### [category]
- **[brief description framed by impact, not just action]**
  - Time: 2026-04-12T14:32:00+04:00
  - Sources: [Slack permalink], [JIRA-123](url), [PR #45](url)
  - Context: [why this matters — what decision was made, what was unblocked, what risk was mitigated]

### [category]
- ...

## Jira — Owned (assignee)
- [JIRA-123](url) [title] — [status] · execution: <status-change|commented|none|unverified>

## Jira — Filed (reporter-only)
- [JIRA-456](url) [title] — assigned to [name], [status]

## Gaps
[Only pair-specific runtime issues. Empty if no source was inaccessible.]
```

**E4. Log and return**:

```
/log run_id={run_id} skill=collect-team-activity status=<SUCCESS|WARNING|FAILED> detail={member-slug} YYYY-MM-DD: {summary}
```

If running as a sub-agent, return a one-line summary string in the form:

```
{SUCCESS|PARTIAL|FAILED} {member-slug} {YYYY-MM-DD}: {n} items, gaps: {list or "none"}
```

If running inline (orchestrator single-pair path), no return is needed — the orchestrator continues to step 8 with knowledge of the file path.

## Reporting

After aggregation:

**Single (member, date) pair**:
```
Team activity collected: {Member Name} (YYYY-MM-DD)
─────────────────────────────────────────────────────
Items found: {count}
Sources: Slack ({count}), Jira ({count}), Confluence ({count}), GitHub ({count or N/A})
Gaps: {list any inaccessible sources}
File: <workspace>/collected/collect-team-activity/{member-slug}/YYYY-MM-DD-{member-slug}-activity.md
```

**Multi-pair**:
```
Team activity collected: {first-date} to {last-date}
──────────────────────────────────────────────────
Members × days: {n}/{total} succeeded ({n_partial} partial, {n_failed} failed)
Total items: {sum across all SUCCESS/PARTIAL files}
Failed pairs: {list or "none"}
Files: <workspace>/collected/collect-team-activity/<member-slug>/...
```

## Logging

The orchestrator emits a single summary log entry on completion:

```
/log run_id=<run_id> skill=collect-team-activity status=<SUCCESS|WARNING|FAILED> detail=<scope-summary>: <n_pairs> pairs, <n_succeeded> succeeded
```

Each executor sub-agent emits its own per-pair log entry (E4 above). Use `manual` as `run_id` if the orchestrator was invoked directly by the user; otherwise pass through the calling agent's `run_id`.

## Important Rules

- **Every item must have at least one source link.** No exceptions. If you can't link to it, flag it as unverified.
- **Frame by impact, not action.** Not "merged PR #45" but "Shipped connection pooling fix that unblocked staging deployment (PR #45)".
- **Don't fabricate activity.** Only report what you find in the data sources. If someone had a quiet day, say so — that's useful signal too.
- **Never infer technical system names from shared vocabulary.** Use the exact service or system name from the source. If a source names an endpoint or service explicitly (e.g., `zeebe-cluster-gateway-zeebe-0`), use that name — do not substitute a related system (e.g., "Kafka") because they share vocabulary ("broker", "partition", "leader"). If the system name genuinely cannot be read from the source, write "system unclear" rather than guessing.
- **Gap notes are factual, not speculative.** When a source returns zero results, record the fact (e.g., "GitHub: 0 results in window"). Do not speculate on the cause ("likely private repo", "alternate handle", "permissions issue") unless verified — speculation in gap notes misleads downstream readers.
- **No DMs.** Direct messages are not accessible via MCP and are out of scope. Private channels are in scope — this skill uses `slack_search_public_and_private` because leadership-relevant decisions surface in private channels. Access is bounded by what the caller's Slack token can see.
- **Respect date boundaries.** Only include activity within the requested date range.
- **Always write the output file** — even on failure. The Status field (SUCCESS/PARTIAL/FAILED) lets calling agents check the result programmatically.
- **Don't duplicate with `/collect-my-activity`.** This skill collects *other people's* activity. For the user's own activity, use `/collect-my-activity`.
- **Identity write-back is orchestrator-only and fill-missing-only.** Sub-agents must not touch `identity.md`. The orchestrator never overwrites an existing value — log a `WARNING` and surface the discrepancy instead.
- **Sub-agents do not switch `gh` accounts or write their own GitHub scripts.** They run the shared `gh-activity.sh` with the cached handle. Never `gh auth switch`. The token lives in the script's process only — never in tool output or the conversation transcript.

## team.md Expected Format

The skill expects `<workspace>/me/team.md` to follow this structure:

```markdown
# My Team

## Direct Reports

### Alice Chen
- **Role**: Backend Engineer
- **Timezone**: Asia/Dubai
- **Slack**: U01ABC123
- **Jira**: 712020:abcdef-1234-5678-abcd-1234567890ab
- **GitHub**: alicechen

### Bob Smith
- **Role**: Frontend Engineer
- **Timezone**: Europe/London
- **Slack**: U02DEF456
- **Jira**: 712020:fedcba-4321-8765-dcba-0987654321ba
- **GitHub**: bobsmith
```

Platform IDs can be resolved by:
- **Slack**: `slack_search_users` by name, or check a user's profile in the Slack UI
- **Jira**: `lookupJiraAccountId` by email, or check in Jira admin. This is a roster step for you or the main session, never an executor: on Atlassian MCP it has no direct tool, so it runs through `discover` and `executeRead`, which the shipped allowlist does not grant, so sub-agents cannot run it.
- **GitHub**: the member's GitHub username
- **Timezone**: optional IANA name (e.g., `Asia/Dubai`); skill falls back to the caller's TZ if absent
