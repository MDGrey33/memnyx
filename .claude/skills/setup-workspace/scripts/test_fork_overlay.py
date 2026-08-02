"""Regression tests for fork-overlay source resolution (_common.fork_overlay_source).

Run with:
    uv run --with pytest pytest scripts/test_fork_overlay.py -v

Uses real one-commit-free git repos (git init + git remote add origin) so the
tests exercise classify_source's actual `git remote get-url origin` path, not a
monkeypatched stand-in. classify_source is @lru_cache'd by Path, so every test
uses a distinct tmp source dir to avoid cross-test cache bleed.

The behaviour under test — the precedence a fork's overlay content resolves by:
repo-root CLAUDE.fork.md (the real, sync-safe home) wins; the bundled stub template
is only a bootstrap fallback; canonical/unknown sources yield no overlay.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from _common import (  # noqa: E402
    classify_source,
    fork_overlay_source,
    fork_overlay_active,
    FORK_OVERLAY_TEMPLATE_REL,
    FORK_OVERLAY_FILE_REL,
    CANONICAL_REPO,
)

CANONICAL_ORIGIN = f"https://github.com/{CANONICAL_REPO}.git"
FORK_ORIGIN = "https://github.com/someorg/some-fork.git"


def make_source(tmp_path: Path, name: str, origin: str | None) -> Path:
    """A source dir that is a git repo with the given origin (None = no git)."""
    src = tmp_path / name
    src.mkdir()
    if origin is not None:
        subprocess.run(["git", "init", "-q", str(src)], check=True)
        subprocess.run(
            ["git", "-C", str(src), "remote", "add", "origin", origin], check=True
        )
    return src


def add_repo_root_overlay(src: Path, body: str = "# Some Fork — fork overlay\n") -> Path:
    p = src / FORK_OVERLAY_FILE_REL
    p.write_text(body, encoding="utf-8")
    return p


def add_stub(src: Path, body: str = "# <Your Fork> — fork overlay\n") -> Path:
    p = src / FORK_OVERLAY_TEMPLATE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _clear_classify_cache():
    """classify_source is process-cached; clear between tests for isolation."""
    classify_source.cache_clear()
    yield
    classify_source.cache_clear()


def test_fork_repo_root_wins_over_stub(tmp_path):
    src = make_source(tmp_path, "fork_both", FORK_ORIGIN)
    repo_root = add_repo_root_overlay(src)
    add_stub(src)
    assert fork_overlay_source(src) == repo_root
    assert fork_overlay_active(src) is True


def test_fork_stub_is_fallback_when_no_repo_root(tmp_path):
    src = make_source(tmp_path, "fork_stub_only", FORK_ORIGIN)
    stub = add_stub(src)
    assert fork_overlay_source(src) == stub
    assert fork_overlay_active(src) is True


def test_fork_repo_root_only(tmp_path):
    src = make_source(tmp_path, "fork_root_only", FORK_ORIGIN)
    repo_root = add_repo_root_overlay(src)
    assert fork_overlay_source(src) == repo_root
    assert fork_overlay_active(src) is True


def test_fork_with_no_overlay_is_none(tmp_path):
    src = make_source(tmp_path, "fork_bare", FORK_ORIGIN)
    assert fork_overlay_source(src) is None
    assert fork_overlay_active(src) is False


def test_canonical_never_resolves_even_with_repo_root_file(tmp_path):
    # A canonical source may itself have a CLAUDE.fork.md-looking file; it must be
    # ignored — canonical Memnyx ships no fork overlay.
    src = make_source(tmp_path, "canonical", CANONICAL_ORIGIN)
    add_repo_root_overlay(src)
    add_stub(src)
    assert fork_overlay_source(src) is None
    assert fork_overlay_active(src) is False


def test_unknown_origin_never_resolves(tmp_path):
    # No git repo → classify_source == 'unknown' → no overlay (never guess fork).
    src = make_source(tmp_path, "no_git", origin=None)
    add_repo_root_overlay(src)
    add_stub(src)
    assert fork_overlay_source(src) is None
    assert fork_overlay_active(src) is False


def test_git_repo_without_origin_is_unknown(tmp_path):
    # A git repo that has no `origin` remote → `git remote get-url origin` fails
    # → 'unknown' (distinct code path from no-git-at-all). Must not resolve.
    src = tmp_path / "no_origin"
    src.mkdir()
    subprocess.run(["git", "init", "-q", str(src)], check=True)  # git, but no origin remote
    add_repo_root_overlay(src)
    assert fork_overlay_source(src) is None
    assert fork_overlay_active(src) is False
