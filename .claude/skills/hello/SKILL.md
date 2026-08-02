---
name: hello
description: Start a session — locate workspace, classify cwd, resolve project + workstream + open item, load memory, write session marker, recap context
user_invocable: true
---

# Session Start

You are starting a new working session. Resolve the active context, load memory, and orient the user.

## Steps

> **Execution strategy — front-load the recap (steps 1–6).** Steps 1–6 take no user input; running them as six serial tool round-trips is the main avoidable latency in session start. Gather everything they need in ONE batched pass, then emit the step-6 recap in a single turn. The independent filesystem work — the workspace file reads (step 3), the registry read, the active-marker enumeration (step 4), the `.last-session` pointer read (step 6), and the `grep -c` lessons count — can all go out together (parallel tool calls, or a single shell probe). When the topic arrived with the `/hello` invocation, the step-10 topic→workstream grep can join this same batch too — it is non-interactive fs work. `/mcp-doctor` (step 5) reads only from tools already in context, and `MEMORY.md` is already loaded via the `@`-import — neither needs I/O. The step numbers are a logical order, **not** a mandate to pay one round-trip per step. Only the *questions* from step 7 onward are genuinely interactive. (Sole exception: step 9's `project-context` read must use the Read tool for its skill-discovery side effect — but that runs after step 7's answer, never in this front-loaded batch, so at workspace root a shell probe for steps 1–6 is fine.)

### 1. Self-locate the workspace

The skill's base directory is `<workspace>/.claude/skills/hello/`. Resolve `<workspace>` by walking up three directory levels. Validate that `<workspace>/.claude/.workspace` exists. If validation fails, abort with a setup-broken error — this is not recoverable from inside /hello.

### 2. Classify cwd

Compute one of five cases. The result is a *hint* for phrasing in step 7; it does not by itself decide the active project.

A session whose cwd is outside `<workspace>/` is allowed in **exactly ONE** case: cwd is a **registered project's own directory** (the real path a `<workspace>/projects/<slug>` symlink points to), launched with `--add-dir <workspace>` (the *Registered project (external path)* case below). The workspace is located in step 1 from this skill's own base directory, which is what makes that one case workable. **Every other outside-workspace cwd is refused** (the *Outside workspace (refuse)* case). This is a closed exception — do NOT extend it to any other outside-workspace scenario, and do NOT improvise a project binding for a directory that is not a registered project's own directory.

- **Registered project (in-workspace)** — cwd is under `<workspace>/projects/<slug>/` and `<slug>` is in the registry. Hint = that project.
- **Registered project (external path)** — cwd is *not* under `<workspace>/`, **and** `realpath(cwd)` is (or is under) `realpath(<workspace>/projects/<slug>)` for some registered `<slug>` — i.e. launched directly from the project's own directory (the symlink's real target), with the workspace supplied via `--add-dir`. This is the only sanctioned outside-workspace case. Hint = that project. **In this case the project folder's own `.mcp.json` and `.claude/settings.json` are in effect, not the workspace's** — workspace-scoped MCP servers do not load (user-scope ones still do). Surface this plainly in the recap (step 6) so the engineer is not surprised by a different MCP/settings surface.
- **Workspace-level** — cwd equals `<workspace>/`, or is under `<workspace>/` but not under `<workspace>/projects/<slug>/`. Hint = workspace-level work.
- **Unregistered project** — cwd is under `<workspace>/projects/<slug>/` but `<slug>` is NOT in the registry. Hint = offer inline registration via `/setup-workspace add-project`.
- **Outside workspace (refuse)** — cwd is not under `<workspace>/` **and** does not resolve to any registered project's directory. **Refuse and stop here.** Give a clear, specific message: the session was started outside the workspace and outside every registered project, so Memnyx cannot bind it to a project. Tell the user exactly what to do — `cd` into `<workspace>` (or into a registered project's own directory) and rerun `/hello` — and, if they intended the current folder, that it is not a registered project (point them at `/setup-workspace add-project`, or at launching from the workspace).

### 3. Load workspace-scope context

Read in parallel; skip silently if a file is missing:

- `<workspace>/me/identity.md`
- `<workspace>/.claude/memory/project-context.md`

Read the project registry directly from `<workspace>/.claude/projects-index.json` (registry mutations go via `/project-registry`; reads bypass it). Treat missing as empty.

**Do NOT read `<workspace>/.claude/memory/MEMORY.md` here.** It is already in context — `CLAUDE.md` `@`-imports it at session boot, so re-reading only duplicates it. The distilled `MEMORY.md` *is* the session-orientation layer; you already have it.

