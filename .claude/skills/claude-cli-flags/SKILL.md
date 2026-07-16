---
name: claude-cli-flags
description: Authoritative, version-pinned reference for every Claude Code CLI flag, classified by whether it works in an INTERACTIVE session (default TUI), a HEADLESS session (-p/--print), or BOTH — plus the canonical launch recipes for each mode. Use when any session needs to launch or script `claude` and must know which switch is valid in which mode, build a headless/streaming invocation, set up remote-control or an always-on session, pass model/effort/permissions/MCP/plugin/settings flags, or answer "does flag X work with -p / in interactive". Trigger: "claude flags", "claude cli switches", "which flags work headless vs interactive", "-p flags", "stream-json flags", "how do I launch claude with X", "/claude-cli-flags".
user_invocable: true
args: "Optional keyword to jump: headless | interactive | both | recipes | subcommands. Empty = full reference."
allowed-tools: Bash, Read
---

# claude-cli-flags — interactive vs headless switch reference

> **NOTE — a common preference: favor interactive, visible sessions over headless `-p`.** Many
> setups prefer **interactive, visible Claude Code sessions** over headless one-shots. A `-p` call
> deliberates with no live window into the reasoning — it can't be watched or caught mid-flight,
> which can undercut transparency. If that matters to you, prefer: an interactive session,
> `--remote-control`, or a streamed live session (`--input-format/--output-format stream-json`), and
> reach for `-p` only with a concrete reason. This is a configurable preference, not a hard rule —
> adjust it to your project. The flags below are documented for completeness either way.

**Pinned to `claude 2.1.183`.** Source of truth is the binary itself: re-derive anytime with
`claude --help`. If the installed version differs materially, re-run help and update this file
(the `--version` check below tells you).

```bash
claude --version    # confirm this still matches 2.1.183 before trusting the table verbatim
```

## The one switch everything pivots on

- **no `-p`** → **interactive** TUI (default; prompt box, slash commands, pickers).
- **`-p` / `--print`** → **headless**: run the prompt, print, exit. Also: the **workspace-trust dialog
  is auto-skipped** in headless (or any non-TTY/piped stdout) — only run `-p` in trusted dirs.
  **See the note above — many setups prefer an interactive/visible session.**

---

## HEADLESS-ONLY  (args: `headless`)
The help text explicitly gates these to `--print` (or to a stream-json format, which implies print).

| Flag | Meaning |
|---|---|
| `-p, --print` | the headless switch itself |
| `--output-format <text\|json\|stream-json>` | shape of printed output; `stream-json` = realtime NDJSON |
| `--input-format <text\|stream-json>` | `stream-json` feeds **multiple messages over stdin** (always-on programmatic driving) |
| `--include-partial-messages` | stream token deltas (requires `--output-format=stream-json`) |
| `--include-hook-events` | emit hook lifecycle events into the stream (requires `stream-json`) |
| `--replay-user-messages` | echo stdin messages back on stdout for ack (stream-json in **and** out) |
| `--max-budget-usd <amount>` | hard dollar cap for the run |
| `--no-session-persistence` | don't write the session to disk (can't be resumed) |
| `--fallback-model <m,m,…>` | auto-fail-over models when overloaded; retries primary each turn |
| `--json-schema <schema>` | validate/force structured output (print/SDK) |
| `--prompt-suggestions` | in print/SDK, emits a predicted-next-prompt message each turn |

---

## INTERACTIVE-ONLY  (args: `interactive`)
Reference TUI concepts (prompt box, pickers, IDE, panes) — no meaning headless.

| Flag | Why interactive |
|---|---|
| *(default, no `-p`)* | the interactive session itself |
| `--remote-control [name]` | "Start an **interactive** session with Remote Control" (drive from claude.ai/phone) |
| `--remote-control-session-name-prefix <p>` | names auto-generated remote-control sessions |
| `--ide` | auto-connect to an IDE on startup |
| `--tmux` | spawn a tmux session for the worktree (requires `--worktree`; iTerm2 native panes if available) |
| `-w, --worktree [name]` | new git worktree for the live session |
| `-n, --name <name>` | display name in the **prompt box / `/resume` picker / terminal title** |
| `--from-pr [value]` | resume a PR-linked session, or open an **interactive picker** |
| `-r, --resume` *(no value)* | **interactive picker** (WITH a value it resumes by id — works headless too, see Both) |

