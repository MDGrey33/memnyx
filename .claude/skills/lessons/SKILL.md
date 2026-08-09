---
name: lessons
description: Capture and integrate lessons learned. Two modes — capture (single lesson) and scan (mine session files or extended JSONL logs for skill-change proposals).
user_invocable: true
args: Optional. Free-text lesson, OR `scan` (default scan of session files), OR `scan --deep` (deep scan of JSONL transcripts).
---

## Model Selection

- **Default model (capture mode):** Haiku — appending a structured lesson is a formatted write
- **Scan mode (default depth):** Sonnet — clustering signals from session files into skill-change proposals is a judgment task
- **Scan mode (deep):** Opus when transcript count > 20 — cross-session synthesis across raw JSONL needs larger reasoning

# Lessons Learned Handler

You operate in one of two modes, dispatched by the first argument:

| First token | Mode |
|---|---|
| `scan` | Scan mode (default depth) — read recent session markdown summaries |
| `scan --deep` | Scan mode (deep) — read recent JSONL extended transcripts |
| anything else (or empty) | Capture mode — record a single lesson |

---

## Resolve scope (every mode)

Before dispatching to a mode, locate the workspace and resolve scope from the active session marker.

The skill's base directory is `<workspace>/.claude/skills/lessons/`; resolve `<workspace>` by walking up three directory levels and validate that `<workspace>/.claude/.workspace` exists.

Scan active markers from `<workspace>/sessions/active/*.md` and `<workspace>/projects/*/sessions/active/*.md`. Parse frontmatter (`project_slug`, `workstream_slug`, `session_id`).

- One match → scope is `<workspace>` if `project_slug = workspace`, else `<workspace>/projects/<project_slug>`.
- >1 matches → ask the user which session this invocation is scoped to.
- 0 matches → check whether `project_slug` and `session_id` were passed as context from `/bye`. If yes, derive scope from `project_slug` (`<workspace>` if `project_slug = workspace`, else `<workspace>/projects/<project_slug>`) and proceed. If no context was passed, surface as a bug and abort (manual invocation: ask the user for scope instead).

Modes A and B use `<scope>` for input/output paths. Mode C is workspace-wide; the marker is read for scope-attribution decoration only.

`<scope>` is only ever the workspace root or a project directory — **a workstream is never a scope of its own.** Workspace-level and project-level workstreams both resolve to the scope containing them, `<workspace>` and `<workspace>/projects/<project_slug>` respectively; `workstream_slug` never routes input or output. A scan spans every workstream at its scope deliberately: recurrence across workstreams is the strongest signal the clustering step has, and routing per workstream would fragment clusters below Mode B step 4's threshold and suppress real proposals.

---

## Mode A: CAPTURE (default)

Triggered when the arg is absent or is free text (not starting with `scan`).

Lessons in capture mode come from:
- The `/bye` skill passing identified lessons
- The user invoking `/lessons "description of what was learned"`
- Manual invocation with `/lessons` (ask the user what was learned)

### Steps

1. **Gather lessons**: If lessons were passed as input, use those. If invoked manually without input, ask the user what they learned.

2. **Categorize** each lesson into one of:
   - `convention` — code style, naming, project patterns
   - `bug-pattern` — common mistakes, gotchas, debugging insights
   - `preference` — user preferences for tools, workflow, communication
   - `architecture` — structural decisions, design patterns
   - `tool-usage` — tips for tools, CLIs, MCP servers, frameworks

3. **Append to lessons file**: Read `<scope>/.claude/memory/lessons-learned.md` with mtime capture, then append each lesson under the appropriate category section with this format:

   ```markdown
   - **[YYYY-MM-DD]** Description of the lesson
   ```

4. **Trigger skills-manager**: Invoke the `/skills-manager` skill to assess whether the lessons warrant updates to any skill files. Pass the lessons as context.

5. **Report**:
   ```
   Lessons captured: [count]
   Categories: [list]
   Skills review: [triggered / no changes needed]
   ```

---

## Mode B: SCAN (default depth)

Triggered by `/lessons scan` (no `--deep` flag).

Input source: `<scope>/sessions/*.md` — markdown summaries written by `/bye`. (Working state lives at scope root, not under `.claude/memory/`.)

### Steps

1. **Select window**: list files modified in the last 7 days. If fewer than 3 exist, expand to the last 14 days. Cap at 20 files — prefer the most recent.

2. **Read each file** and extract signals:
   - User corrections ("no", "don't", "stop doing X", "that's wrong")
   - User confirmations ("yes exactly", "perfect", "keep doing that")
   - Tool failures or repeated retries on the same call
   - Workarounds that worked after an initial failure
   - Explicit mentions of a skill name + a problem
   - Abandoned approaches (task started, dropped mid-session)

3. **Cluster signals by target skill**: for each signal, identify which skill *should have* prevented or handled it. Group by skill name. Signals with no clear target go into a `cross-cutting` bucket.

4. **Draft skill-change proposals**. For each cluster of 2+ related signals, draft one entry:
   ```markdown
   - **skill:** <name>
   - **change:** <what to add, remove, or rewrite>
   - **why:** <one-sentence rationale>
   - **evidence:** <session-file refs, e.g. `session-2026-04-19_144813.md:L42`>
   ```

