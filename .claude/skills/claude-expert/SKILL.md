---
name: claude-expert
description: Definitive reference for how Claude Code works — disambiguates skills vs hooks vs subagents vs MCPs vs slash commands vs memory vs settings. Use when asked "how does Claude Code X work", "what's the difference between X and Y", "where should this live", "build me a [skill|hook|agent|mcp|slash command]", "configure Claude Code", or when picking the right surface for a new capability.
---

# claude-expert — the router, not the doer

This skill is the **reference** for Claude Code's extension surfaces. It tells
you which surface to pick and where to read for depth. It does not itself edit
settings, write skills, or modify keybindings — for those, it hands off to
whatever lifecycle manager your setup has for that artifact type (discovered at
invocation; see the registry below).

All content is distilled from the official docs at
[code.claude.com/docs](https://code.claude.com/docs/en/overview). When details
here conflict with the live docs, the live docs win.

## Read this as reasoning, not rules

Everything below — the tables, the manager registry, the runbooks — exists to
**sharpen** judgment, not replace it. Treat it as principles + tradeoffs, not a
lookup table to obey or a checklist to satisfy. A handful of things are genuine
**invariants** (hold them firm); the rest are **heuristics** (strong defaults you
may override with stated cause). When a case doesn't fit a row, reason from the
tradeoff the row is built on — that's why every fork states its *why*. Full
framing + the invariant list: [reasoning.md](reasoning.md). If a "rule" here makes
no sense for the case in front of you, that's the system failing its job — think,
don't comply.

## On invocation — tune to this setup, then check freshness (run FIRST)

claude-expert adapts to **whoever installed it** rather than assuming a fixed
layout, and keeps itself current **lazily, on use**. The instant this skill is
invoked, before answering:

1. **Discover the environment.** Run
   `bash "$(dirname "$0")/discover-setup.sh"` — or, from the skill dir,
   `bash discover-setup.sh`. It introspects `$HOME/.claude` and the project
   `./.claude` (read-only, fail-soft) and emits a greppable `KEY=VALUE` map:
   installed skills + agents, configured hooks, which **artifact-type manager**
   exists vs is a gap, the staging dir for self-update reports, and the path to a
   local Python reimplementation of Claude Code if one is present. Use that map to
   route to *this user's* managers — never assume a manager name without checking
   it `PRESENT`.

2. **Check freshness (lazy gate).** Run `bash freshness-check.sh`.
   - Prints **FRESH** → proceed straight to the user's request.
   - Prints **STALE** → launch a **background** refresh subagent, then
     **immediately continue with the user's actual task in parallel — do not wait**:

     ```
     Agent(subagent_type: "general-purpose", run_in_background: true,
       description: "claude-expert freshness refresh",
       prompt: "Execute the freshness runbook in self-update.md. Research the
         official changelog + code.claude.com/docs/en/* DIRECTLY via WebSearch/WebFetch
         (never a research skill — it nests) since the date in latest.md. VERIFY each
         version against the canonical changelog. AUTO-APPLY only verified ADDITIVE
         facts to latest.md. PROPOSE any decision-impacting change into STAGING_DIR
         (from discover-setup.sh) — never edit decision logic. On completion:
         run freshness-check.sh stamp (it writes .last-research + clears the lock
         in this skill's own dir, wherever installed). Fail closed.")
     ```

This is **fire-and-forget**: the refresh writes its own results to `latest.md`
and the staging dir. Do not block on it; surface its result only if it flags a
`DECISION-IMPACTING` proposal. The gate self-locks (a STALE result claims a 2-hour
lock) so concurrent invocations never double-spawn, and `.last-research` bumps to
today on completion so it won't re-trigger for 7 days. Full design:
[self-update.md](self-update.md). Both scripts use `$HOME`, never a hardcoded path,
and are read-only except for creating the staging dir.

## Decision tree — which surface?

**Fastest answer for "skill vs subagent vs hook vs md-file":** see the
[four-way table at the top of decision-tree.md](decision-tree.md#the-four-way-skill-vs-subagent-vs-hook-vs-md-file).
The full per-goal lookup is below it. The short form of the primary table:

| I want to... | Surface | Deep dive |
|:--|:--|:--|
| Automate behavior on every tool call, prompt, or session event | **Hook** | [surfaces/hooks.md](surfaces/hooks.md) |
| Give Claude a reusable playbook it loads when relevant | **Skill** | [surfaces/skills.md](surfaces/skills.md) |
| Let the user type `/foo` to run a workflow | **Skill** (custom commands merged into skills) | [surfaces/slash-commands.md](surfaces/slash-commands.md) |
| Run specialist work in an isolated context window | **Subagent** | [surfaces/subagents.md](surfaces/subagents.md) |
| Connect to an external service, DB, or API | **MCP server** | [surfaces/mcp.md](surfaces/mcp.md) |
| Persist a fact/preference across sessions | **Memory** (`CLAUDE.md` or auto-memory) | [surfaces/memory.md](surfaces/memory.md) |
| Configure permissions, env vars, hooks at a project or user level | **Settings.json** | [surfaces/settings.md](surfaces/settings.md) |
| Ship a bundle (skills + agents + hooks + MCP) to a team | **Plugin** | [surfaces/plugins.md](surfaces/plugins.md) |
| Block or auto-approve a tool call | **Permission rule** or **PreToolUse hook** | [surfaces/permissions.md](surfaces/permissions.md) |
| Build a standalone agent outside the CLI (Python/TS) | **Agent SDK** | [surfaces/agent-sdk.md](surfaces/agent-sdk.md) |
| Run recurring or scheduled work | **`/loop`** (session), **`/schedule`** Routines (cloud), local scheduled tasks | [decision-forks.md](decision-forks.md) · [surfaces/background-tasks.md](surfaces/background-tasks.md) |
| React to an external event instead of polling | **Channels** (`--channels`) | [latest.md](latest.md) |
| Keep working until a condition is met (not on an interval) | **`/goal`** | [latest.md](latest.md) |
| Rebind a keyboard shortcut | **Keybindings** (`~/.claude/keybindings.json`) | [surfaces/keybindings.md](surfaces/keybindings.md) |
| Understand what loads into context and when | **Context management** | [surfaces/context-management.md](surfaces/context-management.md) |
| Use Claude Code in VS Code / JetBrains / Desktop / web | **IDE integration** | [surfaces/ide-integrations.md](surfaces/ide-integrations.md) |

## Short summaries of each surface

*(Two surfaces were added in 2026 — **Channels** (event push into a session) and **LSP servers in plugins** — plus **`/goal`** for until-done loops and **`auto`** permission mode replacing `--dangerously-skip-permissions`. See [latest.md](latest.md).)*

### Skills
A `SKILL.md` file (markdown + YAML frontmatter) at
`~/.claude/skills/<name>/SKILL.md` or `.claude/skills/<name>/SKILL.md`. Claude
loads the description eagerly into context and the body on-demand when invoked
(by `/skill-name` or automatically when the description matches). Custom
commands have been merged into skills: `.claude/commands/deploy.md` and
`.claude/skills/deploy/SKILL.md` both produce `/deploy` — skills add a
directory for supporting files and more frontmatter. Keep SKILL.md under 500
lines; offload references. See [surfaces/skills.md](surfaces/skills.md).

### Hooks
User-defined shell commands, HTTP endpoints, prompts, or LLM agents that run
automatically at lifecycle events (`PreToolUse`, `PostToolUse`,
`SessionStart`, `UserPromptSubmit`, `Stop`, `SubagentStop`, `FileChanged`,
etc.). Configured in `settings.json`, plugin `hooks/hooks.json`, or
skill/agent frontmatter. Hooks can block tool calls (exit 2 or `deny`),
inject context, or enforce policy — this is the **only** way to deterministically
force the harness to do something. Memory/preferences CANNOT fulfill
"from now on, every time X". See [surfaces/hooks.md](surfaces/hooks.md).

### Subagents
Markdown files with YAML frontmatter at `.claude/agents/<name>.md` or
`~/.claude/agents/<name>.md`. Each runs in its own context window with its
own tool restrictions, model, permission mode, optional MCP servers, and
optional memory. Claude delegates automatically (by `description` match) or
on request (`@agent-name` or `--agent <name>`). Use when you need context
isolation; skip when the task needs quick back-and-forth. Built-ins:
`Explore`, `Plan`, `general-purpose`. See
[surfaces/subagents.md](surfaces/subagents.md).

### MCP (Model Context Protocol)
External tools/data/APIs connected over stdio, HTTP, or SSE. Add via
`claude mcp add --transport <http|sse|stdio> <name> ...`. Tools are exposed
as `mcp__<server>__<tool>`. Scopes: local (default), project (shared via
`.mcp.json`), user. Build an MCP server when an integration is reusable
across agents/sessions; build a subagent or skill when it's Claude-specific
behavior. See [surfaces/mcp.md](surfaces/mcp.md).

### Slash commands
Built-in commands (like `/help`, `/compact`, `/config`, `/doctor`) plus
bundled skills (like `/simplify`, `/batch`, `/debug`, `/loop`, `/claude-api`).
Custom slash commands = skills. Plugin-provided commands are namespaced
`/plugin-name:command-name`. See
[surfaces/slash-commands.md](surfaces/slash-commands.md).

### Settings
JSON files at four scopes: managed (enterprise policy, not overridable),
project-local (`.claude/settings.local.json`, gitignored), project
(`.claude/settings.json`, in VCS), user (`~/.claude/settings.json`). Hold
permissions rules, env vars, hooks, model, statusLine, autoMode classifier,
plugins, attribution, sandbox, etc. Arrays merge across scopes. See
[surfaces/settings.md](surfaces/settings.md).

### Plugins
Distributable bundles with a `.claude-plugin/plugin.json` manifest plus any
of `skills/`, `agents/`, `hooks/`, `.mcp.json`, `.lsp.json`, `monitors/`,
`bin/`, `settings.json`. Installed via marketplaces (`/plugin`) or loaded
ad-hoc with `--plugin-dir`. Root-skill invocation depends on load form: a
skills-directory plugin (`.claude/skills/<name>/`, autoloaded) resolves its root
**bare** `/<name>`; a marketplace- or `--plugin-dir`-loaded plugin resolves it
**namespaced** `/<plugin>:<name>`. Sub-skills and agents are always namespaced.
See [surfaces/plugins.md](surfaces/plugins.md).

### Memory
`CLAUDE.md` files (written by you) + auto-memory (written by Claude). Project
root CLAUDE.md loads in full at session start; subdirectory ones load on
demand; `.claude/rules/*.md` can be scoped by `paths:` globs. Auto-memory
lives at `~/.claude/projects/<project>/memory/MEMORY.md` by default and
injects its first 200 lines / 25 KB. Use `@path` imports. Memory is context,
NOT enforcement. See [surfaces/memory.md](surfaces/memory.md).

### Agent SDK
TypeScript (`@anthropic-ai/claude-agent-sdk`) or Python
(`claude-agent-sdk`). Same tools, agent loop, and context management as the
CLI, programmable. Use for CI/CD, production automation, custom apps. Not
for interactive development — use the CLI for that. See
[surfaces/agent-sdk.md](surfaces/agent-sdk.md).

### Permissions
Allow/ask/deny rules in `settings.json`. Precedence: deny > ask > allow,
first match wins. Tool rules like `Bash(git commit *)`, `Read(./.env)`,
`WebFetch(domain:example.com)`, `Agent(Explore)`, `mcp__server__*`,
`Skill(name)`. Permission modes: `default`, `acceptEdits`, `plan`, `auto`,
`dontAsk`, `bypassPermissions`. See
[surfaces/permissions.md](surfaces/permissions.md).

### Background / scheduled tasks
`/loop [interval] [prompt]` — session-scoped recurring prompt (7-day
expiry). `CronCreate`/`CronList`/`CronDelete` — session-scoped Claude-callable
tools using 5-field cron expressions. `/schedule` or Routines — cloud-run,
survive machine off. Local scheduled tasks — survive session close. See
[surfaces/background-tasks.md](surfaces/background-tasks.md).

### Context management
Skill descriptions = 1% of context window / 8,000 char fallback budget
(override with `SLASH_COMMAND_TOOL_CHAR_BUDGET`). Per-skill description +
`when_to_use` capped at 1,536 chars. Invoked skills re-attached after
compaction at 5,000 tokens each, combined 25,000-token budget. See
[surfaces/context-management.md](surfaces/context-management.md).

### IDE integrations
VS Code and JetBrains plugins. Share CLAUDE.md, settings, MCP servers,
conversation history with the CLI. Extension has an internal `ide` MCP
server exposing `mcp__ide__getDiagnostics` and `mcp__ide__executeCode`
(Jupyter, user-confirmed). See
[surfaces/ide-integrations.md](surfaces/ide-integrations.md).

### Keybindings
`~/.claude/keybindings.json`. Contexts (`Global`, `Chat`, `Autocomplete`,
`Confirmation`, `Scroll`, `MessageSelector`, and many others). Action
namespaces (`chat:submit`, `app:interrupt`, etc.). Chord syntax:
`ctrl+x ctrl+s`. Reserved: `Ctrl+C`, `Ctrl+D`, `Ctrl+M`. Hot-reloaded. See
[surfaces/keybindings.md](surfaces/keybindings.md).

## Decision forks — pick the right surface (quick rules)

The five load-bearing choices, one line each — these are tradeoffs to reason about,
not lookups. The one-liners are the common case; when yours doesn't fit, reason from
the *why* in [decision-forks.md](decision-forks.md). The symptom→right-surface catalog
is in [anti-patterns.md](anti-patterns.md). Of the five, only **(b) destructive guards
belong in a deny hook** is an invariant; the rest are strong defaults.

a. **Skill vs subagent** — reusable/interactive/inline → **skill**; verbose/isolated/parallel/tool-restricted → **subagent**. A skill's body stays resident all session (re-paid every turn); a subagent returns ~1–2k tokens but starts cold, can't do quick back-and-forth, and **can't nest**.
b. **Guard a destructive action** *(the lone invariant)* — "X must NEVER happen, even under bypass" → **PreToolUse deny hook**, never memory/skill. A `permissionDecision:"deny"` hook fires *before* the permission check and survives `--dangerously-skip-permissions`; memory is only guidance. Match inside the script and **fail closed**.
c. **Don't let a hook hinder** — scope with `matcher` + `if`; keep `UserPromptSubmit` trivial (30s cap); use `async`/`asyncRewake` for slow work; parse `stop_hook_active` (Stop hooks are force-overridden after 8 consecutive blocks).
d. **When to package a plugin** — standalone `.claude/` while you iterate; convert to a **plugin** the moment share / version / reuse-across-projects appears. Only `plugin.json` lives in `.claude-plugin/`; components sit at plugin root.
e. **Recurring work** — session poll → **`/loop`**; survives machine-off → **`/schedule` Routine** (cloud, min 1h, billed); local files + survives session close → **local scheduled task**; event-driven → **Channels**; until-done → **`/goal`**.

## The manager registry — discovered, not assumed

claude-expert is the **router**; the convention is that each artifact type has a
dedicated **manager** skill that owns its lifecycle (review-first, archive-don't-delete,
ask-before-changing). claude-expert picks the surface and hands off — it never edits.

**This roster is not hardcoded.** Which managers actually exist depends on what
*your* setup installed. At invocation, `discover-setup.sh` reports a `MANAGERS`
section: for each artifact TYPE it detects whether a managing skill is `PRESENT`
or a `GAP`, by conventional name AND by scanning skill descriptions for
"`<type> ... manager`". **Route to a manager only if discovery reports it present;
if it's a GAP, say so and fall back to the relevant `surfaces/*.md` plus a
settings-writing skill.** Conventional names below are *examples of what to look
for*, not a guarantee any are installed. Full framing, the gap-handling rules, and
cross-cutting conventions: [managers.md](managers.md) + the live `discover-setup.sh` map.

| Artifact type | Conventional manager name(s) to look for | Trigger |
|:--|:--|:--|
| Skills / slash commands | `skills-manager` | add/update/review a skill |
| Subagents | `agent-manager` | add/edit/review an agent |
| Hooks | `hooks-manager` | "run X every time", "block Y", hook review |
| Loops (`/loop`, session) | `loops-manager` | "poll X", "/loop", "what loops are running" |
| Schedules (Routines, cron, scheduled tasks) | `schedules-manager` | "run nightly/weekly", "list my routines" |
| Plugins / marketplaces | `plugins-manager` | "package as a plugin", "install a plugin" |
| Logs / telemetry | `logs-manager` | "rotate/prune logs", "what writes this log" |
| Memory (`MEMORY.md`, auto-memory) | `memory-manager` | "clean/audit/promote memory" |
| MCP health / lifecycle | `mcp-doctor` / `mcp-manager` | "check MCP", add/remove a server |
| Settings / permissions | `update-config` | "allow X", "set env", "from now on when X" |
| Keybindings | `keybindings-help` | "rebind", "change submit key" |
| Secrets / credentials | `key-manager` | "store/rotate/audit a key" |
| Files / substrate | a file/substrate manager (e.g. `file-keeper`) | "where does this live" |
| Cost / context | a cost/context auditor | "audit cost", "sessions feel slow" |

Any manager **checks claude-expert when the surface is genuinely ambiguous** (not as
a ritual for obvious cases), and any manager that writes settings **delegates the
write to a settings skill** (e.g. `update-config`). Say it plain: claude-expert
teaches the map; the managers drive the cars — and they're drivers, not
rule-followers. See [reasoning.md](reasoning.md).

## How to use this skill

- **Free-form question:** "How do hooks differ from memory?" → points you to
  [surfaces/hooks.md](surfaces/hooks.md) + [surfaces/memory.md](surfaces/memory.md),
  or answers from the summary if it's short.
- **Which-surface question:** "Where should I put a rule that blocks `rm -rf`?"
  → PreToolUse deny / `deny` permission rule, then delegates the write to a
  settings/hooks manager (if discovery reports one).
- **Scoped arg:** Pass a surface name — `/claude-expert hooks` opens the hooks
  reference, `/claude-expert settings` opens settings, etc.
- **For doing:** don't let claude-expert edit. Ask which surface, then delegate
  to the discovered doer.

## Answer protocol — docs first, source second

When answering "how does Claude Code actually do X":

1. **Read the relevant `surfaces/<topic>.md`** for the distilled doc answer.
2. **If that's sufficient, answer and stop.** Cite `code.claude.com/docs`.
3. **If the surface file is silent, ambiguous, or flagged `(docs unclear —
   verify before relying on this)`**, escalate under the hood, in order:
   a. the **official open SDK repos** (`anthropics/claude-agent-sdk-python`,
      `anthropics/claude-agent-sdk-typescript`) for SDK behavior;
   b. a **local open-source Python reimplementation** of Claude Code if one is
      installed — `discover-setup.sh` reports its path as `PYTHON_PORT` (e.g. a
      clone of the open SafeRL-Lab Python reimplementation). If absent, the map
      prints how to clone it. Use it for under-the-hood mechanism checks;
   c. a **live reproduction** in a throwaway dir (run the actual CLI and observe).
4. **Cite source findings distinctly** — e.g.
   `Source (open SDK repo): claude-agent-sdk-python/.../file.py:Lxx` or
   `Source (live repro): observed behavior of <command>`. Do not blur these with
   doc citations; reimplementations and snapshots may drift from the shipped CLI.
5. **Delegate deep greps to the `Explore` subagent** to keep main context clean.

This protocol — knowing when to go past the docs to the open source or a live
repro — is what makes this skill an "expert" rather than a wiki. It relies only on
official open repos, a discovered open reimplementation, and direct reproduction —
never on any private or closed source tree.

## Pointer

- Judgment over rules (read first — the hub principle): [reasoning.md](reasoning.md)
- On-invocation discovery + freshness: `discover-setup.sh`, `freshness-check.sh`
- Decision forks (full tables + failure modes): [decision-forks.md](decision-forks.md)
- Anti-pattern catalog (wrong → right surface): [anti-patterns.md](anti-patterns.md)
- Manager registry (discovery-based roster, gaps): [managers.md](managers.md)
- Latest & best practices (auto-updated): [latest.md](latest.md) · Self-update protocol: [self-update.md](self-update.md)
- Full disambiguation table: [decision-tree.md](decision-tree.md) · Patterns: [patterns.md](patterns.md) · Failure modes: [pitfalls.md](pitfalls.md)

## Version / freshness

See [latest.md](latest.md) for the live freshness date — the self-update bumps it
there. The 2026 baseline absorbed Channels, LSP-in-plugins, `/goal`, `auto` mode,
~29 hook events, the slash-commands→skills merge, and the three-surface scheduling
model.

This skill keeps itself current via a **bounded, gated self-update** with two
triggers — a **lazy on-invocation check** (`freshness-check.sh`: if it hasn't
researched in ≥7 days it spawns a background refresh and answers your task in
parallel) plus an optional **scheduled backstop**. Both append additive facts to
[latest.md](latest.md) and propose any decision-logic change into the staging dir
(reported by `discover-setup.sh`) — never rewriting the decision logic unprompted.
See [self-update.md](self-update.md).

`docs.claude.com/en/docs/claude-code/*` now 301-redirects to
`code.claude.com/docs/en/*`. Agent SDK docs live on
`code.claude.com/docs/en/agent-sdk/*` (formerly `platform.claude.com`).
