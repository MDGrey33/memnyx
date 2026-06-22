---
name: hello
description: Start a session — locate workspace, classify cwd, resolve project + workstream + open item, load memory, write session marker, recap context
user_invocable: true
---

# Session Start

You are starting a new working session. Resolve the active context, load memory, and orient the user.

## Steps

### 1. Self-locate the workspace

The skill's base directory is `<workspace>/.claude/skills/hello/`. Resolve `<workspace>` by walking up three directory levels. Validate that `<workspace>/.claude/.workspace` exists. If validation fails, abort with a setup-broken error — this is not recoverable from inside /hello.

### 2. Classify cwd

Compute one of five cases. The result is a *hint* for phrasing in step 7; it does not by itself decide the active project.

A session whose cwd is outside `<workspace>/` is allowed in **exactly ONE** case: cwd is a **registered project's own clone**, launched with `--add-dir <workspace>` (the *Registered project (external clone)* case below). The workspace is located in step 1 from this skill's own base directory, which is what makes that one case workable. **Every other outside-workspace cwd is refused** (the *Outside workspace (refuse)* case). This is a closed exception — do NOT extend it to any other outside-workspace scenario, and do NOT improvise a project binding for a directory that is not a registered project's clone.

- **Registered project (in-workspace)** — cwd is under `<workspace>/projects/<slug>/` and `<slug>` is in the registry. Hint = that project.
- **Registered project (external clone)** — cwd is *not* under `<workspace>/`, **and** `realpath(cwd)` is (or is under) `realpath(<workspace>/projects/<slug>)` for some registered `<slug>` — i.e. launched directly from the project's own clone with the workspace supplied via `--add-dir`. This is the only sanctioned outside-workspace case. Hint = that project. **In this case the project folder's own `.mcp.json` and `.claude/settings.json` are in effect, not the workspace's** — workspace-scoped MCP servers do not load (user-scope ones still do). Surface this plainly in the recap (step 6) so the engineer is not surprised by a different MCP/settings surface.
- **Workspace-level** — cwd equals `<workspace>/`, or is under `<workspace>/` but not under `<workspace>/projects/<slug>/`. Hint = workspace-level work.
- **Unregistered project** — cwd is under `<workspace>/projects/<slug>/` but `<slug>` is NOT in the registry. Hint = offer inline registration via `/setup-workspace add-project`.
- **Outside workspace (refuse)** — cwd is not under `<workspace>/` **and** does not resolve to any registered project's clone. **Refuse and stop here.** Give a clear, specific message: the session was started outside the workspace and outside every registered project, so Memnyx cannot bind it to a project. Tell the user exactly what to do — `cd` into `<workspace>` (or into a registered project's clone) and rerun `/hello` — and, if they intended the current folder, that it is not a registered project (point them at `/setup-workspace add-project`, or at launching from the workspace).

### 3. Load workspace-scope context

Read all in parallel; skip silently if a file is missing:

- `<workspace>/me/identity.md`
- `<workspace>/.claude/memory/MEMORY.md`
- `<workspace>/.claude/memory/lessons-learned.md`
- `<workspace>/.claude/memory/project-context.md`

Read the project registry directly from `<workspace>/.claude/projects-index.json` (registry mutations go via `/project-registry`; reads bypass it). Treat missing as empty.

Session narrative for the active workstream loads after workstream resolution at step 11 — not here.

### 4. Scan active session markers

List markers from:

- `<workspace>/sessions/active/*.md` (workspace-level sessions)
- `<workspace>/projects/*/sessions/active/*.md` (project-level sessions)

For each, parse frontmatter (`project_slug`, `workstream_slug`, `open_item_slug`, `started_at`) and compute age. **Held purely for the recap at step 6** — informational only. No control-flow consumer in this skill; disambiguation work happens in step 12 against a workstream-local scan, not against this list.

### 5. Run /mcp-doctor

Inline call in session mode. Surfaces server health to fold into the recap.

### 6. Recap (workspace-scope)

```
Session Start
=============
Workspace:  <path>
Cwd hint:   <workspace-level | project=<slug> | project=<slug> (external clone) | unregistered=<slug> | outside>
Last session: <one-line summary, or "No previous sessions">
Active sessions elsewhere: <list with ages, or "none">
MCP status: <from /mcp-doctor>
Lessons:    <N> conventions, <M> patterns
Identity:   loaded / placeholder
```

**"Last session" sourcing.** Scan both `<workspace>/sessions/*.md` (workspace-level closed sessions) AND `<workspace>/projects/*/sessions/*.md` (project-level closed sessions). Sort by the date and time embedded in each filename — not raw lexicographic order, since the workstream slug between them makes that unreliable. Take the most recent; read its frontmatter for `project_slug` and `workstream_slug` to build the one-line summary. Output "No previous sessions" only when both globs return no files.

### 7. Resolve project (open-ended)

Phrasing branches on the cwd hint. In every variant, be honest about inference and invite explicit override — never imply the model deterministically knows whether work "is a project":

