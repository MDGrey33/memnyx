---
name: claude-slash-commands
description: Authoritative, version-pinned reference for every built-in Claude Code slash (/) command — what each does, its aliases, and which are bundled Skills/Workflows vs fixed built-ins — plus how custom slash commands work (the commands-merged-into-skills model, file locations, frontmatter, arguments, !bash, @file). Includes the full /loop vs /schedule breakdown. Use when any session needs to know what a slash command does, find the right command for a task (clear context, switch model, review code, schedule work, background a task), or author a custom /command. Trigger: "claude slash commands", "what does /X do", "list the slash commands", "built-in commands", "custom slash command", "/loop vs /schedule", "how do I make a /command", "/claude-slash-commands". Sibling of claude-cli-flags (launch flags).
user_invocable: true
args: "Optional keyword to jump: session | model | project | parallel | review | cloud | schedule | account | ui | custom | loop-vs-schedule. Empty = full reference."
allowed-tools: Bash, Read
---

# claude-slash-commands — built-in `/` command reference

**Pinned to `claude 2.1.183`** (source: `code.claude.com/docs/en/commands`, verified against the binary).
A command is only recognized at the **start** of a message; text after the name is passed as arguments.
Type `/` in-session to see what's available to *you* (plan/platform-gated commands vary). Re-derive
the canonical list anytime by fetching the commands reference; re-check if the version moved past 2.1.183.

> **Skill** = prompt-based, Claude orchestrates with tools. **Workflow** = multi-agent fan-out.
> Everything else = fixed built-in logic. Aliases shown as `(= /x)`.

## Session & context  (args: `session`)
| Command | Does |
|---|---|
| `/clear [name]` | New conversation, empty context; old one stays in `/resume`. `(= /reset, /new)` |
| `/compact [instructions]` | Summarize the conversation to free context (optional focus) |
| `/context [all]` | Visualize context-window usage as a grid + optimization hints |
| `/rewind` | Rewind conversation and/or code to a prior point. `(= /checkpoint, /undo)` |
| `/resume [session]` | Resume by id/name or open picker. `(= /continue)` |
| `/branch [name]` | Fork the conversation at this point to try another direction; original kept |
| `/fork <directive>` | Spawn a forked subagent that inherits the convo; result returns to you (v2.1.161+) |
| `/btw <question>` | Quick side question that doesn't bloat history |
| `/export [filename]` | Export the conversation as plain text |
| `/copy [N]` | Copy the last (or Nth-latest) assistant response to clipboard |
| `/rename [name]` | Rename the current session shown on the prompt bar |
| `/recap` | One-line summary of the current session |
| `/diff` | Interactive diff viewer: git diff and per-turn diffs |
| `/cd <path>` | Move the session to a new working dir, cache preserved (v2.1.169+) |
| `/add-dir <path>` | Grant file access to another dir for this session |

## Model & reasoning  (args: `model`)
| Command | Does |
|---|---|
| `/model [model]` | Switch model + save as default; `s` on a row = session-only |
| `/effort [level\|auto]` | Set reasoning effort (low/medium/high/xhigh/max/auto) |
| `/fast [on\|off]` | Toggle fast mode (faster Opus output) |
| `/plan [description]` | Enter plan mode, optionally with a starting task |
| `/goal [condition\|clear]` | Run until a condition is met (until-done) |

## Project setup, permissions & config  (args: `project`)
| Command | Does |
|---|---|
| `/init` | Generate a starter `CLAUDE.md` (set `CLAUDE_CODE_NEW_INIT=1` for interactive) |
| `/memory` | Edit CLAUDE.md memory files; manage auto-memory |
| `/permissions` | Manage allow/ask/deny tool rules. `(= /allowed-tools)` |
| `/config [key=value …]` | Settings UI, or set a key directly (v2.1.181+). `(= /settings)` |
| `/hooks` | View hook configurations for tool events |
| `/mcp [reconnect\|enable\|disable <server>]` | Manage MCP servers |
| `/agents` | Manage subagent configurations |
| `/skills` | List skills; hide a skill from Claude or the `/` menu |
| `/plugin [subcommand]` | Manage plugins (list/install/enable/disable) |
| `/reload-plugins [--force]` | Reload plugins without restart |
| `/reload-skills` | Re-scan skill/command dirs mid-session (v2.1.152+) |
| `/keybindings` | Open the keyboard-shortcuts file |
| `/statusline` | Configure the status line |
| `/terminal-setup` | Configure Shift+Enter etc. (only in terminals that need it) |
| `/sandbox` | Toggle sandbox mode (supported platforms) |

