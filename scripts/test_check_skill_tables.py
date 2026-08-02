"""Regression tests for check_skill_tables.py's fork-overlay union logic.

Run with:
    uv run --with pytest pytest scripts/test_check_skill_tables.py -v

check_skill_tables reads REPO_ROOT-relative module constants (SKILLS_DIR,
DOC_SURFACES, FORK_OVERLAY). Each test builds a tiny mock repo under tmp_path and
monkeypatches those constants, then asserts main()'s exit code. Covers the union
the fork overlay introduced: a base surface is complete when its own rows UNION
CLAUDE.fork.md's rows cover the on-disk set — with dead rows still attributed to
the file that carries them, the overlay included. Canonical memnyx ships no
CLAUDE.fork.md, so the empty-union path must reduce to the old base equality.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import check_skill_tables as cst  # noqa: E402


def _table(slugs: list[str]) -> str:
    rows = "\n".join(f"| `/{s}` | desc |" for s in slugs)
    return f"| Skill | Purpose |\n|---|---|\n{rows}\n"


@pytest.fixture
def build(tmp_path, monkeypatch):
    """Assemble a mock repo and point the checker's constants at it.

    disk: skill dirs to create; surfaces: list of per-surface slug lists (each a
    DOC_SURFACE); fork: overlay slug list, or None to omit CLAUDE.fork.md."""
    def _build(disk: list[str], surfaces: list[list[str]], fork: list[str] | None):
        skills_dir = tmp_path / ".claude" / "skills"
        for s in disk:
            (skills_dir / s).mkdir(parents=True)
            (skills_dir / s / "SKILL.md").write_text(f"# {s}\n", encoding="utf-8")

        surface_paths = []
        for i, slugs in enumerate(surfaces):
            p = tmp_path / f"surface_{i}.md"
            p.write_text(_table(slugs), encoding="utf-8")
            surface_paths.append(p)

        fork_path = tmp_path / "CLAUDE.fork.md"
        if fork is not None:
            fork_path.write_text(_table(fork), encoding="utf-8")

        monkeypatch.setattr(cst, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(cst, "SKILLS_DIR", skills_dir)
        monkeypatch.setattr(cst, "DOC_SURFACES", surface_paths)
        monkeypatch.setattr(cst, "FORK_OVERLAY", fork_path)
    return _build


def test_union_complete_passes(build):
    # base surfaces list upstream skills only; the overlay supplies the fork skill
    build(disk=["hello", "bye", "jira"],
          surfaces=[["hello", "bye"], ["hello", "bye"]],
          fork=["jira"])
    assert cst.main() == 0


def test_missing_from_both_base_and_overlay_fails(build):
    build(disk=["hello", "bye", "jira"],
          surfaces=[["hello", "bye"], ["hello", "bye"]],
          fork=[])  # overlay present but does not list jira
    assert cst.main() == 1


def test_dead_row_in_a_base_surface_fails(build):
    build(disk=["hello"],
          surfaces=[["hello", "ghost"], ["hello"]],  # ghost has no skill on disk
          fork=[])
    assert cst.main() == 1


def test_dead_row_in_overlay_fails(build):
    build(disk=["hello"],
          surfaces=[["hello"], ["hello"]],
          fork=["ghost"])  # overlay lists a skill that isn't on disk
    assert cst.main() == 1


def test_no_overlay_reduces_to_base_equality_pass(build):
    # canonical memnyx: no CLAUDE.fork.md; each base table must equal disk on its own
    build(disk=["hello", "bye"],
          surfaces=[["hello", "bye"], ["hello", "bye"]],
          fork=None)
    assert cst.main() == 0


def test_no_overlay_incomplete_base_fails(build):
    build(disk=["hello", "bye"],
          surfaces=[["hello"], ["hello", "bye"]],  # first surface misses bye, no overlay to cover it
          fork=None)
    assert cst.main() == 1
