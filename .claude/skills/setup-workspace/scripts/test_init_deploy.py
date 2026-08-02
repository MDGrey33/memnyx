"""Subprocess tests for init.py's fork-overlay deploy path (deploy_fork_overlay).

Run with:
    uv run --with pytest pytest scripts/test_init_deploy.py -v

init.py's deploy functions read module-level globals set by main(), so they are
driven as a real CLI process (mirroring test_add_project.py) rather than imported.
Each test builds a faithful source — the repo's actual `.claude` tree copied into
a tmp dir, made a git repo with a chosen origin, optionally carrying a repo-root
CLAUDE.fork.md — then runs init against a fresh sibling workspace and asserts on
the files init produced. Covers the path the resolver change rewired end-to-end:
a fork's repo-root overlay is deployed (not the stub), the base gains the
`@`-include, deploy is deploy-if-missing, and a canonical source gets no overlay.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REAL_CLAUDE = SCRIPTS_DIR.parents[2]          # <repo>/.claude
INIT_REL = ".claude/skills/setup-workspace/scripts/init.py"

sys.path.insert(0, str(SCRIPTS_DIR))
from _common import CANONICAL_REPO  # noqa: E402

CANONICAL_ORIGIN = f"https://github.com/{CANONICAL_REPO}.git"
FORK_ORIGIN = "https://github.com/someorg/some-fork.git"

FORK_BODY = "# Some Fork — fork overlay\n\n## Fork Skills\n\n| `/foo` | does foo |\n"


def build_source(tmp_path: Path, origin: str, repo_root_overlay: str | None) -> Path:
    """A faithful boilerplate source: the real .claude tree + a git origin, and
    optionally a repo-root CLAUDE.fork.md."""
    src = tmp_path / "src"
    shutil.copytree(REAL_CLAUDE, src / ".claude")
    subprocess.run(["git", "init", "-q", str(src)], check=True)
    subprocess.run(["git", "-C", str(src), "remote", "add", "origin", origin], check=True)
    if repo_root_overlay is not None:
        (src / "CLAUDE.fork.md").write_text(repo_root_overlay, encoding="utf-8")
    return src


def run_init(src: Path, ws: Path) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        [sys.executable, str(src / INIT_REL), "--workspace", str(ws), "--source", str(src)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"init failed:\n{proc.stdout}\n{proc.stderr}"
    return proc


def test_fork_deploys_repo_root_overlay_and_wires_include(tmp_path):
    src = build_source(tmp_path, FORK_ORIGIN, repo_root_overlay=FORK_BODY)
    ws = tmp_path / "ws"
    run_init(src, ws)
    # the workspace overlay is the fork's repo-root content, NOT the '<Your Fork>' stub
    assert (ws / "CLAUDE.fork.md").read_text(encoding="utf-8") == FORK_BODY
    # base wires the include; local is seeded
    assert "@CLAUDE.fork.md" in (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert (ws / "CLAUDE.local.md").is_file()


def test_fork_deploy_is_idempotent_deploy_if_missing(tmp_path):
    src = build_source(tmp_path, FORK_ORIGIN, repo_root_overlay=FORK_BODY)
    ws = tmp_path / "ws"
    run_init(src, ws)
    # a user tweak to the workspace copy must survive a second init (deploy-if-missing)
    (ws / "CLAUDE.fork.md").write_text(FORK_BODY + "\nlocal tweak\n", encoding="utf-8")
    proc = run_init(src, ws)
    assert "CLAUDE.fork.md (exists)" in proc.stdout
    assert (ws / "CLAUDE.fork.md").read_text(encoding="utf-8").endswith("local tweak\n")


def test_canonical_source_deploys_no_overlay(tmp_path):
    src = build_source(tmp_path, CANONICAL_ORIGIN, repo_root_overlay=None)
    ws = tmp_path / "ws"
    run_init(src, ws)
    assert not (ws / "CLAUDE.fork.md").exists()
    assert "@CLAUDE.fork.md" not in (ws / "CLAUDE.md").read_text(encoding="utf-8")
