---
name: todo
description: Persistent task list that survives across sessions, with staleness detection, priority decay, and blocked detection. Markdown-only — no MCP dependency. Canonical file at `<workspace>/.claude/memory/todo/TODO.md`. Use when the user says "add todo", "mark done", "show todos", "stale tasks", "blocked items", "store this as a todo", "overdue" — OR any persistent tracking need (the built-in TaskCreate is session-scoped, this is for things that outlive the session).
user_invocable: true
args: `<action> [args]` where action is `add | done | update | show | search | remove | stale | blocked | overdue`. No action = show.
allowed-tools: Read, Edit, Write, Grep, Glob, Bash
---

## Model Selection

- **Default model:** a small/cheap model — append/edit of a structured markdown file with deterministic rules
- **Promote to a stronger model when:** `overdue` produces recommendations, or completion verification has to reason about whether a deliverable exists
- **Script-first parts:** reading/writing the file, computing ages, filtering by status — all deterministic

## Scope vs built-in TaskCreate

TaskCreate (the built-in) is **session-scoped** — tasks disappear when the conversation ends. This skill is **persistent** — entries live in `<workspace>/.claude/memory/todo/TODO.md` and survive every session, restart, and machine reboot. Use TaskCreate for in-session todo lists; use this skill for anything worth remembering tomorrow.

Canonical file: `<workspace>/.claude/memory/todo/TODO.md` (create on first use).

## Actions

### `add [priority] <subject>`
Defaults: priority = Medium, status = Open, date = today, last-touched = today.

1. Read `<workspace>/.claude/memory/todo/TODO.md` (create with template below if missing).
2. Next number = max existing number + 1 (never reuse).
3. Append row to Active Items.
4. Append detail section.
5. Report: `Added TODO-N: <subject> (priority)`.

### `done <N or keyword>`
1. Find matching item by number or keyword substring.
2. Before marking done, **verify the deliverable exists** if the detail references a file/path — use Glob/Read. If verification fails, warn and ask to confirm.
3. Move the row from Active to Completed, stamp with today's date.
4. Update the detail section status to Done.
5. Report: `Completed TODO-N: <subject>`.

### `update <N> <field> <value>`
Valid fields: priority (Critical|High|Medium|Low), status (Open|In Progress|Blocked|Done), subject, summary.
Updates the row and detail section. Update Last Touched to today.

### `show` (default when no args)
Display the Active Items table. If empty, "No pending TODOs." Include count-by-priority line at bottom.

### `search <keyword>`
Grep `<workspace>/.claude/memory/todo/TODO.md` plus any per-item detail files in `<workspace>/.claude/memory/todo/`. Return matches with status and priority.

### `remove <N or keyword>`
Delete the row AND the detail section. If a linked detail file exists in `<workspace>/.claude/memory/todo/todo-N-*.md`, leave the file but note it to the user.

### `stale`
List items where Status = Open AND Last Touched > 7 days ago.

### `blocked`
List items where Status = In Progress AND Last Touched > 3 days ago — likely quietly blocked.

### `overdue`
Combined report: stale + blocked + priority-decay candidates. Write the report to `<workspace>/inbox/todo-overdue-<YYYY-MM-DD>.md` (or your preferred inbox location) so the user can review it later, e.g. on mobile via a "portable single-file" export if you have one.

---

## Staleness rules

| Condition | Flag |
|---|---|
| Open + 7+ days untouched | STALE |
| In Progress + 3+ days untouched | BLOCKED |
| Medium priority + 14+ days untouched | Propose auto-escalate to High (ask first) |
| Low priority + 21+ days untouched | Propose archival (ask first) |

## Auto-touch

When a session conversation mentions a TODO subject (keyword match against active items), bump that item's Last Touched to today's date. Prevents false staleness flags for things being actively worked.

## File format

Create the file with this template on first use. Preserve structure exactly on subsequent edits.

```markdown
# TODO

## Active Items
| # | Priority | Subject | Source | Added | Touched | Status |
|---|----------|---------|--------|-------|---------|--------|

## Item Details

## Completed Items
| # | Priority | Subject | Added | Completed |
|---|----------|---------|-------|-----------|
```

Age is computed at display time, not stored. Format: `Nd` | `Nw` | `Nmo`.

## Rules

- **Read before write.** Never assume current state.
- **Preserve all existing items** when adding.
- **Next number** = max existing + 1. Never reuse.
- **Large items** (longer than ~5 lines of detail) get their own file `<workspace>/.claude/memory/todo/todo-N-<slug>.md`, linked from the detail section.
- **Date format:** YYYY-MM-DD.
- **Default priority:** Medium. **Default status:** Open.

## Implicit add

If the user says "store this as a todo" / "track this" / "remind me to X" without an explicit action verb, treat as `add` and extract subject from context. Ask for priority only if it matters (default Medium).

## Don't

- This skill is intentionally markdown-only; don't dual-write to any external store.
- Don't split one deliverable into 5 rows to pad the list.
- Don't mark something Done without the verification step passing, unless the user confirms.
- Don't use this for session-scoped todos — use TaskCreate for those.
