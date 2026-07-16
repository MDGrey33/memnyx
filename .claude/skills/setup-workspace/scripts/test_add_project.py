"""Regression tests for add_project.py's CLAUDE.md generate/patch behavior.

Run with:
    uv run --with pytest pytest scripts/test_add_project.py -v

Builds a minimal mock workspace under tmp_path (template + starters + registry
script) and invokes add_project.py as a subprocess, mirroring real usage —
avoids fighting the script's module-level globals set by main().
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

SETUP_WORKSPACE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = SETUP_WORKSPACE_DIR.parent.parent.parent  # <workspace>/


def build_sandbox(tmp_path: Path) -> Path:
    """Assemble a minimal mock workspace with everything add_project.py needs."""
    ws = tmp_path / "ws"
    sw_scripts = ws / ".claude/skills/setup-workspace/scripts"
    sw_templates = ws / ".claude/skills/setup-workspace/templates"
    registry_scripts = ws / ".claude/skills/project-registry/scripts"
    sw_scripts.mkdir(parents=True)
    (sw_templates / "starters/project").mkdir(parents=True)
    registry_scripts.mkdir(parents=True)

    for name in ("add_project.py", "_starter_maps.py", "_common.py"):
        shutil.copy(SETUP_WORKSPACE_DIR / "scripts" / name, sw_scripts / name)
    shutil.copy(
        SETUP_WORKSPACE_DIR / "templates/project-CLAUDE.md.tmpl",
        sw_templates / "project-CLAUDE.md.tmpl",
    )
    for src in (SETUP_WORKSPACE_DIR / "templates/starters/project").iterdir():
        shutil.copy(src, sw_templates / "starters/project" / src.name)
    shutil.copy(
        WORKSPACE_ROOT / ".claude/skills/project-registry/scripts/registry.py",
        registry_scripts / "registry.py",
    )
    (ws / ".claude/projects-index.json").write_text(
        json.dumps({"schemaVersion": "1.0", "projects": {}})
    )
    return ws


def run_add_project(ws: Path, slug: str, description: str = "", *, dry_run: bool = False) -> subprocess.CompletedProcess:
    args = [sys.executable, str(ws / ".claude/skills/setup-workspace/scripts/add_project.py"), slug]
    if description:
        args.append(description)
    if dry_run:
        args.append("--dry-run")
    return subprocess.run(args, cwd=str(ws), capture_output=True, text=True)


def test_fresh_project_generates_full_template(tmp_path):
    ws = build_sandbox(tmp_path)
    (ws / "projects/fresh").mkdir(parents=True)
    result = run_add_project(ws, "fresh", "a brand new project")
    assert result.returncode == 0, result.stderr

    claude_md = (ws / "projects/fresh/CLAUDE.md").read_text()
    assert "@.claude/memory/MEMORY.md" in claude_md
    assert "# fresh" in claude_md
    assert "a brand new project" in claude_md


def test_preexisting_claude_md_gets_memory_section_appended(tmp_path):
    ws = build_sandbox(tmp_path)
    pdir = ws / "projects/harness-like"
    pdir.mkdir(parents=True)
    original = "# Some Real Repo\n\nCustom hand-authored content that must be preserved verbatim.\n"
    (pdir / "CLAUDE.md").write_text(original)

    result = run_add_project(ws, "harness-like")
    assert result.returncode == 0, result.stderr

    patched = (pdir / "CLAUDE.md").read_text()
    assert patched.startswith(original.rstrip("\n"))
    assert "@.claude/memory/MEMORY.md" in patched
    assert patched.count("## Memory") == 1
    assert "Patched (1)" in result.stdout


def test_preexisting_claude_md_with_include_is_left_untouched(tmp_path):
    ws = build_sandbox(tmp_path)
    pdir = ws / "projects/already-wired"
    pdir.mkdir(parents=True)
    original = "# Already Wired\n\n## Memory\n\n@.claude/memory/MEMORY.md\n"
    (pdir / "CLAUDE.md").write_text(original)

    result = run_add_project(ws, "already-wired")
    assert result.returncode == 0, result.stderr
    assert (pdir / "CLAUDE.md").read_text() == original
    assert "Skipped" in result.stdout


def test_preexisting_unrelated_memory_heading_is_not_duplicated(tmp_path):
    ws = build_sandbox(tmp_path)
    pdir = ws / "projects/own-memory"
    pdir.mkdir(parents=True)
    original = (
        "# Service X\n\n## Memory\n"
        "This service keeps an in-process LRU cache; see cache.py for eviction rules.\n"
    )
    (pdir / "CLAUDE.md").write_text(original)

    result = run_add_project(ws, "own-memory")
    assert result.returncode == 0, result.stderr

    unchanged = (pdir / "CLAUDE.md").read_text()
    assert unchanged == original, "a pre-existing unrelated '## Memory' heading must never be duplicated"
    assert unchanged.count("## Memory") == 1
    assert "@.claude/memory/MEMORY.md" not in unchanged
    assert "has its own '## Memory' section" in result.stdout


def test_rerun_is_idempotent_no_duplicate_section(tmp_path):
    ws = build_sandbox(tmp_path)
    pdir = ws / "projects/harness-like"
    pdir.mkdir(parents=True)
    (pdir / "CLAUDE.md").write_text("# Some Real Repo\n\nContent.\n")

    run_add_project(ws, "harness-like")
    first = (pdir / "CLAUDE.md").read_text()
    result = run_add_project(ws, "harness-like")
    second = (pdir / "CLAUDE.md").read_text()

    assert first == second
    assert second.count("## Memory") == 1
    assert second.count("@.claude/memory/MEMORY.md") == 1
    assert "Skipped" in result.stdout


def test_preexisting_file_with_no_trailing_newline_merges_cleanly(tmp_path):
    ws = build_sandbox(tmp_path)
    pdir = ws / "projects/no-trailing-nl"
    pdir.mkdir(parents=True)
    (pdir / "CLAUDE.md").write_text("# No Trailing Newline\n\nSome content, no final newline.")

    result = run_add_project(ws, "no-trailing-nl")
    assert result.returncode == 0, result.stderr

    merged = (pdir / "CLAUDE.md").read_text()
    assert "final newline.\n\n## Memory" in merged
    assert "final newline.## Memory" not in merged


def test_dry_run_writes_nothing(tmp_path):
    ws = build_sandbox(tmp_path)
    pdir = ws / "projects/harness-like"
    pdir.mkdir(parents=True)
    original = "# Some Real Repo\n\nContent.\n"
    (pdir / "CLAUDE.md").write_text(original)

    result = run_add_project(ws, "harness-like", dry_run=True)
    assert result.returncode == 0, result.stderr
    assert (pdir / "CLAUDE.md").read_text() == original
    assert "Would patch" in result.stdout
    assert not (ws / ".claude/projects-index.json").read_text().count('"harness-like"')
