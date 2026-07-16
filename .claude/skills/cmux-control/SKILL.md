---
name: cmux-control
description: Deterministic playbook for controlling and introspecting cmux terminal tabs and the Claude Code sessions running in them — without re-researching each time. Covers enumerating/indexing every tab, reading & changing tab names, injecting text/commands into a tab from outside, reading a tab's output (read-screen/capture-pane/pipe-pane), launching & driving Claude Code, and inspecting Claude internals (per-tab turn-state, surface→session-id map, on-disk transcript, Feed/approval cards). Also covers the always-on, externally-streamable Claude session pattern. Use when any session needs to list/find tabs, send keystrokes into another tab, read what another tab shows, drive or monitor another Claude Code session, build a fleet monitor, or wire an external command stream into a live session. Trigger: "control cmux", "inject into a tab", "read another tab", "list/index the tabs", "what claude sessions are running", "drive another claude", "send keys to surface", "cmux session map", "/cmux-control".
user_invocable: true
args: "Optional. A task keyword to jump to the matching section: enumerate | names | inject | read | launch | internals | always-on | feed. Empty = print the section index."
allowed-tools: Bash, Read
---

# cmux-control — drive & introspect cmux tabs + Claude Code, deterministically

Every command here was verified live against cmux + Claude Code. cmux is socket-controlled
JSON-RPC over `~/.local/state/cmux/cmux.sock`. **Run all of this only from inside cmux** (the
socket + identity env are present there). No research needed — copy the recipe for the task.

## 0. Preamble — always start with this

```bash
CMUX=/Applications/cmux.app/Contents/Resources/bin/cmux
export CMUX_QUIET=1                       # silence the alias deprecation notices
# Inside any cmux terminal these are auto-set and used as defaults:
#   CMUX_WORKSPACE_ID  CMUX_SURFACE_ID  CMUX_PANE/TAB_ID   (and CMUX_CLAUDE_PID on claude tabs)
```

**Object model:** `window → workspace (tab-group) → pane → surface (a tab)`.
**Refs** are interchangeable everywhere as: index (`2`), short ref (`surface:40` / `workspace:12`), or UUID.
Pass `--id-format both` to any list command to get BOTH the short ref and the UUID
(the UUID is the key that links a tab to its Claude session — see §6).

> Gotcha learned the hard way: `send`/`send-key` and `top` may need an **explicit `--workspace`**
> alongside `--surface`; a bare `--surface` can error `Workspace not found`. Always pass both.

---

## 1. Enumerate / index every tab  (args: `enumerate`)

```bash
$CMUX list-windows                                              # windows
$CMUX workspace list                                           # workspaces (tab-groups)
$CMUX list-panes          --workspace <ws>                     # panes in a workspace
$CMUX list-pane-surfaces  --workspace <ws> --id-format both    # the actual tabs (+ UUIDs)
$CMUX tree --all                                               # everything at once
$CMUX top  --all --processes                                   # live CPU/mem/proc per surface
$CMUX identify --surface <ref>                                 # JSON: refs, surface_type, focus state
```

One-shot table of EVERY tab → turn-state → claude session id → transcript path:
```bash
bash <skill-dir>/scripts/cmux-introspect.sh
```

---

## 2. Read & change tab names  (args: `names`)

```bash
# READ: the name is the trailing text in `list-pane-surfaces` output.
$CMUX list-pane-surfaces --workspace <ws>

# CHANGE:
$CMUX rename-tab       --workspace <ws> --surface <ref> "New tab name"
$CMUX rename-workspace --workspace <ws> "New workspace name"
$CMUX rename-window    --window <w>     "New window name"
```
Note: a Claude tab **auto-titles itself** from the running prompt. `rename-tab` overrides it
(the override sticks until Claude retitles on the next prompt; rename again if needed).

---

## 3. Inject text / commands into a tab from outside  (args: `inject`)

The core primitive — indistinguishable from a human typing, works on a shell OR a Claude prompt box,
and coexists with a human typing in the same tab:
```bash
$CMUX send     --workspace <ws> --surface <ref> -- "the text to type"
$CMUX send-key --workspace <ws> --surface <ref> Enter        # submit it
```
- Special keys: `send-key ... Enter | Escape | Tab | C-c | Up | Down` (Escape interrupts a running
  Claude turn; `Tab` twice / `S-Tab` cycles Claude permission modes).
- Paste path (for big/multiline blobs): `$CMUX set-buffer "text"` then `$CMUX paste-buffer --surface <ref>`.
- **Boot race:** injecting before a TUI finishes booting throws `Broken pipe`. RETRY. Deterministic injector:
```bash
inject(){  # inject <ws> <surface> <text>
  local ws="$1" s="$2" t="$3" i
  for i in 1 2 3 4 5; do
    "$CMUX" send --workspace "$ws" --surface "$s" -- "$t" 2>/dev/null \
      && "$CMUX" send-key --workspace "$ws" --surface "$s" Enter 2>/dev/null && return 0
    sleep 2
  done; return 1; }
```

---

## 4. Read a tab's output  (args: `read`)