## Parallel & background work  (args: `parallel`)
| Command | Does |
|---|---|
| `/background [prompt]` | Detach the session to run as a background agent. `(= /bg)` |
| `/tasks` | View/manage everything running in the background. `(= /bashes)` |
| `/stop` | Stop the attached background session (keeps transcript/worktree) |
| `/batch <instruction>` | **Skill.** Decompose a big change into 5–30 units, one subagent+worktree each, opens PRs |
| `/workflows` | Open the workflow progress view (watch/pause/resume/save) |

## Code review, run & quality  (args: `review`)
| Command | Does |
|---|---|
| `/review [PR]` | Review a PR locally in this session |
| `/code-review [low\|medium\|high\|ultra]` | **Skill.** Review the diff for bugs; `ultra` = deep cloud multi-agent |
| `/security-review` | Analyze branch changes for security vulnerabilities |
| `/simplify [target]` | **Skill.** Parallel cleanup review + apply fixes (no bug-hunt) (v2.1.154+) |
| `/run` | **Skill.** Launch & drive your app to see a change work (v2.1.145+) |
| `/verify` | **Skill.** Build+run the app to confirm a change works (v2.1.145+) |
| `/run-skill-generator` | **Skill.** Record a per-project run/verify recipe |
| `/debug [description]` | **Skill.** Enable debug logging + troubleshoot from the log |
| `/fewer-permission-prompts` | **Skill.** Mine transcripts → add a read-only allowlist |
| `/deep-research <question>` | **Workflow.** Fan-out web research → cited report |
| `/ultraplan <prompt>` | Draft a plan in a cloud session, review in browser, execute |

## Cloud / web / remote  (args: `cloud`)
| Command | Does |
|---|---|
| `/remote-control` | Make this session drivable from claude.ai. `(= /rc)` |
| `/teleport` | Pull a Claude-Code-on-web session into this terminal. `(= /tp)` |
| `/background` | (see Parallel) detaches to a background/cloud agent |
| `/autofix-pr [prompt]` | Cloud session that watches the branch's PR and pushes CI/review fixes |
| `/desktop` | Continue this session in the Claude Code Desktop app. `(= /app)` |
| `/remote-env` | Choose the default environment for cloud agents |
| `/web-setup` | Connect GitHub to Claude Code on the web via local `gh` |
| `/install-github-app` | Set up the Claude GitHub Actions app for a repo |
| `/install-slack-app` | Install the Claude Slack app (OAuth) |

## Scheduling & automation  (args: `schedule`) — see also the `loop-vs-schedule` section
| Command | Does |
|---|---|
| `/loop [interval] [prompt]` | **Skill.** Re-run a prompt while the session stays open; omit interval → self-paced; omit prompt → `.claude/loop.md` or maintenance. `(= /proactive)` |
| `/schedule [description]` | Create/update/list/run **cloud Routines** (Anthropic-managed infra). `(= /routines)` |

## Account, usage & info  (args: `account`)
| Command | Does |
|---|---|
| `/login` · `/logout` | Sign in / out of your Anthropic account |
| `/usage` | Session cost, plan limits, activity (by skill/subagent/plugin/MCP). `(= /cost, /stats)` |
| `/usage-credits` | Configure credits to keep working past a limit |
| `/status` | Settings → Status tab: version, model, account, connectivity |
| `/doctor` | Diagnose the install/settings; press `f` to let Claude fix |
| `/insights` · `/team-onboarding` | Reports analyzing your sessions / onboarding guide |
| `/release-notes` | Changelog version picker |
| `/help` | Help + available commands |
| `/feedback [report]` | Submit feedback / bug / share. `(= /bug, /share)` |
| `/privacy-settings` | View/update privacy settings (Pro/Max) |
| `/upgrade` · `/passes` | Plan upgrade / share a free week |
| `/exit` | Exit the CLI (detaches if attached to a bg session). `(= /quit)` |

