"""Subprocess tests for the generated `mmn` launcher (shell/memnyx.sh).

Run with:
    uv run --with pytest pytest scripts/test_launcher.py -v

The launcher is a file that real shells `source`, so these tests source it in
real shells (bash, zsh, dash, ksh when installed) rather than reading its text.

What they protect: the generated file must keep working when the workspace
folder is at a different absolute path than the one it was generated at (a
second machine, a different user name). bash, zsh and ksh93 can say where a
sourced file lives, so they follow the file. dash cannot, so it keeps the path
baked in at generation time. Both behaviours are asserted, so a change that
silently breaks either one fails here.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
import launcher  # noqa: E402

def _is_ksh93() -> bool:
    """True only for a ksh that has ${.sh.version} (AT&T ksh93). mksh and pdksh
    set KSH_VERSION too, but cannot say where a sourced file lives."""
    exe = shutil.which("ksh")
    if not exe:
        return False
    r = subprocess.run([exe, "-c", 'echo "${.sh.version}"'], capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() != ""


SELF_LOCATING = [s for s in ("bash", "zsh") if shutil.which(s)] + (["ksh"] if _is_ksh93() else [])
BAKED_ONLY = [s for s in ("dash",) if shutil.which(s)] + (
    ["ksh"] if shutil.which("ksh") and not _is_ksh93() else [])
BASH_ONLY = [s for s in ("bash",) if shutil.which(s)]
ALL_SHELLS = SELF_LOCATING + BAKED_ONLY

PRINT_WS = '. "$1"; printf %s "$MEMNYX_WORKSPACE"'


def make_workspace(parent: Path, name: str = "ws") -> Path:
    """A minimal workspace with a generated launcher; returns its resolved path."""
    ws = (parent / name)
    (ws / ".claude").mkdir(parents=True)
    (ws / ".claude" / ".workspace").write_text("")
    (ws / "projects" / "demo").mkdir(parents=True)
    ws = ws.resolve()
    launcher.write_memnyx_sh(ws, dry_run=False)
    return ws


def run_sh(shell: str, script: str, *args: str, cwd: Path | None = None,
           path_prefix: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        [shutil.which(shell), "-c", script, "_", *args],
        capture_output=True, text=True, env=env, cwd=cwd, timeout=30,
    )


@pytest.fixture(autouse=True)
def user_config(tmp_path: Path, monkeypatch) -> Path:
    """An empty folder standing in for ~/.claude. The launcher reads the user's
    settings to see whether a status line is set; it must never read the real ones."""
    d = tmp_path / "user-config"
    d.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(d))
    return d


def sourced_workspace(shell: str, file: Path, cwd: Path | None = None) -> str:
    r = run_sh(shell, PRINT_WS, str(file), cwd=cwd)
    assert r.returncode == 0, f"{shell} failed: {r.stderr}"
    return r.stdout


def relocate(ws: Path, dest_parent: Path, name: str = "moved") -> Path:
    """Simulate pulling the workspace onto another machine: new absolute path,
    old path gone."""
    dest = dest_parent / name
    shutil.copytree(ws, dest)
    shutil.rmtree(ws)
    return dest.resolve()


@pytest.fixture
def fake_claude(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    exe = bin_dir / "claude"
    exe.write_text('#!/bin/sh\necho "FAKE-CLAUDE cwd=$(pwd -P) args=$*"\n')
    exe.chmod(0o755)
    return bin_dir


@pytest.mark.parametrize("shell", ALL_SHELLS)
def test_same_place_resolves_to_the_workspace(shell, tmp_path):
    ws = make_workspace(tmp_path)
    assert sourced_workspace(shell, ws / "shell" / "memnyx.sh") == str(ws)


@pytest.mark.parametrize("shell", SELF_LOCATING)
def test_relocated_workspace_follows_the_file(shell, tmp_path):
    ws = make_workspace(tmp_path / "machine-a")
    dest_parent = tmp_path / "machine-b"
    dest_parent.mkdir()
    new_ws = relocate(ws, dest_parent)
    assert not ws.exists()
    assert sourced_workspace(shell, new_ws / "shell" / "memnyx.sh") == str(new_ws)


@pytest.mark.parametrize("shell", BAKED_ONLY)
def test_shells_that_cannot_locate_the_file_keep_the_baked_path(shell, tmp_path):
    ws = make_workspace(tmp_path / "machine-a")
    dest_parent = tmp_path / "machine-b"
    dest_parent.mkdir()
    new_ws = relocate(ws, dest_parent)
    # Documented limit: dash has no way to find a sourced file.
    assert sourced_workspace(shell, new_ws / "shell" / "memnyx.sh") == str(ws)


@pytest.mark.parametrize("shell", SELF_LOCATING)
def test_relative_source_paths_from_other_folders(shell, tmp_path):
    # The workspace must have moved: on an unmoved one the baked path equals the
    # real one and this test would pass with no self-location code at all.
    ws = make_workspace(tmp_path / "machine-a")
    dest_parent = tmp_path / "machine-b"
    dest_parent.mkdir()
    new_ws = relocate(ws, dest_parent)
    r1 = run_sh(shell, '. ./memnyx.sh; printf %s "$MEMNYX_WORKSPACE"', cwd=new_ws / "shell")
    r2 = run_sh(shell, '. ../../shell/memnyx.sh; printf %s "$MEMNYX_WORKSPACE"',
                cwd=new_ws / "projects" / "demo")
    assert (r1.returncode, r1.stdout) == (0, str(new_ws)), r1.stderr
    assert (r2.returncode, r2.stdout) == (0, str(new_ws)), r2.stderr


@pytest.mark.parametrize("shell", SELF_LOCATING)
def test_workspace_path_with_spaces(shell, tmp_path):
    # Moved into a path with spaces: an unquoted expansion in the template would
    # make `cd` fail quietly and fall back to the old baked path.
    ws = make_workspace(tmp_path / "my work space", "the ws")
    dest_parent = tmp_path / "other machine"
    dest_parent.mkdir()
    new_ws = relocate(ws, dest_parent, "new ws")
    assert sourced_workspace(shell, new_ws / "shell" / "memnyx.sh") == str(new_ws)


@pytest.mark.parametrize("shell", BAKED_ONLY)
def test_baked_path_survives_space_and_quote(shell, tmp_path):
    ws = make_workspace(tmp_path / "it's a folder", "w s")
    assert sourced_workspace(shell, ws / "shell" / "memnyx.sh") == str(ws)


@pytest.mark.parametrize("shell", SELF_LOCATING)
def test_file_outside_any_workspace_falls_back_to_the_baked_path(shell, tmp_path):
    ws = make_workspace(tmp_path / "machine-a")
    loose = tmp_path / "loose"
    loose.mkdir()
    copy = loose / "memnyx.sh"
    shutil.copy(ws / "shell" / "memnyx.sh", copy)
    # No .claude/.workspace above the copy, so it must NOT guess a folder.
    assert sourced_workspace(shell, copy) == str(ws)


@pytest.mark.parametrize("shell", SELF_LOCATING)
def test_sourcing_leaves_no_helper_variables_behind(shell, tmp_path):
    ws = make_workspace(tmp_path)
    r = run_sh(
        shell,
        '. "$1"; for v in _mmn_self _mmn_found _mmn_baked_ws; do '
        'eval "[ -n \\"\\${$v+set}\\" ]" && echo "LEAK:$v"; done; echo done',
        str(ws / "shell" / "memnyx.sh"),
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["done"]


@pytest.mark.parametrize("shell", SELF_LOCATING)
def test_mmn_opens_a_project_after_the_workspace_moved(shell, tmp_path, fake_claude):
    ws = make_workspace(tmp_path / "machine-a")
    dest_parent = tmp_path / "machine-b"
    dest_parent.mkdir()
    new_ws = relocate(ws, dest_parent)
    r = run_sh(shell, '. "$1"; mmn demo', str(new_ws / "shell" / "memnyx.sh"),
               path_prefix=fake_claude)
    assert r.returncode == 0, r.stderr
    line = next(l for l in r.stdout.splitlines() if l.startswith("FAKE-CLAUDE"))
    assert f"cwd={new_ws / 'projects' / 'demo'}" in line
    assert f"--add-dir {new_ws}" in line


@pytest.mark.parametrize("shell", SELF_LOCATING)
def test_mmn_still_refuses_unknown_and_path_like_slugs(shell, tmp_path, fake_claude):
    ws = make_workspace(tmp_path)
    for slug in ("nope", "../x", "a/b", "..", "../shell", "demo/.."):
        r = run_sh(shell, '. "$1"; mmn "$2"', str(ws / "shell" / "memnyx.sh"), slug,
                   path_prefix=fake_claude)
        assert r.returncode != 0, f"{slug!r} should be refused"
        assert "FAKE-CLAUDE" not in r.stdout


@pytest.mark.parametrize("shell", SELF_LOCATING)
def test_cdpath_does_not_break_a_relative_source(shell, tmp_path):
    # The workspace must have MOVED: if the launcher falls back to the baked
    # path it would print the old location, which differs from the real one. On
    # an unmoved workspace baked and real are equal and this test cannot fail.
    ws = make_workspace(tmp_path / "machine-a")
    dest_parent = tmp_path / "machine-b"
    dest_parent.mkdir()
    new_ws = relocate(ws, dest_parent)
    script = f'CDPATH=.:{dest_parent}; export CDPATH; . shell/memnyx.sh; printf %s "$MEMNYX_WORKSPACE"'
    r = run_sh(shell, script, cwd=new_ws)
    assert (r.returncode, r.stdout) == (0, str(new_ws)), r.stderr


@pytest.mark.parametrize("shell", BAKED_ONLY)
def test_mmn_names_the_missing_workspace_instead_of_blaming_the_slug(
        shell, tmp_path, fake_claude):
    ws = make_workspace(tmp_path / "machine-a")
    dest_parent = tmp_path / "machine-b"
    dest_parent.mkdir()
    new_ws = relocate(ws, dest_parent)
    r = run_sh(shell, '. "$1"; mmn demo', str(new_ws / "shell" / "memnyx.sh"),
               path_prefix=fake_claude)
    assert r.returncode != 0
    assert "FAKE-CLAUDE" not in r.stdout
    assert "workspace folder" in r.stderr and str(ws) in r.stderr
    assert "not a registered project" not in r.stderr


@pytest.mark.parametrize("shell", BASH_ONLY)
def test_bare_file_name_found_in_the_current_folder(shell, tmp_path):
    # bash looks in the current folder for `. memnyx.sh`; the file then reports a
    # bare name. zsh and ksh do not search the current folder, so they never get here.
    ws = make_workspace(tmp_path / "machine-a")
    dest_parent = tmp_path / "machine-b"
    dest_parent.mkdir()
    new_ws = relocate(ws, dest_parent)
    r = run_sh(shell, '. memnyx.sh; printf %s "$MEMNYX_WORKSPACE"', cwd=new_ws / "shell")
    assert (r.returncode, r.stdout) == (0, str(new_ws)), r.stderr


@pytest.mark.parametrize("shell", BAKED_ONLY)
def test_a_shell_that_sets_ksh_version_without_sh_file_still_sources(shell, tmp_path):
    # Stand-in for mksh and pdksh: KSH_VERSION is set but ${.sh.file} does not
    # exist. Sourcing must neither exit the shell nor stop before `mmn` is defined.
    ws = make_workspace(tmp_path / "machine-a")
    dest_parent = tmp_path / "machine-b"
    dest_parent.mkdir()
    new_ws = relocate(ws, dest_parent)
    script = ('KSH_VERSION="@(#)MIRBSD KSH R59"; export KSH_VERSION; . "$1"; '
              'printf %s "$MEMNYX_WORKSPACE"; type mmn >/dev/null 2>&1 && printf " mmn-defined"')
    r = run_sh(shell, script, str(new_ws / "shell" / "memnyx.sh"))
    assert (r.returncode, r.stdout) == (0, f"{ws} mmn-defined"), r.stderr


@pytest.mark.parametrize("args", [(), ("-p", "hi")])
@pytest.mark.parametrize("shell", BAKED_ONLY)
def test_mmn_warns_but_still_launches_in_the_current_folder_when_the_workspace_is_gone(
        shell, args, tmp_path, fake_claude):
    ws = make_workspace(tmp_path / "machine-a")
    dest_parent = tmp_path / "machine-b"
    dest_parent.mkdir()
    new_ws = relocate(ws, dest_parent)
    r = run_sh(shell, '. "$1"; shift; mmn "$@"', str(new_ws / "shell" / "memnyx.sh"), *args,
               path_prefix=fake_claude)
    assert r.returncode == 0, r.stderr
    assert "FAKE-CLAUDE" in r.stdout
    assert "workspace folder" in r.stderr and str(ws) in r.stderr


# --- compaction-safeguard hooks outside the workspace root -----------------------
#
# Claude Code loads the workspace's settings.json (where the hooks are wired) only
# when it starts at the workspace root. Elsewhere mmn must pass the hooks itself
# with --settings, and at the root it must not, or they fire twice.

import json  # noqa: E402

HOOKS_REL = Path(".claude/hooks/memnyx/compaction.sh")


@pytest.fixture
def recording_claude(tmp_path: Path) -> Path:
    """A fake claude that records cwd, MEMNYX_WORKSPACE and each argument."""
    bin_dir = tmp_path / "recbin"
    bin_dir.mkdir()
    exe = bin_dir / "claude"
    exe.write_text(
        '#!/bin/sh\n'
        'out="$MMN_TEST_RECORD"\n'
        '{ printf "cwd=%s\\n" "$(pwd -P)"; printf "ws=%s\\n" "$MEMNYX_WORKSPACE";\n'
        '  for a in "$@"; do printf "arg=%s\\n" "$a"; done; } > "$out"\n'
    )
    exe.chmod(0o755)
    return bin_dir


def with_hook_script(ws: Path) -> None:
    script = ws / HOOKS_REL
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text('echo "HOOK ran in $(cd "$(dirname "$0")/../../.." && pwd -P) mode=$1"\n')


def launch(shell: str, ws: Path, command: str, bin_dir: Path, tmp_path: Path,
           cwd: Path | None = None, setup: str = "") -> tuple[subprocess.CompletedProcess, dict]:
    """`setup` runs on its own lines before sourcing: an alias takes effect only
    on lines read after it is defined."""
    record = tmp_path / "record.txt"
    env_script = f'MMN_TEST_RECORD="{record}"; export MMN_TEST_RECORD\n{setup}\n. "$1"; {command}'
    r = run_sh(shell, env_script, str(ws / "shell" / "memnyx.sh"), cwd=cwd, path_prefix=bin_dir)
    assert r.returncode == 0, r.stderr
    lines = record.read_text().splitlines()
    rec = {"cwd": lines[0][4:], "ws": lines[1][3:], "args": [l[4:] for l in lines[2:]]}
    return r, rec


def settings_arg(args: list[str]) -> dict | None:
    if "--settings" not in args:
        return None
    return json.loads(args[args.index("--settings") + 1])


@pytest.mark.parametrize("shell", ALL_SHELLS)
def test_mmn_passes_the_hooks_when_opening_a_project(shell, tmp_path, recording_claude):
    ws = make_workspace(tmp_path)
    with_hook_script(ws)
    r, rec = launch(shell, ws, "mmn demo", recording_claude, tmp_path)
    s = settings_arg(rec["args"])
    assert s is not None and set(s) == {"hooks"}          # no statusline.sh here, so no gauge
    assert {e: [g["matcher"] for g in s["hooks"][e]] for e in s["hooks"]} == {
        "PreCompact": ["*"], "PostCompact": ["*"], "SessionStart": ["compact"]}
    assert rec["ws"] == str(ws)
    assert str(ws) not in json.dumps(s)                    # no machine path in the JSON
    assert "compaction safeguard added with --settings" in r.stdout
    assert "--settings <compaction hooks>" in r.stdout
    # The commands, run as Claude Code would (env inherited), reach the workspace's script.
    for event, mode in (("PreCompact", "pre"), ("PostCompact", "post"), ("SessionStart", "resume")):
        cmd = s["hooks"][event][0]["hooks"][0]["command"]
        out = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True,
                             env={**os.environ, "MEMNYX_WORKSPACE": rec["ws"]}, cwd=rec["cwd"])
        assert out.stdout.strip() == f"HOOK ran in {ws} mode={mode}", out.stderr


@pytest.mark.parametrize("shell", ALL_SHELLS)
def test_mmn_adds_nothing_at_the_workspace_root(shell, tmp_path, recording_claude):
    ws = make_workspace(tmp_path)
    with_hook_script(ws)
    r, rec = launch(shell, ws, "mmn", recording_claude, tmp_path, cwd=ws)
    assert rec["cwd"] == str(ws)
    assert "--settings" not in rec["args"]
    assert "compaction safeguard added" not in r.stdout


@pytest.mark.parametrize("shell", ALL_SHELLS)
def test_mmn_passes_the_hooks_in_a_subfolder_of_the_workspace(shell, tmp_path, recording_claude):
    ws = make_workspace(tmp_path)
    with_hook_script(ws)
    sub = ws / "notes"
    sub.mkdir()
    _, rec = launch(shell, ws, "mmn", recording_claude, tmp_path, cwd=sub)
    assert settings_arg(rec["args"]) is not None


@pytest.mark.parametrize("shell", ALL_SHELLS)
def test_mmn_adds_nothing_when_the_hook_scripts_are_absent(shell, tmp_path, recording_claude):
    ws = make_workspace(tmp_path)                          # no .claude/hooks/memnyx/
    _, rec = launch(shell, ws, "mmn demo", recording_claude, tmp_path)
    assert "--settings" not in rec["args"]


@pytest.mark.parametrize("shell", SELF_LOCATING)
def test_mmn_hooks_work_from_a_workspace_path_with_spaces_and_quotes(shell, tmp_path, recording_claude):
    ws = make_workspace(tmp_path, name="my 'odd' ws")
    with_hook_script(ws)
    _, rec = launch(shell, ws, "mmn demo", recording_claude, tmp_path)
    cmd = settings_arg(rec["args"])["hooks"]["PreCompact"][0]["hooks"][0]["command"]
    out = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True,
                         env={**os.environ, "MEMNYX_WORKSPACE": rec["ws"]}, cwd=rec["cwd"])
    assert out.stdout.strip() == f"HOOK ran in {ws} mode=pre", out.stderr


@pytest.mark.parametrize("shell", ALL_SHELLS)
def test_user_flags_still_pass_through_with_the_hooks(shell, tmp_path, recording_claude):
    ws = make_workspace(tmp_path)
    with_hook_script(ws)
    _, rec = launch(shell, ws, "mmn demo --model haiku", recording_claude, tmp_path)
    assert rec["args"][-2:] == ["--model", "haiku"]
    assert rec["args"][:2] == ["--add-dir", str(ws)]


# A `cd` that prints. Omarchy aliases `cd` to `zd`, which prints an icon line and
# the path when given `--`; other setups define `cd() { builtin cd "$@" && ls; }`.
# The launcher captures `$(cd … && pwd -P)`, so any output from `cd` lands in the
# captured path and the check that follows fails without a word. Each test sets
# the noisy `cd` up before the launcher is sourced, as a shell profile would.
NOISY_CD_FUNCTION = 'cd() { command cd "$@" && echo "NOISE from cd"; }'
# zsh's `command` looks only for external programs, so its version uses `builtin`.
NOISY_CD_ALIAS = {
    "bash": 'shopt -s expand_aliases\n_noisy_cd() { builtin cd "$@" && echo "NOISE from cd"; }\nalias cd=_noisy_cd\n',
    "zsh": '_noisy_cd() { builtin cd "$@" && echo "NOISE from cd"; }\nalias cd=_noisy_cd\n',
}
ALIAS_SHELLS = [s for s in NOISY_CD_ALIAS if shutil.which(s)]


def noisy_cd_cases():
    cases = [pytest.param(s, NOISY_CD_FUNCTION.replace("command cd", "builtin cd")
                          if s == "zsh" else NOISY_CD_FUNCTION, id=f"{s}-function")
             for s in ALL_SHELLS]
    cases += [pytest.param(s, NOISY_CD_ALIAS[s], id=f"{s}-alias") for s in ALIAS_SHELLS]
    return cases


@pytest.mark.parametrize("shell,setup", noisy_cd_cases())
def test_a_noisy_cd_does_not_drop_the_hooks_or_the_project(shell, setup, tmp_path, recording_claude):
    ws = make_workspace(tmp_path)
    with_hook_script(ws)
    _, rec = launch(shell, ws, "mmn demo", recording_claude, tmp_path, setup=setup)
    assert rec["cwd"] == str(ws / "projects" / "demo")
    assert settings_arg(rec["args"]) is not None


@pytest.mark.parametrize("shell,setup",
                         [p for p in noisy_cd_cases() if p.values[0] in SELF_LOCATING])
def test_a_noisy_cd_does_not_stop_a_moved_workspace_finding_itself(shell, setup, tmp_path):
    ws = make_workspace(tmp_path / "machine-a")
    dest_parent = tmp_path / "machine-b"
    dest_parent.mkdir()
    new_ws = relocate(ws, dest_parent)
    r = run_sh(shell, f'{setup}\n. "$1"\nprintf %s "$MEMNYX_WORKSPACE"\n',
               str(new_ws / "shell" / "memnyx.sh"))
    assert r.returncode == 0, r.stderr
    assert r.stdout == str(new_ws)


@pytest.mark.parametrize("shell,setup", [p for p in noisy_cd_cases() if p.values[0] == "bash"])
def test_a_noisy_cd_does_not_stop_a_bare_file_name_finding_itself(shell, setup, tmp_path):
    # Same as test_bare_file_name_found_in_the_current_folder, with a noisy cd.
    ws = make_workspace(tmp_path / "machine-a")
    dest_parent = tmp_path / "machine-b"
    dest_parent.mkdir()
    new_ws = relocate(ws, dest_parent)
    r = run_sh(shell, f'{setup}\n. memnyx.sh\nprintf %s "$MEMNYX_WORKSPACE"\n', cwd=new_ws / "shell")
    assert (r.returncode, r.stdout) == (0, str(new_ws)), r.stderr


# An alias that goes to the wrong folder. Dropping output cannot hide this; only
# skipping the alias (the backslash in `\cd`) does.
WRONG_FOLDER_ALIAS = {
    "bash": 'shopt -s expand_aliases\n_wrong_cd() { builtin cd /; }\nalias cd=_wrong_cd\n',
    "zsh": '_wrong_cd() { builtin cd /; }\nalias cd=_wrong_cd\n',
}


@pytest.mark.parametrize("shell", [s for s in WRONG_FOLDER_ALIAS if shutil.which(s)])
def test_a_cd_alias_is_skipped(shell, tmp_path, recording_claude):
    ws = make_workspace(tmp_path)
    with_hook_script(ws)
    _, rec = launch(shell, ws, "mmn demo", recording_claude, tmp_path, setup=WRONG_FOLDER_ALIAS[shell])
    assert rec["cwd"] == str(ws / "projects" / "demo")
    assert settings_arg(rec["args"]) is not None



def with_statusline_script(ws: Path) -> None:
    script = ws / ".claude/hooks/memnyx/statusline.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text('echo "GAUGE from $(cd "$(dirname "$0")/../../.." && pwd -P)"\n')


@pytest.mark.parametrize("shell", ALL_SHELLS)
def test_mmn_adds_the_gauge_when_no_status_line_is_set(shell, tmp_path, recording_claude):
    ws = make_workspace(tmp_path)
    with_hook_script(ws)
    with_statusline_script(ws)
    r, rec = launch(shell, ws, "mmn demo", recording_claude, tmp_path)
    cmd = settings_arg(rec["args"])["statusLine"]["command"]
    assert str(ws) not in cmd                              # no machine path in the JSON
    out = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True,
                         env={**os.environ, "MEMNYX_WORKSPACE": rec["ws"]}, cwd=rec["cwd"])
    assert out.stdout.strip() == f"GAUGE from {ws}", out.stderr
    assert "context gauge added too" in r.stdout


def _status_line_in(where: str, ws: Path, user_config: Path) -> None:
    files = {
        "user": user_config / "settings.json",
        "project": ws / "projects/demo/.claude/settings.json",
        "project-local": ws / "projects/demo/.claude/settings.local.json",
    }
    files[where].parent.mkdir(parents=True, exist_ok=True)
    files[where].write_text('{\n  "statusLine": {"type": "command", "command": "mine.sh"}\n}\n')


@pytest.mark.parametrize("where", ["user", "project", "project-local"])
@pytest.mark.parametrize("shell", ALL_SHELLS)
def test_mmn_keeps_a_status_line_set_elsewhere(shell, where, tmp_path, recording_claude, user_config):
    ws = make_workspace(tmp_path)
    with_hook_script(ws)
    with_statusline_script(ws)
    _status_line_in(where, ws, user_config)
    r, rec = launch(shell, ws, "mmn demo", recording_claude, tmp_path)
    s = settings_arg(rec["args"])
    assert s is not None and set(s) == {"hooks"}           # hooks still added
    assert "context gauge added" not in r.stdout


@pytest.mark.parametrize("shell", ALL_SHELLS)
def test_mmn_adds_no_gauge_when_its_script_is_absent(shell, tmp_path, recording_claude):
    ws = make_workspace(tmp_path)
    with_hook_script(ws)                                   # no statusline.sh
    _, rec = launch(shell, ws, "mmn demo", recording_claude, tmp_path)
    assert set(settings_arg(rec["args"])) == {"hooks"}