**Do NOT read `<workspace>/.claude/memory/lessons-learned.md`.** It is the raw append-inbox that `/lessons` and `/bye` consume — not session-start context. It grows without bound as lessons accumulate, so full-reading it at every session start is a cost that scales with history, for a file `/hello` doesn't use. The recap needs only a count: get it with `grep -c` (see step 6's Lessons line). Same rule at project scope (step 9). The principle is general: to report a metric about a large file, count it, never ingest it.

Session narrative for the active workstream loads after workstream resolution at step 10 — not here.

### 4. Scan active session markers

List markers from:

- `<workspace>/sessions/active/*.md` (workspace-level sessions)
- `<workspace>/projects/*/sessions/active/*.md` (project-level sessions)

For each, extract the frontmatter fields (`project_slug`, `workstream_slug`, `open_item_slug`, `started_at`) and compute age. **Extract them with Bash (`grep`/`sed`), NOT the Read tool.** These markers span every scope, and a Read-tool touch of one under `projects/<slug>/sessions/active/` triggers that project's on-demand `CLAUDE.md` + `@`-import load — a *normal-subdirectory* read, which fires the nested-CLAUDE.md load (unlike a `.claude/` read, which does not). Reading all of them with the Read tool would side-load the full `CLAUDE.md` + `MEMORY.md` of **every project that has an active marker** — heavy, unrelated context this step doesn't need. This scan is metadata-only; keep it that way with Bash. **Held purely for the recap at step 6** — informational only. No control-flow consumer in this skill; disambiguation work happens in step 11 against a workstream-local scan, not against this list.

### 5. Run /mcp-doctor

Inline call in session mode. Surfaces server health to fold into the recap.

### 6. Recap (workspace-scope)

```
Session Start
=============
Workspace:  <path>
Cwd hint:   <workspace-level | project=<slug> | project=<slug> (external path) | unregistered=<slug> | outside>
Last session: <one-line summary, or "No previous sessions">
Active sessions elsewhere: <list with ages, or "none">
MCP status: <from /mcp-doctor>
Lessons:    <N> saved to memory · <M> raw notes not yet curated
Identity:   loaded / placeholder
```

**"Last session" sourcing.** Read the scope-neutral global pointer `<workspace>/.claude/.last-session` (alongside `projects-index.json`) — the most-recent session may belong to any project or to workspace level, and `/bye` writes this one pointer on every close with the just-closed session's `path`, `project_slug`, `workstream_slug`, and `closed_at`. The one-line summary comes straight from that single small read; no enumeration, no sort — O(1) regardless of how many closed sessions have accumulated or which scope owns the latest.

Read the pointer with Bash (`cat`/`grep`) — it's a small data file at workspace scope, so the Read tool buys nothing here.