## UI / misc  (args: `ui`)
`/theme` · `/color` · `/tui [default\|fullscreen]` · `/focus` · `/scroll-speed` · `/vim` *(removed v2.1.92 → use /config Editor mode)* ·
`/voice` · `/radio` (Claude FM) · `/powerup` · `/mobile` `(/ios,/android)` · `/stickers` · `/heapdump` · `/chrome` · `/ide` ·
`/setup-bedrock` · `/setup-vertex` *(only with the matching env flag)*.

---

## /loop vs /schedule — the distinction that matters  (args: `loop-vs-schedule`)

| | **`/loop`** | **`/schedule`** (cloud Routine) |
|---|---|---|
| Lifetime | session-scoped; dies on exit; 7-day auto-expire | durable; persists indefinitely |
| Runs where | **this live terminal session** (only while REPL idle) | **Anthropic cloud infra** |
| Survives machine-off? | no | **yes** |
| Local Mac access (files/shell/MCP)? | **yes** | **no** (cloud sandbox) |
| Min interval | self-paced 1 min–1 hr (or any fixed interval) | **1 hour** |
| Prompt context | inherits the live session | must be fully self-contained |
| Backing tool | `CronCreate` / `ScheduleWakeup` | `create_scheduled_task` |
| Best for | poll / iterate / watch *while you're here* | automate on a cadence *even when you're gone* |

**Decision rule:** must outlive the session or run with the Mac off → `/schedule`. Needs to keep going
while you're working (and may touch local files) → `/loop`. Need "the instant X changes" → the `Monitor`
tool (streams, not polls), not either of these.

**Third option — local scheduled task:** definitions at `~/.claude/scheduled-tasks/<name>/SKILL.md`, run by
the **Claude Desktop app** (NOT the terminal's `/schedule`, NOT a launchd job by default). Local Mac access
+ ~1-min cadence, but needs the machine on and the Desktop app running. For true always-on local automation,
an OS-level scheduler (e.g. a **launchd** plist on macOS, or a systemd/cron unit on Linux) is the real mechanism.

---

## Custom slash commands  (args: `custom`)
**Custom commands are now Skills.** `.claude/commands/deploy.md` and `.claude/skills/deploy/SKILL.md` both
create `/deploy`. Old `.claude/commands/` files keep working; skills add a folder + frontmatter + auto-loading.

**Where they live → name:**
| Location | `/name` |
|---|---|
| `~/.claude/skills/<dir>/SKILL.md` (personal) or `.claude/skills/<dir>/SKILL.md` (project) | dir name |
| `.claude/commands/<file>.md` | file name |
| Plugin `skills/<dir>/` | `plugin-name:dir` |
| Nested project skill on name clash | `apps/web:deploy` |

Precedence: enterprise > personal > project; a same-name skill overrides a bundled command; a skill beats a command of the same name.

**Frontmatter** (`SKILL.md`): `description` (required) · `allowed-tools` · `argument-hint` · `model` (or `inherit`) ·
`disable-model-invocation: true` (only *you* can run it — use for side-effecting `/deploy`, `/commit`) ·
`user-invocable: false` (only *Claude* can load it — background knowledge).

**Arguments & dynamics in the body:**
- `$ARGUMENTS` → the full argument string as typed.
- `$1`, `$2`, … (or `$ARGUMENTS[0]`…) → positional args (shell-style quoting; quote multi-word values).
- `!`<code> → run bash and inline its output into the prompt (e.g. pull a live `git diff`).
- `@path` → inline a file's contents.

**Invocation:** type `/name` directly (if user-invocable), or Claude auto-loads it when relevant (unless
`disable-model-invocation`). A few built-ins (`/init`, `/review`, `/security-review`) are also exposed to Claude via the Skill tool; most (e.g. `/compact`) are not.

---

## Honesty
- List pinned to v2.1.183; visibility varies by plan/platform (e.g. `/privacy-settings` Pro/Max; `/setup-bedrock` only with `CLAUDE_CODE_USE_BEDROCK=1`). Type `/` in-session for your actual set.
- `/vim` and `/pr-comments` were removed (v2.1.92 / v2.1.91); listed for recognition only.
- Descriptions condensed from the official reference — open it for the full prose and version notes.