- **Workspace-level hint** → "What are you working on today? I'll infer whether to treat it as project work or workspace-level work and confirm before proceeding. You can also explicitly say 'register a new project' or 'this is a one-off task' to skip the inference."
- **Registered-project hint** → "Looks like you're in `<slug>`. Continuing on that, or working on something else today? (If something else, I'll infer the scope and confirm — or you can ask me to register a new project.)"
- **Registered-project (external clone) hint** → "You're in the `<slug>` clone (the workspace references it via symlink, and you launched with `--add-dir`). Continuing on `<slug>`, or something else? Heads-up: this session is using `<slug>`'s own MCP servers and settings, not the workspace's." Then resolve exactly as for the registered-project hint.
- **Unregistered-project hint** → "`<slug>` isn't registered yet. Want me to register and scaffold it now (calls `/setup-workspace add-project`), or are you treating this as a one-off?"

Resolution rules — match the registry first:

1. **Semantic match against registered slugs and descriptions.** If a plausible match exists, confirm with the user ("That sounds like `<slug>` — continue there?"). The registry is the source of truth for whether work belongs to a project; topic shape (personal, cross-cutting, leadership update, team activity, 1:1 prep, etc.) is not a signal to skip the registry — users may register a project (e.g., `my-work`) precisely for that work.
2. **Ambiguity** between two or more registered projects → ask one clarifying question.
3. **Explicit user override.** If the user explicitly says "register a new project" / "create a project" / "one-off task" / similar, honour that immediately without further inference. Explicit override always beats inference.
4. **No match, user describes a new project** → fall through to step 8 (new-project handling).
5. **No match, user confirms it's not project-bound** → set scope = workspace-level. Workspace-level is the fallback when no project fits — never the default for a topic shape.

**Empty registry caveat.** When no projects are registered, paths 1–2 are unreachable; the resolver collapses to inference (paths 3–5) with no anchored confirmation. State this honestly in the question rather than pretending registry-backed matching is happening.

### 8. New-project handling

When the user names a project that isn't registered (and it's not the unregistered-cwd branch):

1. Confirm the slug with the user (lowercase, hyphens, starts with a letter).
2. If `<workspace>/projects/<slug>/` doesn't exist, instruct the user to create it first:
   - Fresh project: `mkdir <workspace>/projects/<slug>`
   - Existing repo elsewhere: `ln -s /path/to/real/repo <workspace>/projects/<slug>`
3. Run `/setup-workspace add-project <slug> [description]`. Scaffolds the project AND registers it in one step. Do NOT call `/project-registry add` directly — it doesn't scaffold memory or session-marker dirs.

The project is now selected.

### 9. Layer project-scope context (when scope = project)

Read in parallel; skip silently if missing:

- `<workspace>/projects/<slug>/.claude/memory/MEMORY.md`
- `<workspace>/projects/<slug>/.claude/memory/lessons-learned.md`
- `<workspace>/projects/<slug>/.claude/memory/project-context.md`

List `<workspace>/projects/<slug>/workstreams/*.md` (read on demand at step 11).

**These reads are load-bearing beyond memory.** Reading a file under `<workspace>/projects/<slug>/` triggers Claude Code's on-demand discovery of that project's `.claude/skills/`, registering them as invocable skills (autocomplete included) for the rest of the session. Do not replace these reads with cached or pre-aggregated content — the discovery side effect is part of this step's contract. Discovery covers the skills format only; legacy `.claude/commands/` files in a project never register this way (they load when the session starts in that project, or via an explicit `--add-dir`/`/add-dir` — never on-demand).

For workspace-level scope, the equivalents at `<workspace>/.claude/memory/` are already loaded in step 3; just list `<workspace>/workstreams/*.md`.

Session narrative for the active workstream loads after workstream resolution at step 11.

### 10. Cognee semantic search (conditional no-op)