```bash
$CMUX read-screen  --workspace <ws> --surface <ref> --lines 60              # rendered visible screen
$CMUX read-screen  --workspace <ws> --surface <ref> --lines 200 --scrollback # include scrollback
$CMUX capture-pane --workspace <ws> --surface <ref> --lines 60              # tmux-compat alias, same result
$CMUX pipe-pane    --surface <ref> --command 'cat >> /tmp/tap.log'          # CONTINUOUS stream of the pane to a cmd
```
`read-screen` on a Claude tab returns the full rendered TUI: its replies, the `⏺ Bash(...)` tool
lines, the `✻ Worked for Ns` timer, and the prompt box. For verbatim/structured reading prefer the
transcript jsonl (§6) — the screen is lossy (truncated/wrapped), the jsonl is ground truth.

---

## 5. Launch & control a Claude Code session  (args: `launch`)

cmux takes **no** Claude flags of its own — you hand it a full claude command line.
**For which claude flags are valid interactive vs headless, see the `claude-cli-flags` skill.**
```bash
# new always-on claude in its own workspace:
$CMUX new-workspace --name "cc-live" --cwd "$HOME" \
      --command "claude --dangerously-skip-permissions --remote-control my-session" \
      --focus false --id-format both
# native agent-session tab (deeper integration than a plain terminal running claude):
$CMUX new-surface --type agent-session --provider claude --workspace <ws>
# resume a dead tab's prior session:
$CMUX surface resume set --surface <ref>     # or relaunch with: claude --resume <session-id>
```
After launch, **all control = §3 injection**: prompts, `/slash` commands, `Escape` to interrupt,
`S-Tab` to cycle modes. There is no separate "control API"; the TUI is the API.

---

## 6. Inspect Claude Code internals  (args: `internals`)  ← the deep part

cmux PATH-shims the `claude` binary (`…/cmux-cli-shims/<surface-uuid>/claude` →
`cmux-claude-wrapper`) which **injects Claude Code hooks** that report lifecycle back to cmux.
That is the entire basis of cmux's awareness — there is **no** granular `claude.turn.*` RPC.

**(a) Per-tab turn-state** (pushed by the injected hooks):
```bash
$CMUX list-status --workspace <ws>
# → claude_code=Needs input icon=bell.fill color=#4C8DFF
# states: running | idle | needsInput | unknown
```

**(b) Surface → Claude session id map** (the keystone):
```bash
cat ~/.cmuxterm/claude-hook-sessions.json   # { activeSessionsBySurface: { <surface-UUID>: {sessionId,...} } }
```
Look up the UUID from `list-pane-surfaces --id-format both` (§1).

**(c) Full verbatim transcript** (deepest "what's happening inside" — every message, tool call, result):
```bash
find ~/.claude/projects -name "<session-id>.jsonl"      # the on-disk transcript for that tab
```

**(d) Raw hook event feed / live bus:**
```bash
ls -la ~/.cmuxterm/events.jsonl ~/.cmuxterm/workstream.jsonl   # raw hook events (large)
$CMUX events --limit 20 --no-heartbeat --no-ack               # live subscription
$CMUX list-log --workspace <ws> --limit 20                    # per-surface log
```

**Hooks plumbing:** `$CMUX hooks` (mgmt) · `$CMUX hooks setup` · "Claude Code hooks are injected
automatically by the cmux Claude wrapper" (no manual install needed for claude).

---

## 7. Feed / approvals from outside  (args: `feed`)

Claude **PermissionRequest** events become cmux approval cards — so permission prompts can be
seen/answered without touching the TUI:
```bash
$CMUX list-notifications                       # e.g. "Claude Code | Waiting | Claude is waiting for your input"
$CMUX mark-notification-read --id <uuid>
$CMUX dismiss-notification --id <uuid>
$CMUX jump-to-unread
```

---

## 8. Always-on, externally-streamable Claude session  (args: `always-on`)

Pattern: launch claude in a cmux workspace (§5) → a FIFO inbox + a small watcher script that
injects each incoming line (§3) → optional HTTP door (a tiny local server) so "outside" can be a
curl call, a phone shortcut, a cron job, or another agent. This is a pattern to build, not a
bundled tool — wire it up per-project as:
```
start.sh   # boots the session + the inbox watcher
send.sh 'do the thing'   # streams a command in from anywhere
```
The three native alternatives and when to pick them:
| Need | Use |
|---|---|
| interactive TUI + drive from claude.ai/phone, no scripts | `claude --remote-control <name>` |
| purely programmatic, headless, structured I/O | `claude -p --input-format stream-json --output-format stream-json` |
| interactive TUI **and** arbitrary local/script injection **and** read-back | this cmux pattern (§3+§4) |

---

## Honest limits (don't overclaim)
- Internals visibility = exactly what the hooks report (status + approvals). Anything finer → read the transcript jsonl (§6c).
- `read-screen` is lossy (wrapped/truncated); jsonl is ground truth.
- A locally-bound HTTP door for the always-on pattern (§8) has no auth by default — add your own if it's reachable beyond localhost.
- `--dangerously-skip-permissions` makes injected tool calls run unattended; without it, injection only fills the box and the Feed (§7) still gates each call.
- Everything assumes you're running inside cmux (socket + identity env present).