---

## WORKS IN BOTH  (args: `both`)
Mode-agnostic session configuration — valid with or without `-p`.

**Model / effort**
`--model <alias|full>` · `--effort <low\|medium\|high\|xhigh\|max>`

**Permissions / tools**
`--permission-mode <acceptEdits\|auto\|bypassPermissions\|default\|dontAsk\|plan>` ·
`--dangerously-skip-permissions` · `--allow-dangerously-skip-permissions` ·
`--allowedTools <…>` · `--disallowedTools <…>` · `--tools <…>` (`""`=none, `default`=all)

**Context / prompt**
`--add-dir <dirs…>` · `--system-prompt <p>` · `--append-system-prompt <p>` ·
`--exclude-dynamic-system-prompt-sections` (better prompt-cache reuse; default system prompt only) ·
`--file <file_id:relpath…>`

**Agents / skills**
`--agent <name>` · `--agents <json>` · `--disable-slash-commands` · `--brief` (enables SendUserMessage)

**MCP**  `--mcp-config <files|json…>` · `--strict-mcp-config`

**Plugins**  `--plugin-dir <path>` · `--plugin-url <url>` (both repeatable)

**Settings / auth**  `--settings <file|json>` · `--setting-sources <user,project,local>` · `--betas <…>`

**Session lifecycle**  `-c, --continue` · `-r, --resume <value>` (by id) · `--session-id <uuid>` · `--fork-session`

**Modes / troubleshooting**  `--bare` (minimal; sets `CLAUDE_CODE_SIMPLE=1`) ·
`--safe-mode` (all customizations off; sets `CLAUDE_CODE_SAFE_MODE=1`) ·
`-d, --debug [filter]` · `--debug-file <path>` · `--verbose` · `--ax-screen-reader` ·
`--chrome` / `--no-chrome` · `--mcp-debug` *(deprecated → use `--debug`)*

---

## Canonical recipes  (args: `recipes`)

```bash
# INTERACTIVE, drivable from claude.ai / phone:
claude --remote-control my-session

# INTERACTIVE, unattended tool calls (e.g. an always-on session driven externally):
claude --dangerously-skip-permissions --remote-control my-session

# HEADLESS one-shot, structured output:
claude -p "summarize the diff" --output-format json

# HEADLESS streaming, always-on programmatic driving (feed many msgs over stdin):
claude -p --input-format stream-json --output-format stream-json --include-partial-messages

# HEADLESS with a hard budget + model fallback:
claude -p "do X" --max-budget-usd 0.50 --fallback-model sonnet,haiku

# Resume a specific session headless (by id, no picker):
claude -p -r <session-id> "continue with Y"
```
Interactive vs headless for always-on work: `--remote-control` = human + claude.ai both drive one TUI.
The `-p --input-format stream-json` trio = a program drives it, with structured read-back.

---

## Related
For the in-session `/` slash commands (not launch flags), see the **claude-slash-commands** skill.

## Not flags — subcommands  (args: `subcommands`)
`claude <command>`: `agents` · `auth` · `mcp` · `plugin|plugins` · `project` · `doctor` · `install` ·
`update|upgrade` · `setup-token` · `ultrareview` · `auto-mode`.

## Honesty
- Classification follows the v2.1.183 `--help` annotations verbatim; "BOTH" = no mode gate stated.
- A flag valid in a mode can still be a no-op if its dependency is absent (e.g. `--tmux` needs `--worktree`;
  `--include-partial-messages` needs `--output-format=stream-json`).
- Re-confirm against `claude --help` if the version moved past 2.1.183.