If cognee is loaded (per /mcp-doctor's report), call `cognee_search "project context recent work"` and fold useful findings into the recap. If cognee is not loaded, skip silently.

### 11. Resolve workstream

To seed the hint: list `<scope>/sessions/*.md`, parse `<YYYY-MM-DD>` and `<HHMMSS>` from each filename, sort by parsed datetime descending, take the most recent. Extract the workstream slug from the filename (`<YYYY-MM-DD>-<workstream-slug>-<HHMMSS>-<6hex>.md` — the slug is the middle segment between the date and the timestamp). If no session files exist, skip the hint.

Phrasing branches on whether a recent session file was found:

- **Found** → "Last time you were on `<workstream-slug>`. Continue, or working on something else?"
- **Not found** → "Which workstream are you on, or is this a new one?"

Resolution:

- **Continue** → load the named workstream file from the active scope's `workstreams/`.
- **Match an existing workstream** (semantic, not regex) → confirm and load.
- **New** → derive a slug from the user's description (sanitisation below); offer for confirmation; create `<scope>/workstreams/<slug>.md` with a one-line header (`# Workstream: <slug>` plus start date). No open-items section pre-populated — that's content `/bye` accumulates.

**After workstream is confirmed**: find the most recent `<scope>/sessions/*-<workstream-slug>-*.md` and load it as the session narrative. Skip silently if none exists.

**Slug sanitisation** (workstream and open-item slugs):

- Lowercase the input.
- Replace any non-alphanumeric character (except hyphens) with hyphens.
- Collapse repeated hyphens into single hyphens.
- Trim to 50 characters.
- Force `.md` extension on workstream filenames.
- Reject input containing `..`, `/`, or other path separators — re-prompt.
- Always join the sanitised slug to `<scope>/workstreams/` (never concatenate raw user input into a path).
- Fail with a validation prompt if the input cannot be safely normalised.

### 12. Check for an existing active marker on this workstream

Now that scope and workstream are known, scan `<scope>/sessions/active/*-<workstream-slug>-*.md` — workstream-local only. No cross-scope scan; step 6's recap already surfaced cross-scope sessions for the user's awareness, and acting on those is the user's decision, not this skill's.

Branches by count:

- **0 matches** → proceed to step 13.
- **1 match** → parse the marker's frontmatter. Show:

   ```
   Active marker on this workstream:
     Open item: <open_item_summary>
     Started:   <age> ago
     File:      <relative path>

   Resume that work, or start fresh?
   ```

   - **Resume** → adopt the marker as this session's marker. Load `open_item_slug` and `open_item_summary` from the frontmatter. **Cross-reference against the workstream file's open checkboxes — if the marker's `open_item_slug` maps to an item already marked `[x]`, the marker is stale; prompt the user to pick the live work from the workstream's `- [ ]` list before adopting.** Write `resumed_at: <ISO-8601 with TZ offset>` into the marker's frontmatter — add the field if missing, replace if present (only the most recent resume is tracked, no history list). Use mtime-check on this write since a concurrent `/hello` on the same marker could in principle race. **Skip step 13 (open-item resolution) and step 14 (marker write).** Record the resume decision for the final recap.
   - **Fresh** → proceed to step 13. The prior marker stays in `active/` untouched — we do not auto-promote, auto-delete, or auto-modify. Flag it in step 15's recap so the user can decide what to do with it.

- **>1 matches** → list each candidate with age + open item summary. Ask the user to pick one to resume, or to start fresh. Apply the same downstream branches as the 1-match case. Any unrescued candidates are surfaced in step 15.

### 13. Resolve open item (conflict unit)

Read the workstream file. Find checkbox lines (`- [ ] ...`).

Either:

- **Slug from checkbox text** — if the user's answer or a follow-up identifies one of the existing checkboxes, derive a slug from the first ~50 chars of that line (same sanitisation as workstream slugs). Capture the verbatim checkbox text as `open_item_summary`.
- **User-named fallback** — if no checkbox matches, ask the user to name the work in a few words; sanitise the same way; capture the user phrase as `open_item_summary`.

Ask explicitly: "Which open item are you tackling? (Or is this a new one not yet on the list?)" Do NOT add new items to the workstream file — `/bye` writes that on session close.

**If the user defers answering** (redirects to loading context, asks a clarifying question, or gives a non-answer), hold steps 13 and 14 open. When the first concrete work signal arrives — any request to produce, modify, investigate, or write something — re-ask the open-item question and complete step 14 before starting that work. Never begin substantive work without a written marker.

### 14. Write the session marker

**Skip this step if step 12 resolved to *Resume*** — the existing marker is the session's marker; no fresh write needed.

Path:

- Project context → `<workspace>/projects/<slug>/sessions/active/<id>.md`.
- Workspace-level → `<workspace>/sessions/active/<id>.md`.

Filename format: `<YYYY-MM-DD>-<workstream-slug>-<HHMMSS>-<6hex>.md` — workstream slug embedded so the file can be promoted to `sessions/` by `/bye` with a directory move only (no rename). The date + HHMMSS + 6hex together are collision-safe at second resolution.

Marker content:

```yaml
---
project_slug: <slug or "workspace">
workstream_slug: <slug>
open_item_slug: <slug>
open_item_summary: <verbatim checkbox text or user-named phrase>
started_at: <ISO-8601 with TZ offset>
session_id: <id>
---

Active session marker. Promoted to sessions/ by /bye on session close.
```

Atomic write. No mtime-check — the id is unique by construction, no race.

**Optional field — `resumed_at`**: step 12's Resume branch later adds this to an adopted marker. Absence means the marker was never resumed. `/bye` step 3 surfaces it in the session narrative when present.

### 15. Final recap

```
Active context
──────────────
Project:    <slug or "workspace">
Workstream: <slug>
Open item:  <summary>

Open items in this scope:
  <workstream-1>:
    - <item>
    - <item>
  <workstream-2>:
    - <item>

Project skills: <names discovered from the project's .claude/skills/, or omit the line>
Marker: <relative path>
```

Open items are listed grouped by workstream — never flat, never all attributed to the active workstream. Cross-reference each `workstreams/*.md` file in the active scope to build the list.

The "Project skills" line surfaces what step 9's discovery side effect made invocable — list the skill names from the active project's `.claude/skills/` so the user knows they can type them. Omit the line entirely when the project ships none.

If step 12 left an unrescued prior marker on this workstream (the user picked "Fresh" or didn't resume one of multiple candidates), surface it after the open-items list with its full path so the user can decide what to do with it. Do not act on it automatically.

