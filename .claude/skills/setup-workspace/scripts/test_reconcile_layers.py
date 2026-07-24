"""Integration tests for sync.reconcile_claude_layers fork-overlay behavior.

Run with:
    uv run --with pytest pytest scripts/test_reconcile_layers.py -v

reconcile_claude_layers takes (workspace, source, apply) explicitly (no module
globals), so it is unit-testable directly. These exercise the fork-overlay
branches the resolver change rewired — the functions that had zero coverage
before this PR: regenerate-on-apply from the repo-root file, unchanged detection,
would-overwrite planning, fork-with-no-overlay suppression, the canonical
ORPHANED path, and the unknown-origin touch-nothing guard.

Sources are real git repos (git init + remote add origin) so classify_source's
actual `git remote get-url origin` path runs. Each test uses a distinct tmp dir
(classify_source is @lru_cache'd by Path).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import sync  # noqa: E402
from _common import (  # noqa: E402
    classify_source,
    CANONICAL_REPO,
    FORK_OVERLAY_FILE_REL,
    FORK_OVERLAY_TEMPLATE_REL,
)

CANONICAL_ORIGIN = f"https://github.com/{CANONICAL_REPO}.git"
FORK_ORIGIN = "https://github.com/someorg/some-fork.git"
REAL_SW = SCRIPTS_DIR.parent  # .../setup-workspace
REAL_BASE_TMPL = REAL_SW / "templates/workspace-CLAUDE.md.tmpl"
BASE_TMPL_DEST_REL = ".claude/skills/setup-workspace/templates/workspace-CLAUDE.md.tmpl"


@pytest.fixture(autouse=True)
def _clear_classify_cache():
    classify_source.cache_clear()
    yield
    classify_source.cache_clear()


def make_source(tmp_path: Path, name: str, origin: str | None,
                repo_root_body: str | None = None, ship_stub: bool = True) -> Path:
    """A source repo with the base template (so render_base_claude_md works), a git
    origin (None = no git → 'unknown'), and optionally a repo-root CLAUDE.fork.md
    and/or the bundled stub template."""
    src = tmp_path / name
    dst_tmpl = src / BASE_TMPL_DEST_REL
    dst_tmpl.parent.mkdir(parents=True)
    dst_tmpl.write_text(REAL_BASE_TMPL.read_text(encoding="utf-8"), encoding="utf-8")
    if ship_stub:
        (src / FORK_OVERLAY_TEMPLATE_REL).write_text(
            "# <Your Fork> — fork overlay\n", encoding="utf-8"
        )
    if repo_root_body is not None:
        (src / FORK_OVERLAY_FILE_REL).write_text(repo_root_body, encoding="utf-8")
    if origin is not None:
        subprocess.run(["git", "init", "-q", str(src)], check=True)
        subprocess.run(["git", "-C", str(src), "remote", "add", "origin", origin], check=True)
    return src


def make_workspace(tmp_path: Path, fork_body: str | None = None) -> Path:
    """A workspace with a LAYERED base (carries the marker, so the guard passes) and
    an existing CLAUDE.local.md (keeps the local branch inert), optionally a
    pre-existing CLAUDE.fork.md."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "CLAUDE.md").write_text(
        "# ws\n\n## Layered overlays\n\nlayered.\n", encoding="utf-8"
    )
    (ws / "CLAUDE.local.md").write_text("# local\n", encoding="utf-8")
    if fork_body is not None:
        (ws / "CLAUDE.fork.md").write_text(fork_body, encoding="utf-8")
    return ws


def fork_line(actions: list[str]) -> str:
    """The single CLAUDE.fork.md action line (fails loudly if 0 or >1)."""
    hits = [a for a in actions if a.startswith("CLAUDE.fork.md")]
    assert len(hits) == 1, f"expected one fork action, got {hits}"
    return hits[0]


def test_fork_regenerates_from_repo_root_on_apply(tmp_path):
    src = make_source(tmp_path, "src", FORK_ORIGIN, repo_root_body="# Fork\n\nreal body\n")
    ws = make_workspace(tmp_path, fork_body="# stale\n")
    actions = sync.reconcile_claude_layers(ws, src, apply=True)
    assert "written" in fork_line(actions)
    # workspace copy now equals the fork's repo-root content (literal → render is a no-op)
    assert (ws / "CLAUDE.fork.md").read_text(encoding="utf-8") == "# Fork\n\nreal body\n"


def test_fork_unchanged_when_workspace_matches(tmp_path):
    body = "# Fork\n\nsame\n"
    src = make_source(tmp_path, "src", FORK_ORIGIN, repo_root_body=body)
    ws = make_workspace(tmp_path, fork_body=body)
    actions = sync.reconcile_claude_layers(ws, src, apply=False)
    assert "unchanged" in fork_line(actions)


def test_fork_would_overwrite_when_missing_in_plan_mode(tmp_path):
    src = make_source(tmp_path, "src", FORK_ORIGIN, repo_root_body="# Fork\n")
    ws = make_workspace(tmp_path, fork_body=None)  # no workspace overlay yet
    actions = sync.reconcile_claude_layers(ws, src, apply=False)
    line = fork_line(actions)
    assert "would overwrite" in line and "missing" in line
    assert not (ws / "CLAUDE.fork.md").exists()  # plan mode writes nothing


def test_fork_with_no_overlay_suppresses_include(tmp_path):
    # fork origin, but neither a repo-root CLAUDE.fork.md nor the stub
    src = make_source(tmp_path, "src", FORK_ORIGIN, repo_root_body=None, ship_stub=False)
    ws = make_workspace(tmp_path, fork_body=None)
    actions = sync.reconcile_claude_layers(ws, src, apply=True)
    assert "provides no overlay" in fork_line(actions)
    assert "suppressed" in fork_line(actions)


def test_canonical_with_workspace_overlay_is_orphaned(tmp_path):
    src = make_source(tmp_path, "src", CANONICAL_ORIGIN, repo_root_body=None, ship_stub=True)
    ws = make_workspace(tmp_path, fork_body="# leftover fork overlay\n")
    actions = sync.reconcile_claude_layers(ws, src, apply=True)
    assert "ORPHANED" in fork_line(actions)
    # ORPHANED never rewrites or deletes the leftover — user decides
    assert (ws / "CLAUDE.fork.md").read_text(encoding="utf-8") == "# leftover fork overlay\n"


def test_unknown_origin_touches_nothing(tmp_path):
    src = make_source(tmp_path, "src", origin=None, repo_root_body="# Fork\n")
    ws = make_workspace(tmp_path, fork_body="# untouched\n")
    actions = sync.reconcile_claude_layers(ws, src, apply=True)
    assert len(actions) == 1 and "SKIPPED" in actions[0]
    assert (ws / "CLAUDE.fork.md").read_text(encoding="utf-8") == "# untouched\n"
