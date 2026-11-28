"""Wire the compaction-safeguard hooks into a workspace's .claude/settings.json.

Shared by init.py and sync.py. The scripts live in
`<workspace>/.claude/hooks/memnyx/`, a folder Memnyx owns, and are deployed and
synced like skills; a user's own scripts in `.claude/hooks/` are never touched.
This module only maintains the settings entries that call them.

Ownership rule (v2-design-principles.md, "Update and contribution flow"):
settings.json stays user-owned. Memnyx manages only entries whose command is
exactly one it generates, and never removes or changes anything else. The
commands carry no machine path (`$CLAUDE_PROJECT_DIR`), so a settings.json
committed and shared across machines stays correct on each. The status line is
set only when no settings scope already has one.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SETTINGS_REL = ".claude/settings.json"
LOCAL_SETTINGS_REL = ".claude/settings.local.json"
SCRIPTS_REL = ".claude/hooks/memnyx"
COMPACTION_SCRIPT_REL = f"{SCRIPTS_REL}/compaction.sh"
STATUSLINE_SCRIPT_REL = f"{SCRIPTS_REL}/statusline.sh"

# event -> (matcher, compaction.sh argument)
HOOK_EVENTS = [
    ("PreCompact", "*", "pre"),
    ("PostCompact", "*", "post"),
    ("SessionStart", "compact", "resume"),
]
TIMEOUT_SECONDS = 10


def hook_command(arg: str) -> str:
    # $CLAUDE_PROJECT_DIR is set for hook commands (Claude Code hooks docs).
    return f'bash "$CLAUDE_PROJECT_DIR"/{COMPACTION_SCRIPT_REL} {arg}'


# Whether $CLAUDE_PROJECT_DIR reaches status-line commands is not documented;
# the fallback runs from the session's working directory.
STATUS_COMMAND = f'bash "${{CLAUDE_PROJECT_DIR:-.}}"/{STATUSLINE_SCRIPT_REL}'

OUR_HOOK_COMMANDS = {hook_command(arg) for _, _, arg in HOOK_EVENTS}


def _default_user_settings() -> Path:
    return Path.home() / ".claude/settings.json"


def _wire_event(hooks: dict, event: str, matcher: str, want: str) -> tuple[list[str], bool]:
    """Leave `event` with exactly one Memnyx entry: command `want` under `matcher`.

    Removes Memnyx-generated entries that are duplicates or sit under the wrong
    matcher; user entries are never touched. Returns (actions, changed).
    """
    groups = hooks.get(event)
    if groups is None:
        groups = hooks[event] = []
    if not isinstance(groups, list):
        return [f"skipped hooks.{event}: not a list, left as is"], False

    actions: list[str] = []
    kept = False
    for group in list(groups):
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            continue
        right_matcher = group.get("matcher") == matcher
        remaining = []
        for h in group["hooks"]:
            cmd = h.get("command") if isinstance(h, dict) else None
            if cmd not in OUR_HOOK_COMMANDS:
                remaining.append(h)
            elif cmd == want and right_matcher and not kept:
                kept = True
                remaining.append(h)
            else:
                actions.append(f"removed a duplicate or misplaced Memnyx entry from hooks.{event}")
        if len(remaining) != len(group["hooks"]):
            if remaining:
                group["hooks"] = remaining
            else:
                groups.remove(group)
    if not kept:
        groups.append({
            "matcher": matcher,
            "hooks": [{"type": "command", "command": want, "timeout": TIMEOUT_SECONDS}],
        })
        actions.append(f"added hooks.{event} ({want})")
    return actions, bool(actions)


def _status_line_elsewhere(workspace: Path, user_settings: Path) -> str | None:
    """Name the other settings file that already sets a statusLine, if any."""
    for label, path in (
        (LOCAL_SETTINGS_REL, workspace / LOCAL_SETTINGS_REL),
        ("~/.claude/settings.json", user_settings),
    ):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("statusLine") is not None:
            return label
    return None


def _write_atomic(path: Path, data: dict) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def wire_settings(workspace: Path, apply: bool, user_settings: Path | None = None) -> list[str]:
    """Plan (apply=False) or make (apply=True) the settings changes.

    Returns one human-readable line per action or notice. The file is written
    only when an entry is added or removed. Never raises on a malformed
    settings file: it reports and touches nothing.
    """
    user_settings = user_settings or _default_user_settings()
    path = workspace / SETTINGS_REL
    if path.is_symlink():
        return [f"skipped {SETTINGS_REL}: it is a symlink; wire the hooks by hand"]
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return [f"skipped {SETTINGS_REL}: not readable as JSON ({e.__class__.__name__}); nothing changed"]
        if not isinstance(data, dict):
            return [f"skipped {SETTINGS_REL}: top level is not an object; nothing changed"]
    else:
        data = {}

    hooks = data.get("hooks")
    if hooks is None:
        hooks = data["hooks"] = {}
    if not isinstance(hooks, dict):
        return [f"skipped {SETTINGS_REL}: `hooks` is not an object; nothing changed"]

    actions: list[str] = []
    changed = False
    for event, matcher, arg in HOOK_EVENTS:
        acts, ch = _wire_event(hooks, event, matcher, hook_command(arg))
        actions.extend(acts)
        changed = changed or ch

    status = data.get("statusLine")
    if status is None:
        elsewhere = _status_line_elsewhere(workspace, user_settings)
        if elsewhere:
            actions.append(
                f"kept your statusLine (set in {elsewhere}); for the context gauge, "
                f"set its command to: {STATUS_COMMAND}"
            )
        else:
            data["statusLine"] = {"type": "command", "command": STATUS_COMMAND}
            actions.append(f"added statusLine (context gauge, {STATUS_COMMAND})")
            changed = True
    elif not (isinstance(status, dict) and status.get("command") == STATUS_COMMAND):
        actions.append(
            f"kept your statusLine; for the context gauge, set its command to: {STATUS_COMMAND}"
        )

    if apply and changed:
        _write_atomic(path, data)

    actions.extend(_local_duplicates(workspace))
    return actions


def _local_duplicates(workspace: Path) -> list[str]:
    """Warn when settings.local.json also runs a compaction.sh: both would fire."""
    path = workspace / LOCAL_SETTINGS_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return []
    events = []
    for event, groups in hooks.items():
        for group in groups if isinstance(groups, list) else []:
            for h in (group.get("hooks") or []) if isinstance(group, dict) else []:
                cmd = h.get("command") if isinstance(h, dict) else None
                if isinstance(cmd, str) and "compaction.sh" in cmd and event not in events:
                    events.append(event)
    if not events:
        return []
    return [
        f"warning: {LOCAL_SETTINGS_REL} also runs a compaction.sh on {', '.join(events)}; "
        "both copies will fire. Remove those entries there (this tool does not edit that file)."
    ]
