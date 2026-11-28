"""Wire the compaction-safeguard hooks into a workspace's .claude/settings.json.

Shared by init.py and sync.py. The scripts themselves live in
`<workspace>/.claude/hooks/` and are deployed and synced like skills; this
module only maintains the settings entries that call them.

Ownership rule (v2-design-principles.md, "Update and contribution flow"):
settings.json stays user-owned. Memnyx adds or re-points only its own entries,
recognised by the script path they run (`.claude/hooks/compaction.sh`,
`.claude/hooks/statusline.sh`), and never removes or changes anything else.
The status line is set only when the workspace has none.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

SETTINGS_REL = ".claude/settings.json"
LOCAL_SETTINGS_REL = ".claude/settings.local.json"
COMPACTION_SCRIPT_REL = ".claude/hooks/compaction.sh"
STATUSLINE_SCRIPT_REL = ".claude/hooks/statusline.sh"

# event -> (matcher, compaction.sh argument)
HOOK_EVENTS = [
    ("PreCompact", "*", "pre"),
    ("PostCompact", "*", "post"),
    ("SessionStart", "compact", "resume"),
]
TIMEOUT_SECONDS = 10


def _command(workspace: Path, script_rel: str, arg: str | None = None) -> str:
    cmd = f"bash {shlex.quote(str(workspace / script_rel))}"
    return f"{cmd} {arg}" if arg else cmd


def _is_ours(command: object, script_rel: str) -> bool:
    return isinstance(command, str) and ("/" + script_rel) in command


def _wire_event(hooks: dict, event: str, matcher: str, want: str) -> str | None:
    """Make `event` carry exactly one Memnyx entry whose command is `want`.

    Returns a description of the change, or None when nothing changed.
    """
    groups = hooks.setdefault(event, [])
    if not isinstance(groups, list):
        return f"skipped hooks.{event}: not a list, left as is"
    found = False
    for group in groups:
        if not isinstance(group, dict):
            continue
        for h in group.get("hooks") or []:
            if isinstance(h, dict) and _is_ours(h.get("command"), COMPACTION_SCRIPT_REL):
                found = True
                if h.get("command") != want:
                    h["command"] = want
                    return f"re-pointed hooks.{event} to {want}"
    if found:
        return None
    groups.append({
        "matcher": matcher,
        "hooks": [{"type": "command", "command": want, "timeout": TIMEOUT_SECONDS}],
    })
    return f"added hooks.{event} ({want})"


def wire_settings(workspace: Path, apply: bool) -> list[str]:
    """Plan (apply=False) or make (apply=True) the settings changes.

    Returns one human-readable line per action or notice. Never raises on a
    malformed settings file: it reports and touches nothing.
    """
    actions: list[str] = []
    path = workspace / SETTINGS_REL
    if path.is_symlink():
        return [f"skipped {SETTINGS_REL}: it is a symlink; wire the hooks by hand"]
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            return [f"skipped {SETTINGS_REL}: not readable as JSON ({e.__class__.__name__}); nothing changed"]
        if not isinstance(data, dict):
            return [f"skipped {SETTINGS_REL}: top level is not an object; nothing changed"]
    else:
        data = {}

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return [f"skipped {SETTINGS_REL}: `hooks` is not an object; nothing changed"]

    for event, matcher, arg in HOOK_EVENTS:
        change = _wire_event(hooks, event, matcher, _command(workspace, COMPACTION_SCRIPT_REL, arg))
        if change:
            actions.append(change)

    want_status = _command(workspace, STATUSLINE_SCRIPT_REL)
    status = data.get("statusLine")
    if status is None:
        data["statusLine"] = {"type": "command", "command": want_status}
        actions.append(f"added statusLine (context gauge, {want_status})")
    elif isinstance(status, dict) and _is_ours(status.get("command"), STATUSLINE_SCRIPT_REL):
        if status.get("command") != want_status:
            status["command"] = want_status
            actions.append(f"re-pointed statusLine to {want_status}")
    else:
        actions.append(
            "kept your statusLine; for the context gauge, set its command to: " + want_status
        )

    if apply and any(not a.startswith("kept ") for a in actions):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")

    actions.extend(_local_duplicates(workspace))
    return actions


def _local_duplicates(workspace: Path) -> list[str]:
    """Warn when settings.local.json also runs a compaction.sh: both would fire."""
    path = workspace / LOCAL_SETTINGS_REL
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
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
