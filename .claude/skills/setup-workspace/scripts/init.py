#!/usr/bin/env python3
"""Initialise a workspace from a v2 boilerplate source.

Usage:
    init.py --workspace <path> [--source <path>] [--dry-run]

Sibling-layout convention: the source clone and the target workspace live at
sibling paths (e.g., ~/src/memnyx/ and ~/workspace/). Run init
from inside the source clone; pass the target workspace via --workspace.

Source path defaults to cwd when cwd is itself a v2 boilerplate (identified
by the marker .claude/skills/setup-workspace/templates/workspace-CLAUDE.md.tmpl).
Otherwise --source is required.

Refuses if source and workspace are nested (one inside the other) or equal —
this prevents the user re-creating the CLAUDE.md traversal-up problem the
sibling layout exists to solve.

Idempotent. Skills/agents/agent-guardrails.md are overwritten on re-run; user
content (CLAUDE.md, memory files, identity, gitignore, settings.json, doc
templates) is preserved if already present.

Use --dry-run to preview without writing anything.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 10):
    sys.exit(
        f"Python 3.10+ required (detected {sys.version_info.major}.{sys.version_info.minor}). "
        "Install a newer Python via brew, uv, or pyenv."
    )

import argparse
import shutil
from pathlib import Path

WORKSPACE_TEMPLATE_REL = ".claude/skills/setup-workspace/templates/workspace-CLAUDE.md.tmpl"
STARTERS_DIR_REL = ".claude/skills/setup-workspace/templates/starters/workspace"

# Dirs to create at workspace root.
# `projects/` is pre-created so `mkdir <workspace>/projects/<slug>` and
# `ln -s ... <workspace>/projects/<slug>` (the documented add-project paths in
# /hello and add_project.py) don't fail for a fresh user with no parent dir.
ROOT_DIRS = ["workstreams", "sessions/active", "artifacts", "me", "projects"]
# Dirs to create under .claude/
CLAUDE_DIRS = ["memory", "skills", "agents", "docs"]

# Starter files copied (only written if missing). Edit the files under
# templates/starters/workspace/ to change starter content. To add or remove a
# starter, edit `_starter_maps.WORKSPACE_STARTERS` so init, add_project, and
# sync stay aligned. The gitignore source has its leading dot stripped
# (filesystems get weird with dotfile-only directories) and is materialised as
# `.gitignore` at the workspace.
from _starter_maps import WORKSPACE_STARTERS as STARTER_MAP  # noqa: E402
import launcher  # noqa: E402  — launcher.write_memnyx_sh writes the mmn shell launcher

# Module-level state set by main()
_WORKSPACE: Path | None = None
_DRY_RUN: bool = False


def workspace() -> Path:
    if _WORKSPACE is None:
        raise RuntimeError("workspace not initialised; call main() first")
    return _WORKSPACE


def is_dry_run() -> bool:
    return _DRY_RUN


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def is_v2_boilerplate(p: Path) -> bool:
    return (p / WORKSPACE_TEMPLATE_REL).is_file()


def resolve_workspace(workspace_arg: str) -> Path:
    p = Path(workspace_arg).expanduser().resolve()
    if p.exists() and not p.is_dir():
        die(f"workspace path is not a directory: {p}")
    return p


def resolve_source(source_arg: str | None) -> Path:
    if source_arg:
        p = Path(source_arg).expanduser().resolve()
        if not p.is_dir():
            die(f"source path is not a directory: {p}")
        if not is_v2_boilerplate(p):
            die(f"source at {p} is not a v2 boilerplate (missing {WORKSPACE_TEMPLATE_REL})")
        return p

    cwd = Path.cwd().resolve()
    if is_v2_boilerplate(cwd):
        return cwd

    die(
        f"cwd ({cwd}) is not a v2 boilerplate, and --source was not provided.\n"
        f"hint: run init from inside the cloned memnyx folder, "
        f"or pass --source <path> explicitly."
    )


def validate_layout(workspace: Path, source: Path) -> None:
    """Refuse if source and workspace overlap. Sibling layout is required."""
    if workspace == source:
        die(
            f"workspace and source resolve to the same path: {workspace}\n"
            f"hint: clone the boilerplate to a separate folder outside the workspace."
        )
    if source.is_relative_to(workspace):
        die(
            f"source ({source}) is nested inside workspace ({workspace}).\n"
            f"hint: the sibling layout requires the boilerplate clone to live "
            f"OUTSIDE the workspace folder. Move the clone, e.g.:\n"
            f"  mv {source} ~/src/{source.name}"
        )
    if workspace.is_relative_to(source):
        die(
            f"workspace ({workspace}) is nested inside source ({source}).\n"
            f"hint: pick a workspace folder that is not under the boilerplate clone."
        )


def create_dirs(created: list, skipped: list) -> None:
    ws = workspace()
    if not ws.exists():
        if not is_dry_run():
            ws.mkdir(parents=True, exist_ok=True)
        created.append("workspace root")
    for d in ROOT_DIRS:
        path = ws / d
        if path.exists():
            skipped.append(f"dir {d}/ (exists)")
        else:
            if not is_dry_run():
                path.mkdir(parents=True, exist_ok=True)
            created.append(f"dir {d}/")
    for d in CLAUDE_DIRS:
        path = ws / ".claude" / d
        if path.exists():
            skipped.append(f"dir .claude/{d}/ (exists)")
        else:
            if not is_dry_run():
                path.mkdir(parents=True, exist_ok=True)
            created.append(f"dir .claude/{d}/")


def write_workspace_marker(created: list, skipped: list) -> None:
    """Create the workspace marker file. Other skills detect a workspace by its presence."""
    marker = workspace() / ".claude" / ".workspace"
    if marker.exists():
        skipped.append(".claude/.workspace (exists)")
        return
    if not is_dry_run():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("")
    created.append(".claude/.workspace")


def write_source_ref(source: Path, created: list, skipped: list) -> None:
    """Record the source path so /setup-workspace sync can find it without --source."""
    ref = workspace() / ".claude" / ".source"
    if ref.exists():
        existing = ref.read_text().strip()
        if existing == str(source):
            skipped.append(".claude/.source (already points at source)")
            return
        # Source path has changed; update it.
        if not is_dry_run():
            ref.write_text(str(source) + "\n")
        created.append(f".claude/.source (updated: {existing} -> {source})")
        return
    if not is_dry_run():
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text(str(source) + "\n")
    created.append(".claude/.source")


def deploy_dir(src: Path, dst: Path, overwrite: bool, created: list, skipped: list, label: str) -> None:
    """Copy contents of src into dst. If overwrite, dst entries are replaced."""
    if not src.is_dir():
        skipped.append(f"{label} (source missing)")
        return
    if dst.is_symlink():
        skipped.append(
            f"{label} (refused: {dst} is a symlink to {dst.resolve()}; "
            f"the boilerplate manages this directory directly — remove the symlink and re-run)"
        )
        return
    if not is_dry_run():
        dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        target = dst / entry.name
        target_present = target.exists() or target.is_symlink()
        if target_present and not overwrite:
            skipped.append(f"{label}/{entry.name} (exists)")
            continue
        if not is_dry_run():
            if target.is_symlink():
                target.unlink()
            elif target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            if entry.is_dir():
                shutil.copytree(entry, target)
            else:
                shutil.copy2(entry, target)
        created.append(f"{label}/{entry.name}")


def deploy_agent_guardrails(source: Path, created: list, skipped: list) -> None:
    src = source / ".claude/docs/agent-guardrails.md"
    dst = workspace() / ".claude/docs/agent-guardrails.md"
    if not src.is_file():
        skipped.append("docs/agent-guardrails.md (source missing)")
        return
    if dst.is_symlink():
        skipped.append(
            f"docs/agent-guardrails.md (refused: dst is a symlink to {dst.resolve()}; "
            f"remove the symlink and re-run)"
        )
        return
    if not is_dry_run():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    created.append("docs/agent-guardrails.md (overwritten)")


def deploy_other_docs(source: Path, created: list, skipped: list) -> None:
    src_docs = source / ".claude/docs"
    dst_docs = workspace() / ".claude/docs"
    if not src_docs.is_dir():
        skipped.append("docs/ (source missing)")
        return
    if not is_dry_run():
        dst_docs.mkdir(parents=True, exist_ok=True)
    for entry in src_docs.iterdir():
        if entry.name == "agent-guardrails.md":
            continue
        target = dst_docs / entry.name
        if target.exists():
            skipped.append(f"docs/{entry.name} (exists; user-owned template)")
            continue
        if not is_dry_run():
            if entry.is_dir():
                shutil.copytree(entry, target)
            else:
                shutil.copy2(entry, target)
        created.append(f"docs/{entry.name}")


def deploy_settings(source: Path, created: list, skipped: list) -> None:
    src = source / ".claude/settings.json"
    dst = workspace() / ".claude/settings.json"
    if not src.is_file():
        skipped.append(".claude/settings.json (source missing)")
        return
    if dst.exists():
        skipped.append(".claude/settings.json (exists; run /setup-workspace sync to update later)")
        return
    if not is_dry_run():
        shutil.copy2(src, dst)
    created.append(".claude/settings.json")


def generate_claude_md(source: Path, created: list, skipped: list) -> None:
    template = source / WORKSPACE_TEMPLATE_REL
    dst = workspace() / "CLAUDE.md"
    if dst.exists():
        skipped.append("CLAUDE.md (exists)")
        return
    if not template.is_file():
        die(f"template missing at {template}")
    if not is_dry_run():
        content = template.read_text()
        content = content.replace("{{workspace_name}}", workspace().name)
        content = content.replace("{{workspace_path}}", str(workspace()))
        dst.write_text(content)
    created.append("CLAUDE.md")


def write_starter(path: Path, content: str, label: str, created: list, skipped: list) -> None:
    if path.exists():
        skipped.append(f"{label} (exists)")
        return
    if not is_dry_run():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    created.append(label)


def deploy_starters(source: Path, created: list, skipped: list) -> None:
    ws = workspace()
    starters_dir = source / STARTERS_DIR_REL
    for src_name, dst_rel in STARTER_MAP:
        src = starters_dir / src_name
        if not src.is_file():
            die(f"starter missing at {src}\nhint: re-clone the boilerplate source.")
        write_starter(ws / dst_rel, src.read_text(), dst_rel, created, skipped)


def write_launcher(created: list, skipped: list) -> None:
    """Write <workspace>/shell/memnyx.sh (the `mmn` launcher). Derived — always
    overwritten, like agent-guardrails. Doing it here (not leaving it to the
    agent) guarantees the launcher exists after init; wiring it into the user's
    shell profile is the only consent-gated part, handled by the skill's step 8."""
    launcher.write_memnyx_sh(workspace(), is_dry_run())
    created.append("shell/memnyx.sh (mmn launcher, overwritten)")


