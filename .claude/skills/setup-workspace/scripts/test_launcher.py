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

SELF_LOCATING = [s for s in ("bash", "zsh", "ksh") if shutil.which(s)]
BAKED_ONLY = [s for s in ("dash",) if shutil.which(s)]
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
    ws = make_workspace(tmp_path)
    r1 = run_sh(shell, '. ./memnyx.sh; printf %s "$MEMNYX_WORKSPACE"', cwd=ws / "shell")
    r2 = run_sh(shell, '. ../../shell/memnyx.sh; printf %s "$MEMNYX_WORKSPACE"',
                cwd=ws / "projects" / "demo")
    assert (r1.returncode, r1.stdout) == (0, str(ws)), r1.stderr
    assert (r2.returncode, r2.stdout) == (0, str(ws)), r2.stderr


@pytest.mark.parametrize("shell", SELF_LOCATING)
def test_workspace_path_with_spaces(shell, tmp_path):
    ws = make_workspace(tmp_path / "my work space", "the ws")
    assert sourced_workspace(shell, ws / "shell" / "memnyx.sh") == str(ws)


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
    for slug in ("nope", "../x", "a/b", ".."):
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
