---
name: bye
description: End the session — summarize work, persist context, capture lessons, close the active marker
user_invocable: true
---

# Session End

You are wrapping up the current working session. Summarize, persist, and hand off. v2 paths assumed throughout; scope comes from the active session marker, never from cwd.

## Steps

1. **Resolve scope and find the session marker.** The skill's base directory is `<workspace>/.claude/skills/bye/`; resolve `<workspace>` by walking up three directory levels and validate that `<workspace>/.claude/.workspace` exists.

   **Primary path** — recall both `session_id` AND `project_slug` from conversation context (`/hello` logged both when it wrote the marker). Look up directly at the matching scope's `sessions/active/<session_id>.md` — scope is `<workspace>` if `project_slug = workspace`, else `<workspace>/projects/<project_slug>`. Deterministic — no scanning, no disambiguation.

   If `project_slug` is lost from context but `session_id` is recalled, probe `<workspace>/sessions/active/<session_id>.md` first, then `<workspace>/projects/*/sessions/active/<session_id>.md`. Still deterministic since `session_id` is unique by construction; the probe is two open() calls, not a scan.

   **Fallback path** — only if the `session_id` is unavailable from conversation context (e.g., compaction dropped it). Be honest with the user that the primary path failed; do not paper over the miss with broad scans. Then:
   - Recover scope and workstream from conversation context. If neither is known, ask the user.
   - Scan `<scope>/sessions/active/*-<workstream-slug>-*.md` (workstream-local only — no cross-scope scan, no cross-workstream scan).
   - 1 match → take it.
   - >1 matches → list each with age + open item summary; ask user to pick.
   - 0 matches → ask user which scope + workstream to write to. Proceed without a marker; step 3 will write narrative directly to a fresh file in `<scope>/sessions/`, and step 4 is skipped entirely.


2. **Summarize the session**: Review the conversation and identify:
   - What was accomplished (tasks completed, files changed)
   - Key decisions made
   - Open items and next steps
   - Problems encountered and how they were resolved
   - The open item bound to this session — is it complete? Ask the user if unclear; do not mark complete silently.

   If the user signals during summary that this isn't actually a session close (mind changed, more work to do), abort `/bye` — return to the conversation. The marker stays in `active/` untouched; no narrative is written, no promotion happens, no farewell prints. `/bye` can be re-invoked later when the session genuinely closes. There is no "paused" state in the system — `active/` already represents an open session.

3. **Write session narrative into the active marker**: Read the marker file at `<scope>/sessions/active/<filename>` (frontmatter already there from `/hello`). Append the session narrative body below the frontmatter closing `---`. No mtime-check — this is the session's own unique file; no other process writes to it.

   ```markdown
   # Session

   **Date**: YYYY-MM-DD
   **Duration**: ~Xh (estimate based on conversation length)
   **Workstream**: <workstream_slug>
   **Resumed at**: <ISO-8601>   (include this line only if the marker has a `resumed_at` field; omit otherwise)

   ## Accomplished
   - [list of completed items]

   ## Key Decisions
   - [list of decisions and rationale]

   ## Open Items
   - [ ] [next steps and pending work — grouped by workstream when listing across multiple]

   ## Problems & Resolutions
   - [issues encountered and how they were fixed]
   ```

   **0-match case** (no marker was selected at step 1): write the narrative directly to a fresh file at `<scope>/sessions/<YYYY-MM-DD>-<workstream-slug>-<HHMMSS>-<6hex>.md` instead — matches the filename format `/hello` step 14 uses. Skip step 4 entirely (the file is already at its final location).