5. **Write proposal file** to `<scope>/artifacts/lessons/lessons-scan-<YYYY-MM-DD>-default.md` (mtime-check on write), resolved as above — a workspace-scoped scan writes to `<workspace>/artifacts/lessons/`, a project-scoped scan to `<workspace>/projects/<project_slug>/artifacts/lessons/`. Output lands at the same scope the input was read from, whichever it is. Never `contributions/` — see Downstream skills.
   ```markdown
   # Lessons scan — default mode — <YYYY-MM-DD>

   Window: <N> session files, <start-date> to <end-date>
   Signals found: <count>
   Proposals: <count>

   ## Proposed skill changes
   <proposals>

   ## Cross-cutting observations
   <any signals that don't map to a single skill>
   ```

6. **Hand off to skills-manager**: Invoke `/skills-manager` with the proposal file path as context. Skills-manager runs its own holistic-review → approval-gate → apply workflow.

7. **Report to the user**:
   ```
   Scan mode: default
   Window: <N> files
   Proposals written: <count> → <scope>/artifacts/lessons/lessons-scan-<date>-default.md
   Skills-manager: triggered

   Review the proposals. Any that generalise beyond this workspace can be staged
   for upstream with /contribute — your call, per proposal.
   ```

---

## Mode C: SCAN --deep

Triggered by `/lessons scan --deep`.

Input source: `<harness-transcript-dir>/*.jsonl` — raw harness transcripts, one file per session, turn-by-turn, where `<harness-transcript-dir>` is this workspace's directory under `~/.claude/projects/` (resolved below).

**The `*.jsonl` glob is load-bearing — never widen it to the directory.** These directories are not flat: alongside the transcripts sit a per-session sidecar directory for each session id, holding spilled `tool-results`, and a `memory/` directory holding the harness's auto-memory. Walking either would pull raw tool output and the user's personal memory files into the scan, and evidence refs would then cite them in a proposal file.

Transcripts live only here — never in the workspace. The harness names each directory after the **realpath** of the session's working directory with path separators flattened (`/Users/me/workspace` → `-Users-me-workspace`), so canonicalise `<workspace>` with `realpath` *before* flattening it and matching the candidate list. Skipping that step silently breaks the scan whenever the workspace is reached through a symlink — the flattened logical path matches nothing, and Mode C stops as though no transcripts existed.

**Match the flattened path exactly, or as a prefix that ends at a separator.** A bare prefix match is wrong: a sibling workspace named `workspace2` flattens to a name that starts with the same characters as `workspace`, and multiple workspaces are supported. The separator condition keeps genuine descendants — sessions launched from a project clone under the workspace — while excluding the sibling. If nothing matches, report that and stop; never fall back to another root's transcripts, which belong to unrelated work and would ground proposals in evidence this workspace cannot check.

### Steps

1. **Select window**: list JSONL files modified in the last 3 days. Note the unbounded count first — if >20, use Opus model for this scan. Then cap at 15 files, preferring the most recent.

2. **Scan each JSONL**. Each line is a JSON object representing one turn (user message, assistant response, tool call, tool result). Look for signals the markdown summary could have missed:
   - Mid-turn user frustration ("why are you...", "stop", multiple "no" in a row)
   - Tool-retry loops (same tool called 3+ times with similar args and errors)
   - Long tool-result dumps the assistant ignored
   - Reasoning chains that contradicted the final action
   - Abandoned subagent launches
   - Skills invoked that failed silently
   - Repeated permission denials on the same tool

3. **Cluster signals by target skill** — same as default scan, but the signal vocabulary is richer (raw tool errors, turn-level sentiment, not just end-of-session summary).

4. **Draft skill-change proposals** — same format as default scan, but evidence refs point to JSONL files and line numbers:
   ```markdown
   - **evidence:** `010cbd9d-adb5-4730-8121-64c158238a39.jsonl:L1247`
   ```

5. **Write proposal file** to `<workspace>/artifacts/lessons/lessons-scan-<YYYY-MM-DD>-deep.md` (mtime-check on write; same structure as default-mode proposal, with `Mode: deep` and `Scope attribution: <workspace | projects/<slug> from marker>` in the header). Workspace root, not `<scope>` — this mode is workspace-wide by design, so its output belongs where its input does. Never `contributions/`.

6. **Hand off to skills-manager** — same as default scan.

7. **Report to the user**:
   ```
   Scan mode: deep
   Window: <N> JSONL files (<total line count>)
   Proposals written: <count> → <workspace>/artifacts/lessons/lessons-scan-<date>-deep.md
   Skills-manager: triggered

   Review the proposals. Any that generalise beyond this workspace can be staged
   for upstream with /contribute — your call, per proposal.
   ```

---

## mtime-check protocol

For every shared-file write (Mode A append; Mode B/C proposal write):

1. Read the file; capture mtime.
2. Compute the edit.
3. Re-stat. If mtime changed since the read, re-read the file and re-compute the edit from scratch. Retry up to 3 times.
4. Write.

On retry exhaustion (>3 conflicts), prompt the user.

## Division of labor

This skill **detects** (finds what needs to change). `skills-manager` **governs** (decides and applies changes). Never edit skill files from within `lessons` — always hand off.

## What NOT to scan

- Files older than the window (noise swamps recent signal)
- JSONL files > 50MB (probably a stuck session, skip)
- Sessions flagged as test/scratch in their filename

## Downstream skills — do not duplicate

- **`contribute`** operates on captured lessons to prepare upstream Memnyx contributions. Downstream of this skill.
- **Never invoke `contribute` from here, and never write into `contributions/`.** A scan proposal is an unvalidated hypothesis carrying local evidence refs; a contribution is a generalised, human-reviewed claim. Deciding which proposals are worth upstreaming is the reviewer's judgment call, made after reading them — surface the option in the report and stop there.