**Fallback** (pointer absent, or its `path` no longer exists — resolve it as `<workspace>/<path>`, joining to the workspace located in step 1, **not** cwd: the stored `path` is workspace-relative, and under `--add-dir` / the `mmn` launcher cwd is routinely a registered project's own directory (the external-path case), not the workspace root, so a bare relative-path check would spuriously fail; also covers a workspace predating the pointer, or `/bye` never having run): scan both `<workspace>/sessions/*.md` and `<workspace>/projects/*/sessions/*.md`, sort by the date and time embedded in each filename — not raw lexicographic order, since the workstream slug between them makes that unreliable — take the most recent, and extract its frontmatter (`project_slug`, `workstream_slug`) with **Bash (`grep`/`sed`), not the Read tool** — same reason as step 4: the most-recent session can be a project file, and a Read-tool touch would side-load that project's `CLAUDE.md` + memory. Output "No previous sessions" only when the pointer is absent **and** both globs return no files.

**"Lessons" line sourcing.** A *count*, never a full read — and never an invented breakdown. `MEMORY.md` is already in context (via the `@`-import); count its actual distilled bullet entries for `<N>` — a count of content already loaded, no I/O. (That's the asymmetry with `<M>` below: `<N>` is a context-count because `MEMORY.md` is loaded, whereas `<M>` needs a `grep -c` because `lessons-learned.md` is deliberately *not* loaded.) **Do NOT fabricate a "conventions vs patterns" split** — the file's section headings vary by scope (e.g. Feedback / Tool Usage / Conventions) and rarely match that label, so quoting made-up sub-counts is a fabrication. If a breakdown adds value, use the file's real section names; otherwise report the honest total. Get raw-inbox depth `<M>` from `grep -cE '^[-*] ' <workspace>/.claude/memory/lessons-learned.md` (matches both `-` and `*` list markers) — a count, not a read. Never load `lessons-learned.md` into context to produce this number. Keep the user-facing label plain ("saved to memory" / "raw notes not yet curated") — the recap orients users who don't know the distilled-vs-inbox memory model, so don't surface that jargon in the output.

### 7. Resolve project (open-ended)

Phrasing branches on the cwd hint. In every variant, be honest about inference and invite explicit override — never imply the model deterministically knows whether work "is a project":

- **Workspace-level hint** → "What are you working on today? I'll infer whether to treat it as project work or workspace-level work and confirm before proceeding. You can also explicitly say 'register a new project' or 'this is a one-off task' to skip the inference."
- **Registered-project hint** → "Looks like you're in `<slug>`. Continuing on that, or working on something else today? (If something else, I'll infer the scope and confirm — or you can ask me to register a new project.)"
- **Registered-project (external path) hint** → "You're in `<slug>`'s own directory (the workspace references it via symlink, and you launched with `--add-dir`). Continuing on `<slug>`, or something else? Heads-up: this session is using `<slug>`'s own MCP servers and settings, not the workspace's." Then resolve exactly as for the registered-project hint.
- **Unregistered-project hint** → "`<slug>` isn't registered yet. Want me to register and scaffold it now (calls `/setup-workspace add-project`), or are you treating this as a one-off?"

Resolution rules — match the registry first:

1. **Semantic match against registered slugs and descriptions.** If a plausible match exists, confirm with the user ("That sounds like `<slug>` — continue there?"). The registry is the source of truth for whether work belongs to a project; topic shape (personal, cross-cutting, leadership update, team activity, 1:1 prep, etc.) is not a signal to skip the registry — users may register a project (e.g., `my-work`) precisely for that work.
2. **Ambiguity** between two or more registered projects → ask one clarifying question.
3. **Explicit user override.** If the user explicitly says "register a new project" / "create a project" / "one-off task" / similar, honour that immediately without further inference. Explicit override always beats inference.
4. **No match, user describes a new project** → fall through to step 8 (new-project handling).
5. **No match, user confirms it's not project-bound** → set scope = workspace-level. Workspace-level is the fallback when no project fits — never the default for a topic shape.

**Topic names the work, not the project.** Users often describe *what* they're doing, not which project owns it — and the work may live in a project other than the cwd hint. When the registry doesn't cleanly resolve scope from the topic, run the cross-project topic→workstream scan (the mechanism defined in step 10) *now* and let it surface candidate `<project> / <workstream>` pairs. A strong workstream match is itself evidence for its project — and since workstreams live only under registered projects, confirming one still honours "the registry is the source of truth for scope"; you're just reaching the registered project via the work the user named. Picking a candidate resolves scope **and** pre-identifies the workstream (step 10 then only loads it). If candidates span several projects, ask one focused disambiguation naming them — never silently guess one, never fall through to a generic question. This runs as soon as the topic is known (the ARGUMENTS, or the answer here), so it folds into the step 1–6 front-load batch when the topic arrived with the invocation.

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

- **Read `<workspace>/projects/<slug>/CLAUDE.md` with the Read tool, then load its `@`-imports.** Use the Read tool (not Bash) — the injection side-channel that the check below keys on only fires on a Read-tool open; a Bash read never triggers it, so the check would always say "not injected" and you'd re-read every import (correct, but you lose the point of the check). Reading a project file *sometimes* makes the harness inject that project's `CLAUDE.md` `@`-imports (e.g. its `MEMORY.md`) into context as a separate system-reminder — and sometimes not; the behaviour is inconsistent and must not be relied on. So after reading the CLAUDE.md, for each file it `@`-imports (resolve each `@path` relative to the CLAUDE.md; skip any inside backticks or a fenced code block; follow only the **direct** imports the project CLAUDE.md declares — don't recurse into imports-of-imports, which today's project memory doesn't use): **did its content just arrive as a system-reminder injection right after your CLAUDE.md read? If not — or if you're unsure — read it yourself.** Prioritise never missing an import over avoiding a duplicate: a duplicate is cheap, but skipping a file that wasn't actually injected loses project memory (the failure this guards against). Checking for that *visible injection event* is reliable in a way that introspecting your whole context window is not. This tracks whatever the CLAUDE.md declares, so it stays correct as the project's imports change. (The Read tool's own *result* never resolves `@`-imports — the CLAUDE.md comes back with the literal `@…` line; imported content, when present, arrived via that separate injection, not the tool result.)
- **Read `<workspace>/projects/<slug>/.claude/memory/project-context.md`** with the **Read tool** (domain context; skip silently if missing). Beyond its content, this Read is the reliable trigger for the project's skill discovery (below). It isn't a CLAUDE.md import — a separate read.
- **Do NOT read `lessons-learned.md`** — raw inbox; `grep -c` for the recap count, never full-read (same rule as step 3).

List `<workspace>/projects/<slug>/workstreams/*.md` (read on demand at step 10).

**Skill discovery is a separate mechanism — that's why `project-context.md` is read with the Read tool.** A Read/Edit-tool access to a file under `<workspace>/projects/<slug>/.claude/` registers that project's `.claude/skills/` (invocable, autocomplete included); Bash (`cat`/`sed`/`grep`) does not. The `project-context.md` read above is that trigger. It is independent of `@`-import loading — which is why the imports are handled by the check-then-fill above rather than assumed to arrive. Discovery covers the skills format only; legacy `.claude/commands/` files never register on-demand (they load when the session starts in that project, or via an explicit `--add-dir`/`/add-dir`).

For workspace-level scope, the memory at `<workspace>/.claude/memory/` is already loaded in step 3 — the workspace `CLAUDE.md` is the cwd's own file, so the harness loads it and expands its `@`-imports at launch (this is why the workspace `MEMORY.md` genuinely does arrive for free, unlike the project one). Just list `<workspace>/workstreams/*.md`.

Session narrative for the active workstream loads after workstream resolution at step 10.

### 10. Resolve workstream

Seed the hint by matching the user's stated topic against workstreams (a cheap, cross-project scan), and fall back to recency when there is no topic or no match:

1. **Topic → workstream scan (cross-project, cheap).** Take the user's stated topic — the `/hello` ARGUMENTS if the invocation carried any, plus their step-7 answer — and `grep` it across **all** workstream files: `<workspace>/workstreams/*.md` and `<workspace>/projects/*/workstreams/*.md` (exclude archived workstreams once that mechanism exists). Not just the resolved scope — the user names the *work*, which may live in a project other than the cwd hint.

   - **Scope the scan by corpus, not by filename-vs-content.** The whole workstream corpus is small (tens of files). `grep` reads them from disk in milliseconds and returns only the matching lines/filenames — the bodies do **not** enter context — so match against filenames *and* bodies freely. What stays strictly off-limits is content-scanning the large, numerous corpora — `sessions/`, `artifacts/`, and memory files — to find the work; never `grep` those here. The cheap/expensive line is *which corpus you scan*, not whether you read past the filename.
   - **One query-expanded grep for candidate filenames.** Search the topic's key terms and a few obvious variants in a single pass (topic "security vulnerabilities" → `secur|vuln|cve|remediat`), returning **filenames** (`grep -ilE`), not matched lines. A handful of terms, for recall — expect some false positives (a broad term like `secur` matches an unrelated changelog line); you discard those at the peek. Filenames are bounded output (one line per hit); matched lines (`-in`) balloon across many hits and overflow/truncate, defeating the purpose. One call; when the topic arrived with the invocation this folds into the step 1–6 front-load batch. **Guard the globs against no-match** — suppress errors (`… 2>/dev/null`): the `<workspace>/projects/*/workstreams/*.md` glob expands to nothing on a fresh workspace or a project with no workstreams, and an unguarded unmatched glob makes `grep` error and can abort the scan. Treat zero hits as an empty candidate set and fall through to the recency fallback.
   - **Narrow by filename, peek to describe, ingest only on selection.** From the candidate filenames, narrow to the few plausible ones by name, discarding obvious false positives. To write a useful disambiguation, **peek at the top of each narrowed candidate with `head` (Bash)** — header / status / first open items, a bounded few-line read. Use **Bash, not the Read tool**, for the peek: a Read-tool touch of a candidate *workstream* file (a normal project subdirectory, not `.claude/`) can trigger that project's nested-`CLAUDE.md` **load** — the harness side-loads that project's `CLAUDE.md` + its `@`-imported memory (observed: cross-scope `sessions/` reads did exactly this in a live run). You don't want a not-yet-picked candidate's whole project layered in. (This is the nested-CLAUDE.md load, distinct from skill discovery — discovery is `.claude/`-only and wouldn't fire on a `workstreams/` read anyway; the load is what a normal-subdir read triggers.) Reserve project-context layering for the *chosen* project at step 9. Read a workstream's **full** body only once the user picks it (or on a single unambiguous match). Do not scan `artifacts/` — even by filename — to corroborate: the workstream corpus is the only sanctioned discovery source; `sessions/`, `artifacts/`, and memory stay off-limits for finding the work.
   - **Cross-project candidates drive scope too.** If matches span more than one project/scope, surface them all as `<project> / <workstream>` and ask one focused disambiguation. Picking a candidate in another project sets scope to that (registered) project — if step 7 has not already layered it, run step 9 for the chosen project before loading the workstream. When step 7 already ran this scan to resolve scope, reuse its result here; do not re-grep.

2. **Recency fallback** (no topic, or the scan found nothing). List `<scope>/sessions/*.md`, parse `<YYYY-MM-DD>` and `<HHMMSS>` from each filename, sort by parsed datetime descending, take the most recent. Extract the workstream slug from the filename (`<YYYY-MM-DD>-<workstream-slug>-<HHMMSS>-<6hex>.md` — the slug is the middle segment between the date and the timestamp). If no session files exist, skip the hint.

**Graceful degrade — a scan miss is never a dead end.** Fall to the recency hint; if that is empty too, just ask ("Which workstream are you on, or is this a new one?"). Do not escalate to content-grepping `sessions/` or `artifacts/` to force a match — that is the corpus the cost boundary protects.

Phrasing branches on what seeded the hint:

- **Topic match, one** → "Looks like your `<slug>` workstream — continue there, or something else?"
- **Topic match, several (possibly cross-project)** → "Your description matches a few workstreams — which one? `<project>/<slug>`, `<project>/<slug>`, …"
- **Recency match** → "Last time you were on `<workstream-slug>`. Continue, or working on something else?"
- **No hint** → "Which workstream are you on, or is this a new one?"

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

### 11. Check for an existing active marker on this workstream

Now that scope and workstream are known, scan `<scope>/sessions/active/*-<workstream-slug>-*.md` — workstream-local only. No cross-scope scan; step 6's recap already surfaced cross-scope sessions for the user's awareness, and acting on those is the user's decision, not this skill's.

Branches by count:

- **0 matches** → proceed to step 12.
- **1 match** → parse the marker's frontmatter. Show:

   ```
   Active marker on this workstream:
     Open item: <open_item_summary>
     Started:   <age> ago
     File:      <relative path>

   Resume that work, or start fresh?
   ```

   - **Resume** → adopt the marker as this session's marker. Load `open_item_slug` and `open_item_summary` from the frontmatter. **Cross-reference against the workstream file's open checkboxes — if the marker's `open_item_slug` maps to an item already marked `[x]`, the marker is stale; prompt the user to pick the live work from the workstream's `- [ ]` list before adopting.** Write `resumed_at: <ISO-8601 with TZ offset>` into the marker's frontmatter — add the field if missing, replace if present (only the most recent resume is tracked, no history list). Use mtime-check on this write since a concurrent `/hello` on the same marker could in principle race. **Skip step 12 (open-item resolution) and step 13 (marker write).** Record the resume decision for the final recap.
   - **Fresh** → proceed to step 12. The prior marker stays in `active/` untouched — we do not auto-promote, auto-delete, or auto-modify. Flag it in step 14's recap so the user can decide what to do with it.

- **>1 matches** → list each candidate with age + open item summary. Ask the user to pick one to resume, or to start fresh. Apply the same downstream branches as the 1-match case. Any unrescued candidates are surfaced in step 14.

### 12. Resolve open item (conflict unit)

Read the workstream file. Find checkbox lines (`- [ ] ...`).

Either:

- **Slug from checkbox text** — if the user's answer or a follow-up identifies one of the existing checkboxes, derive a slug from the first ~50 chars of that line (same sanitisation as workstream slugs). Capture the verbatim checkbox text as `open_item_summary`.
- **User-named fallback** — if no checkbox matches, ask the user to name the work in a few words; sanitise the same way; capture the user phrase as `open_item_summary`.

Ask explicitly: "Which open item are you tackling? (Or is this a new one not yet on the list?)" Do NOT add new items to the workstream file — `/bye` writes that on session close.

**If the user defers answering** (redirects to loading context, asks a clarifying question, or gives a non-answer), hold steps 12 and 13 open. When the first concrete work signal arrives — any request to produce, modify, investigate, or write something — re-ask the open-item question and complete step 13 before starting that work. Never begin substantive work without a written marker.

### 13. Write the session marker

**Skip this step if step 11 resolved to *Resume*** — the existing marker is the session's marker; no fresh write needed.

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

**Optional field — `resumed_at`**: step 11's Resume branch later adds this to an adopted marker. Absence means the marker was never resumed. `/bye` step 3 surfaces it in the session narrative when present.

### 14. Final recap

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

If step 11 left an unrescued prior marker on this workstream (the user picked "Fresh" or didn't resume one of multiple candidates), surface it after the open-items list with its full path so the user can decide what to do with it. Do not act on it automatically.