4. **Promote the session marker** (critical state transition — must run immediately after step 3): Move `<scope>/sessions/active/<filename>` → `<scope>/sessions/<filename>` (directory move only — filename unchanged). Sessions accumulate in `<scope>/sessions/` indefinitely by design — the workstream file is the system of record (status, decisions, open items, all promoted by step 5); session files are the per-session journal, kept for archaeology and not pruned automatically.

   This step runs early — immediately after the narrative is written — so that failures in later steps (workstream update, lessons, MEMORY) do not leave an orphan marker in `active/`. The only orphan window is the fs operation between step 3's write and step 4's move; if `/bye` fails inside that window, the orphan retains its full narrative and is recoverable.

   Skip case: 0-match — step 3 wrote the file directly to `<scope>/sessions/`; nothing to promote. (The user-abort branch at step 2 never reaches this step, so there's no other skip case.)

5. **Update active workstream**: Edit `<scope>/workstreams/<workstream_slug>.md` in place — surgical edits, not full rewrite. Use mtime-check. Status line → today's date + one-line current state. Open Items → mark closed `[x]` (with user confirmation), append new `[ ]`. Decisions → append today's with `[YYYY-MM-DD]` prefix. Long-form artifacts (drafts, comparison docs, design specs over ~15 lines) go to `<scope>/artifacts/<workstream_slug>/<filename>.md`; the workstream gets a one-line pointer.

6. **Identify lessons**: Review the session for:
   - Mistakes made and corrections applied
   - New patterns or conventions discovered
   - User preferences expressed
   - Tool tips or workarounds found
   - Architectural insights

7. **Capture lessons**: If any lessons were identified, invoke the `/lessons` skill with the identified lessons. Pass `project_slug` and `session_id` from the session marker as context — the marker is promoted before this step and `/lessons` cannot re-scan `active/`. `/lessons` uses these to resolve scope directly without scanning.

8. **Curate MEMORY.md**: First, read the full lessons inbox at both levels (skip the workspace read if scope = workspace — same file):
   - `<scope>/.claude/memory/lessons-learned.md`
   - `<workspace>/.claude/memory/lessons-learned.md`

   Identify promotion candidates — either criterion qualifies:
   - Confirmed by this session's work (the lesson was validated or re-encountered in the current conversation)
   - Recurring pattern across 2+ inbox entries (same insight appearing in different sessions — exercise judgment, not string-matching)

   For each candidate: promote into the MEMORY.md at the same scope as the lesson's source inbox (`<scope>/.claude/memory/MEMORY.md` for scope-level lessons; `<workspace>/.claude/memory/MEMORY.md` for workspace-level). Apply standard curation: edit to reflect current truth, don't just append, remove stale entries. Then remove the promoted entry from its source `lessons-learned.md` — that file is an inbox, not an archive.

9. **Update personal workspace** (`<workspace>/me/` — never per-project, regardless of marker scope):
   - **identity.md**: Fill missing fields by name across the whole file. Never modify Preferences, Writing Style, Growth, or organic content.
   - **brag-log.md**: Append "led / oversight / flagged" accomplishments only; BAU is not brag-worthy.
   - **growth.md**: Note focus-area gaps surfaced during the session. Don't over-record.
   - **team.md**: Propose additions; do not write silently. Starter is scaffolded by `/setup-workspace init`.

10. **Check project docs for staleness**: If this session made structural changes (new dependency, changed data flow, new service interaction, renamed concept):
    - Consult the project's **doc-sync table** if its `CLAUDE.md` has one (the per-project surface→content mapping, per the doc-maintenance convention) and check each listed surface against what the session changed. If there's no table, fall back to the standard set: `<scope>/.claude/memory/project-context.md` and `<scope>/.claude/docs/architecture.md` (skip a file silently if it doesn't exist).
    - **Propose** specific updates only where the session changed something a doc actually claims. Do NOT write them silently — the user approves or skips. Keep this lightweight; never run a heavy documentation pass inline.
    - If the staleness is more than a quick touch-up **and `/scribe` is available**, nudge: "these docs look stale — want to run `/scribe --from-session`?" If that skill isn't installed, just surface the stale surfaces and move on — never nudge toward a command that isn't there.

11. **Suggest contributions**: If any lessons from this session seem broadly useful beyond this scope, mention that the user can run `/contribute` to generalize and stage them for Memnyx.

12. **Output farewell**:

    ```
    Session Complete
    ================
    Scope: [workspace | projects/<slug>]
    Tasks completed: [count]
    Lessons captured: [count]
    Open items: [count]
    Workstream: [name] — updated / none
    Memory: updated / unchanged
    Personal: brag-log updated / identity updated / unchanged
    Marker: [path] — promoted to sessions/

    See you next time! Run /hello to pick up where we left off.
    ```

## mtime-check protocol

For every shared-file write at steps 5, 8, 9 (not step 3 — the session file is the session's own unique file; no mtime-check needed):

1. Read the file; capture mtime.
2. Compute the edit.
3. Re-stat. If mtime changed since the read, re-read and re-apply the targeted change. Retry up to 3 times.
4. Write.

On retry exhaustion (>3 conflicts), prompt the user.

## Auto-memory branch (deferred)

When auto-memory is adopted (per `v2-design-principles.md` §Session lifecycle), step 7 routes through `/memory-hygiene graduate` instead of `/lessons`. Unused until adoption.
