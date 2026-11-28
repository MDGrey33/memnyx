"""Tests for the compaction-safeguard wiring (_hooks.py) and the hook script.

Run with:
    uv run --with pytest pytest scripts/test_hooks.py -v

Unit tests drive `_hooks.wire_settings` against a tmp workspace. The
integration tests run the real init.py and sync.py as subprocesses (mirroring
test_init_deploy.py) and then run the deployed compaction.sh against session
markers, so the path from setup to a matched marker is exercised end to end.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REAL_CLAUDE = SCRIPTS_DIR.parents[2]          # <repo>/.claude
INIT_REL = ".claude/skills/setup-workspace/scripts/init.py"
SYNC_REL = ".claude/skills/setup-workspace/scripts/sync.py"

sys.path.insert(0, str(SCRIPTS_DIR))
import _hooks  # noqa: E402
from _common import CANONICAL_REPO  # noqa: E402

EVENTS = [e for e, _, _ in _hooks.HOOK_EVENTS]


def settings(ws: Path) -> dict:
    return json.loads((ws / _hooks.SETTINGS_REL).read_text())


def ours(data: dict, event: str) -> list[str]:
    return [
        h["command"]
        for g in data.get("hooks", {}).get(event, [])
        for h in g.get("hooks", [])
        if "/.claude/hooks/compaction.sh" in h.get("command", "")
    ]


def make_ws(tmp_path: Path, content: dict | str | None = None) -> Path:
    ws = tmp_path / "ws"
    (ws / ".claude").mkdir(parents=True)
    (ws / ".claude/.workspace").touch()
    if content is not None:
        text = content if isinstance(content, str) else json.dumps(content)
        (ws / _hooks.SETTINGS_REL).write_text(text)
    return ws


# --- unit: wire_settings -------------------------------------------------------

def test_fresh_settings_gets_three_hooks_and_status_line(tmp_path):
    ws = make_ws(tmp_path, {"permissions": {"allow": ["Read"]}})
    _hooks.wire_settings(ws, apply=True)
    data = settings(ws)
    for event, arg in [("PreCompact", "pre"), ("PostCompact", "post"), ("SessionStart", "resume")]:
        cmds = ours(data, event)
        assert len(cmds) == 1 and cmds[0].endswith(f"compaction.sh {arg}")
        assert str(ws) in cmds[0]
    assert data["hooks"]["SessionStart"][0]["matcher"] == "compact"
    assert data["statusLine"]["command"].endswith("/.claude/hooks/statusline.sh")
    assert data["permissions"] == {"allow": ["Read"]}


def test_missing_settings_file_is_created(tmp_path):
    ws = make_ws(tmp_path)
    _hooks.wire_settings(ws, apply=True)
    assert all(len(ours(settings(ws), e)) == 1 for e in EVENTS)


def test_second_run_changes_nothing(tmp_path):
    ws = make_ws(tmp_path, {})
    _hooks.wire_settings(ws, apply=True)
    before = (ws / _hooks.SETTINGS_REL).read_bytes()
    actions = _hooks.wire_settings(ws, apply=True)
    assert actions == []
    assert (ws / _hooks.SETTINGS_REL).read_bytes() == before


def test_plan_mode_writes_nothing(tmp_path):
    ws = make_ws(tmp_path, {"permissions": {}})
    before = (ws / _hooks.SETTINGS_REL).read_bytes()
    actions = _hooks.wire_settings(ws, apply=False)
    assert any(a.startswith("added hooks.PreCompact") for a in actions)
    assert (ws / _hooks.SETTINGS_REL).read_bytes() == before


def test_user_hooks_and_status_line_are_kept(tmp_path):
    user_hook = {"matcher": "*", "hooks": [{"type": "command", "command": "echo mine"}]}
    user_status = {"type": "command", "command": "my-status"}
    ws = make_ws(tmp_path, {"hooks": {"PreCompact": [user_hook]}, "statusLine": user_status})
    actions = _hooks.wire_settings(ws, apply=True)
    data = settings(ws)
    assert data["hooks"]["PreCompact"][0] == user_hook
    assert len(ours(data, "PreCompact")) == 1
    assert data["statusLine"] == user_status
    assert any(a.startswith("kept your statusLine") for a in actions)


def test_moved_workspace_is_re_pointed_not_duplicated(tmp_path):
    old = "bash /old/place/.claude/hooks/compaction.sh pre"
    ws = make_ws(tmp_path, {
        "hooks": {"PreCompact": [{"matcher": "*", "hooks": [{"type": "command", "command": old}]}]},
        "statusLine": {"type": "command", "command": "bash /old/place/.claude/hooks/statusline.sh"},
    })
    actions = _hooks.wire_settings(ws, apply=True)
    data = settings(ws)
    cmds = ours(data, "PreCompact")
    assert len(cmds) == 1 and str(ws) in cmds[0]
    assert str(ws) in data["statusLine"]["command"]
    assert any(a.startswith("re-pointed hooks.PreCompact") for a in actions)
    assert any(a.startswith("re-pointed statusLine") for a in actions)


def test_malformed_settings_are_left_alone(tmp_path):
    ws = make_ws(tmp_path, '{"permissions": ')
    actions = _hooks.wire_settings(ws, apply=True)
    assert len(actions) == 1 and actions[0].startswith("skipped")
    assert (ws / _hooks.SETTINGS_REL).read_text() == '{"permissions": '


def test_symlinked_settings_are_refused(tmp_path):
    ws = make_ws(tmp_path)
    target = tmp_path / "elsewhere.json"
    target.write_text("{}")
    (ws / _hooks.SETTINGS_REL).symlink_to(target)
    actions = _hooks.wire_settings(ws, apply=True)
    assert actions[0].startswith("skipped") and target.read_text() == "{}"


def test_duplicate_in_local_settings_is_reported_not_edited(tmp_path):
    ws = make_ws(tmp_path, {})
    local = {"hooks": {"PreCompact": [{"hooks": [{"type": "command", "command": "bash /x/compaction.sh pre"}]}]}}
    (ws / _hooks.LOCAL_SETTINGS_REL).write_text(json.dumps(local))
    actions = _hooks.wire_settings(ws, apply=True)
    assert any(a.startswith("warning:") and "PreCompact" in a for a in actions)
    assert json.loads((ws / _hooks.LOCAL_SETTINGS_REL).read_text()) == local


# --- integration: init, sync, and the deployed script --------------------------

def build_source(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    shutil.copytree(REAL_CLAUDE, src / ".claude")
    subprocess.run(["git", "init", "-q", str(src)], check=True)
    subprocess.run(["git", "-C", str(src), "remote", "add", "origin",
                    f"https://github.com/{CANONICAL_REPO}.git"], check=True)
    return src


def run(src: Path, rel: str, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run([sys.executable, str(src / rel), *args], capture_output=True, text=True)
    assert proc.returncode == 0, f"{rel} failed:\n{proc.stdout}\n{proc.stderr}"
    return proc


def run_hook(ws: Path, mode: str, payload: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(ws / _hooks.COMPACTION_SCRIPT_REL), mode],
        input=payload, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
             "COMPACTION_LOG_DIR": str(ws.parent / "log")},
    )


def marker(ws: Path, name: str, workstream: str, cc_id: str | None) -> None:
    d = ws / "sessions/active"
    d.mkdir(parents=True, exist_ok=True)
    lines = ["---", "project_slug: workspace", f"workstream_slug: {workstream}", "open_item_slug: x"]
    if cc_id:
        lines.append(f"cc_session_id: {cc_id}")
    (d / name).write_text("\n".join(lines + ["---", ""]))


def test_init_deploys_scripts_and_wires_settings(tmp_path):
    src = build_source(tmp_path)
    ws = tmp_path / "ws"
    run(src, INIT_REL, "--workspace", str(ws), "--source", str(src))
    assert (ws / _hooks.COMPACTION_SCRIPT_REL).is_file()
    assert (ws / _hooks.STATUSLINE_SCRIPT_REL).is_file()
    data = settings(ws)
    assert all(len(ours(data, e)) == 1 for e in EVENTS)
    assert "permissions" in data  # the deployed settings.json kept its content


def test_sync_reports_then_applies_hooks_to_an_older_workspace(tmp_path):
    src = build_source(tmp_path)
    ws = tmp_path / "ws"
    run(src, INIT_REL, "--workspace", str(ws), "--source", str(src))
    # simulate a workspace set up before the safeguard existed
    shutil.rmtree(ws / ".claude/hooks")
    data = settings(ws)
    data.pop("hooks"); data.pop("statusLine")
    (ws / _hooks.SETTINGS_REL).write_text(json.dumps(data))
    before = (ws / _hooks.SETTINGS_REL).read_text()

    report = run(src, SYNC_REL, "--workspace", str(ws), "--source", str(src))
    assert "+ .claude/hooks/compaction.sh" in report.stdout
    assert "added hooks.PreCompact" in report.stdout
    assert (ws / _hooks.SETTINGS_REL).read_text() == before  # report mode wrote nothing

    run(src, SYNC_REL, "--workspace", str(ws), "--source", str(src), "--apply-all")
    assert (ws / _hooks.COMPACTION_SCRIPT_REL).is_file()
    assert all(len(ours(settings(ws), e)) == 1 for e in EVENTS)


def test_deployed_hook_lists_only_this_sessions_marker(tmp_path):
    src = build_source(tmp_path)
    ws = tmp_path / "ws"
    run(src, INIT_REL, "--workspace", str(ws), "--source", str(src))
    marker(ws, "a.md", "mine", "SESSION-A")
    marker(ws, "b.md", "other", "SESSION-B")
    marker(ws, "c.md", "old", None)

    hit = run_hook(ws, "resume", json.dumps({"session_id": "SESSION-A"}))
    assert hit.returncode == 0
    assert "This session's marker" in hit.stdout
    assert "workstream=mine" in hit.stdout
    assert "workstream=other" not in hit.stdout and "workstream=old" not in hit.stdout

    miss = run_hook(ws, "pre", json.dumps({"session_id": "SESSION-Z"}))
    assert miss.returncode == 0
    assert all(f"workstream={w}" in miss.stdout for w in ("mine", "other", "old"))

    bad = run_hook(ws, "pre", "not json")
    assert bad.returncode == 0 and "workstream=old" in bad.stdout


def test_deployed_hook_logs_under_workspace_artifacts(tmp_path):
    src = build_source(tmp_path)
    ws = tmp_path / "ws"
    run(src, INIT_REL, "--workspace", str(ws), "--source", str(src))
    proc = subprocess.run(
        ["bash", str(ws / _hooks.COMPACTION_SCRIPT_REL), "post"],
        input=json.dumps({"trigger": "auto", "session_id": "S", "compact_summary": "kept"}),
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    logs = list((ws / "artifacts/compaction-safeguard/log").glob("*-auto.md"))
    assert len(logs) == 1 and "kept" in logs[0].read_text()