def print_summary(source: Path, created: list, skipped: list) -> None:
    print()
    if is_dry_run():
        print("=== /setup-workspace init [DRY RUN] ===")
        print("(no files written; this is a preview)")
    else:
        print("=== /setup-workspace init complete ===")
    print(f"Workspace: {workspace()}")
    print(f"Source:    {source}")
    print()
    if created:
        verb = "Would create" if is_dry_run() else "Created"
        print(f"{verb} ({len(created)}):")
        for item in created:
            print(f"  + {item}")
    if skipped:
        verb = "Would skip" if is_dry_run() else "Skipped"
        print(f"\n{verb} ({len(skipped)}):")
        for item in skipped:
            print(f"  · {item}")
    print()
    if is_dry_run():
        print("Re-run without --dry-run to apply.")
    else:
        print("Next steps:")
        print(f"  - cd {workspace()} and start a new Claude session.")
        print("  - Fill in me/identity.md (placeholder values) and the Conventions block in CLAUDE.md.")
        print("  - Run /hello — it picks up registered projects, or offers to register new ones as you describe them.")
        print("  - The `mmn` launcher was written to shell/memnyx.sh; enabling it edits your shell profile, so /setup-workspace asks before wiring it.")
        print("  - Optional: /setup-cognee for semantic search across memory.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialise a workspace from a v2 boilerplate source.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workspace", required=True, help="Workspace path to install into.")
    parser.add_argument(
        "--source",
        help="Boilerplate source path. Defaults to cwd when cwd is itself a v2 boilerplate.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing anything.")
    return parser.parse_args()


def main() -> None:
    global _WORKSPACE, _DRY_RUN
    args = parse_args()
    _DRY_RUN = args.dry_run
    _WORKSPACE = resolve_workspace(args.workspace)
    source = resolve_source(args.source)
    validate_layout(_WORKSPACE, source)

    if _DRY_RUN:
        print("=== DRY RUN — nothing will be written ===\n")
    print(f"Workspace: {_WORKSPACE}")
    print(f"Source:    {source}")
    print()

    created: list = []
    skipped: list = []

    create_dirs(created, skipped)
    write_workspace_marker(created, skipped)
    write_source_ref(source, created, skipped)
    deploy_dir(source / ".claude/skills", _WORKSPACE / ".claude/skills", overwrite=True, created=created, skipped=skipped, label="skills")
    deploy_dir(source / ".claude/agents", _WORKSPACE / ".claude/agents", overwrite=True, created=created, skipped=skipped, label="agents")
    deploy_agent_guardrails(source, created, skipped)
    deploy_other_docs(source, created, skipped)
    deploy_settings(source, created, skipped)
    generate_claude_md(source, created, skipped)
    deploy_starters(source, created, skipped)
    write_launcher(created, skipped)
    print_summary(source, created, skipped)


if __name__ == "__main__":
    main()
