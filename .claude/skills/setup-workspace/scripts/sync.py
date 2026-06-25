#!/usr/bin/env python3
"""Sync upstream-owned content from a v2 boilerplate source to a workspace.

Usage:
    sync.py --workspace <path> [--source <path>]                  # report only
    sync.py --workspace <path> [--source <path>] --apply-all      # apply every update + new file (incl. starter new)
    sync.py --workspace <path> [--source <path>] --apply <relpath>...   # apply specific files

Walks two surfaces:

  1. Upstream-owned content (`.claude/skills/**`, `.claude/agents/**`,
     `.claude/docs/agent-guardrails.md`) — fully bucketed and acted on.
  2. Starter files (workspace-level + per-registered-project) — bucketed
     with the `update` bucket SUPPRESSED. Starters are user-evolved after
     init; sync only ever offers to deploy `new` ones, never to overwrite
     a workspace copy that has diverged from source.

Bucket meanings:
    unchanged    workspace matches source
    update       workspace differs from source (locally edited or upstream changed)
                   — only actionable for upstream-owned content; for starters,
                   surfaced as `divergent` and never applied
    new          source has the file, workspace doesn't
    local-only   workspace has the file, source doesn't (user-added)

Default mode prints the plan and exits. Apply modes copy source-version files
to the workspace for the named (or all) actionable paths. local-only files are
never touched — sync doesn't remove user-added content.

Source path defaults to the absolute path stored in `<workspace>/.claude/.source`
(written by `init.py`). Pass `--source` explicitly to override.

Does NOT touch user-evolved content directly: CLAUDE.md, MEMORY.md, lessons-learned.md,
identity, workstreams, sessions, settings.json, project-context.md, or other
.claude/docs/* templates. The starter walk does *report* divergence for files in
these categories, but never overwrites.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 10):
    sys.exit(
        f"Python 3.10+ required (detected {sys.version_info.major}.{sys.version_info.minor}). "
        "Install a newer Python via brew, uv, or pyenv."
    )

import argparse
import filecmp
import json
import shutil
from pathlib import Path

from _starter_maps import PROJECT_STARTERS, WORKSPACE_STARTERS
from _common import (
    die, is_v2_boilerplate, resolve_workspace, BOILERPLATE_MARKER_REL,
    classify_source, fork_overlay_active, fork_include_block, render_template,
    FORK_OVERLAY_TEMPLATE_REL, LOCAL_OVERLAY_SEED_REL,
)
import launcher  # launcher.write_memnyx_sh regenerates the mmn shell launcher on apply

SOURCE_REF_REL = ".claude/.source"
REGISTRY_REL = ".claude/projects-index.json"

SYNCED_DIRS = [".claude/skills", ".claude/agents"]
SYNCED_FILES = [".claude/docs/agent-guardrails.md"]

STARTERS_WORKSPACE_DIR_REL = ".claude/skills/setup-workspace/templates/starters/workspace"
STARTERS_PROJECT_DIR_REL = ".claude/skills/setup-workspace/templates/starters/project"

# Skipped during comparison (runtime artifacts, OS metadata).
SKIP_DIR_NAMES = {"__pycache__"}
SKIP_FILE_NAMES = {".DS_Store"}


def resolve_source(source_arg: str | None, workspace: Path) -> Path:
    if source_arg:
        p = Path(source_arg).expanduser().resolve()
    else:
        ref = workspace / SOURCE_REF_REL
        if not ref.is_file():
            die(
                f"no source path provided and {SOURCE_REF_REL} not found in workspace.\n"
                f"hint: pass --source <path>, or re-run init to record the source."
            )
        recorded = ref.read_text().strip()
        if not recorded:
            die(f"{ref} is empty. Pass --source <path> explicitly.")
        p = Path(recorded).expanduser().resolve()

    if not p.is_dir():
        die(f"source path is not a directory: {p}")
    if not is_v2_boilerplate(p):
        die(f"source at {p} is not a v2 boilerplate (missing {BOILERPLATE_MARKER_REL})")
    return p


def walk_synced(root: Path, rel_root: str) -> list[str]:
    """Walk root/rel_root, return sorted list of relative paths (from root). Skips runtime artifacts."""
    base = root / rel_root
    if not base.is_dir():
        return []
    result = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in p.relative_to(root).parts):
            continue
        if p.name in SKIP_FILE_NAMES:
            continue
        result.append(str(p.relative_to(root)))
    return sorted(result)


def build_plan(workspace: Path, source: Path) -> dict:
    """Return upstream-owned buckets keyed as {update, new, local_only, unchanged} (relative paths)."""
    source_paths: set[str] = set()
    workspace_paths: set[str] = set()

    for d in SYNCED_DIRS:
        source_paths.update(walk_synced(source, d))
        workspace_paths.update(walk_synced(workspace, d))
    for f in SYNCED_FILES:
        if (source / f).is_file():
            source_paths.add(f)
        if (workspace / f).is_file():
            workspace_paths.add(f)

    update, new, local_only, unchanged = [], [], [], []

    for rel in sorted(source_paths | workspace_paths):
        src = source / rel
        dst = workspace / rel
        in_src = src.is_file()
        in_dst = dst.is_file()
        if in_src and not in_dst:
            new.append(rel)
        elif in_dst and not in_src:
            local_only.append(rel)
        elif in_src and in_dst:
            if filecmp.cmp(src, dst, shallow=False):
                unchanged.append(rel)
            else:
                update.append(rel)

    return {"update": update, "new": new, "local_only": local_only, "unchanged": unchanged}


def registered_project_slugs(workspace: Path) -> list[str]:
    """Read the workspace registry. Empty list if missing/malformed."""
    registry = workspace / REGISTRY_REL
    if not registry.is_file():
        return []
    try:
        data = json.loads(registry.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    return sorted((data.get("projects") or {}).keys())


def _categorise(src: Path, dst: Path) -> str:
    in_src = src.is_file()
    in_dst = dst.is_file()
    if in_src and not in_dst:
        return "new"
    if in_dst and not in_src:
        return "local_only"
    if in_src and in_dst:
        return "unchanged" if filecmp.cmp(src, dst, shallow=False) else "divergent"
    return "missing"


def build_starter_plan(workspace: Path, source: Path) -> dict:
    """Walk starter files (workspace + per-registered-project).

    Returns {divergent, new, local_only, unchanged} lists of display paths
    (`<starter-class>/<dest-relpath>`, e.g. `workspace/.gitignore` or
    `projects/foo/.claude/memory/MEMORY.md`) and a `sources` dict mapping
    each display path to its absolute source Path. `divergent` mirrors
    the `update` bucket but is never actionable — starters are user-evolved.
    """
    divergent, new, local_only, unchanged = [], [], [], []
    sources: dict[str, Path] = {}
    dests: dict[str, Path] = {}

    starters_workspace = source / STARTERS_WORKSPACE_DIR_REL
    if starters_workspace.is_dir():
        for src_name, dst_relpath in WORKSPACE_STARTERS:
            src_path = starters_workspace / src_name
            dst_path = workspace / dst_relpath
            display = f"workspace/{dst_relpath}"
            sources[display] = src_path
            dests[display] = dst_path
            bucket = _categorise(src_path, dst_path)
            if bucket == "new":
                new.append(display)
            elif bucket == "divergent":
                divergent.append(display)
            elif bucket == "unchanged":
                unchanged.append(display)
            elif bucket == "local_only":
                local_only.append(display)
            # "missing" (neither side has it) is impossible here since WORKSPACE_STARTERS lists source files

    starters_project = source / STARTERS_PROJECT_DIR_REL
    if starters_project.is_dir():
        for slug in registered_project_slugs(workspace):
            project_dir = workspace / "projects" / slug
            if not project_dir.is_dir() and not project_dir.is_symlink():
                continue  # project missing on disk; surfaced by /project-registry, not here
            for src_name, dst_relpath in PROJECT_STARTERS:
                src_path = starters_project / src_name
                dst_path = project_dir / dst_relpath
                display = f"projects/{slug}/{dst_relpath}"
                sources[display] = src_path
                dests[display] = dst_path
                bucket = _categorise(src_path, dst_path)
                if bucket == "new":
                    new.append(display)
                elif bucket == "divergent":
                    divergent.append(display)
                elif bucket == "unchanged":
                    unchanged.append(display)
                elif bucket == "local_only":
                    local_only.append(display)

    return {
        "divergent": sorted(divergent),
        "new": sorted(new),
        "local_only": sorted(local_only),
        "unchanged": sorted(unchanged),
        "sources": sources,
        "dests": dests,
    }


CLAUDE_MD_MEMORY_INCLUDE = "@.claude/memory/MEMORY.md"


def claude_md_missing_memory_include(workspace: Path) -> list[Path]:
    """Return CLAUDE.md paths (workspace + each registered project) that do not
    reference `@.claude/memory/MEMORY.md`. Templates ship with this `@`-include so
    the MEMORY.md index auto-loads at session start; existing deployed CLAUDE.md
    files are user-evolved and never modified by sync — this surfaces drift as
    an advisory hint only.
    """
    missing: list[Path] = []
    candidates = [workspace / "CLAUDE.md"]
    for slug in registered_project_slugs(workspace):
        candidates.append(workspace / "projects" / slug / "CLAUDE.md")
    for cm in candidates:
        if not cm.is_file():
            continue
        try:
            if CLAUDE_MD_MEMORY_INCLUDE not in cm.read_text():
                missing.append(cm)
        except OSError:
            continue
    return missing


def print_claude_md_memory_advisory(missing: list[Path]) -> None:
    if not missing:
        return
    print()
    print("Hint: the following CLAUDE.md file(s) do not @-include their MEMORY.md.")
    print(f"Add a line `{CLAUDE_MD_MEMORY_INCLUDE}` to auto-load the memory index")
    print("at session start (template addition). Sync does not modify CLAUDE.md.")
    for cm in missing:
        print(f"  · {cm}")


LAYERED_OVERLAYS_MARKER = "## Layered overlays"


def render_base_claude_md(source: Path, workspace: Path) -> str:
    c = render_template(source / BOILERPLATE_MARKER_REL, workspace)
    return c.replace("{{fork_overlay_include}}", fork_include_block(source))


def _safe_layer_write(dst: Path, content: str, label: str, actions: list[str]) -> None:
    """Write a layer file, refusing a symlinked destination — mirrors the symlink
    refusal apply_paths enforces, so sync never follows a link out of the workspace
    and clobbers an external target."""
    if dst.is_symlink():
        actions.append(f"{label} — refused: {dst.name} is a symlink to {dst.resolve()}; remove the symlink and re-run")
        return
    dst.write_text(content)
    actions.append(f"{label} — written")


def reconcile_claude_layers(workspace: Path, source: Path, apply: bool) -> list[str]:
    """Reconcile the three CLAUDE.md layers — kept separate from the file-copy
    buckets because base/fork/local are generated from templates with substitution.

      base   CLAUDE.md        overwritten from the rendered base template
      fork   CLAUDE.fork.md   overwritten from the fork overlay template (forks only)
      local  CLAUDE.local.md  seeded from its template if absent; never overwritten

    Two guards protect ALL three layers (touch nothing if either trips):
      * classification 'unknown' — the source's git origin can't be read, so we
        can't tell canonical from fork; never guess (a transient failure must not
        flip a canonical workspace into fork shape).
      * legacy monolith — the base lacks the '## Layered overlays' marker; hold
        every layer until the user runs the one-time split (else the local seed
        would duplicate the monolith's Conventions and a fork overlay would be
        written that nothing references).
    """
    actions: list[str] = []

    kind = classify_source(source)  # cached: one git lookup per process
    if kind == "unknown":
        actions.append("layers — SKIPPED: source git origin unreadable; cannot classify canonical-vs-fork, base/fork/local left untouched")
        return actions

    base_dst = workspace / "CLAUDE.md"
    if not base_dst.is_file():
        actions.append("CLAUDE.md — missing; run init (sync does not create the base)")
        return actions
    existing = base_dst.read_text()
    if LAYERED_OVERLAYS_MARKER not in existing:
        actions.append("CLAUDE.md — SKIPPED: legacy monolithic (no '## Layered overlays'); run the one-time split first. Fork overlay + local seed held until then.")
        return actions

    # base
    rendered = render_base_claude_md(source, workspace)
    if existing == rendered:
        actions.append("CLAUDE.md — unchanged (base)")
    elif apply:
        _safe_layer_write(base_dst, rendered, "CLAUDE.md (base)", actions)
    else:
        actions.append("CLAUDE.md — would overwrite (base differs)")

    # fork overlay
    fork_dst = workspace / "CLAUDE.fork.md"
    if fork_overlay_active(source):
        rendered_fork = render_template(source / FORK_OVERLAY_TEMPLATE_REL, workspace)
        if fork_dst.is_file() and fork_dst.read_text() == rendered_fork:
            actions.append("CLAUDE.fork.md — unchanged (fork overlay)")
        elif apply:
            _safe_layer_write(fork_dst, rendered_fork, "CLAUDE.fork.md (fork overlay)", actions)
        else:
            verb = "missing" if not fork_dst.is_file() else "differs"
            actions.append(f"CLAUDE.fork.md — would overwrite (fork overlay; {verb})")
    elif kind == "fork":
        actions.append("CLAUDE.fork.md — source is a fork but ships no overlay template; base include suppressed")
    elif fork_dst.is_file():
        actions.append("CLAUDE.fork.md — ORPHANED: source is canonical and the base no longer references it; remove by hand if the source change was intended")

    # local overlay — seed if missing, never overwrite (single owner: this reconciler)
    local_dst = workspace / "CLAUDE.local.md"
    if local_dst.is_file():
        actions.append("CLAUDE.local.md — present; left untouched (user-owned)")
    else:
        seed = source / LOCAL_OVERLAY_SEED_REL
        if not seed.is_file():
            actions.append("CLAUDE.local.md — missing; no seed template in source")
        elif apply:
            _safe_layer_write(local_dst, render_template(seed, workspace), "CLAUDE.local.md (seeded)", actions)
        else:
            actions.append("CLAUDE.local.md — would seed (missing)")

    return actions


def print_plan(workspace: Path, source: Path, plan: dict, starter_plan: dict) -> None:
    print()
    print("=== sync plan ===")
    print(f"workspace: {workspace}")
    print(f"source:    {source}")
    print()
    print("-- upstream-owned (skills, agents, agent-guardrails) --")
    print(f"== update ({len(plan['update'])}) ==")
    for rel in plan["update"]:
        print(f"M {rel}")
    print()
    print(f"== new ({len(plan['new'])}) ==")
    for rel in plan["new"]:
        print(f"+ {rel}")
    print()
    print(f"== local-only ({len(plan['local_only'])}) ==")
    for rel in plan["local_only"]:
        print(f"? {rel}")
    if plan["local_only"]:
        print("  (present in your workspace but not upstream — either something you")
        print("   added locally, OR a skill/agent upstream removed or renamed. sync never")
        print("   deletes; if it's an upstream removal, delete it by hand. See MIGRATION.md.)")
    print()
    print(f"== unchanged ({len(plan['unchanged'])} files match source) ==")
    print()
    print("-- starters (workspace + registered projects; divergent never applied) --")
    print(f"== starter new ({len(starter_plan['new'])}) ==")
    for rel in starter_plan["new"]:
        print(f"+ {rel}")
    print()
    print(f"== starter divergent ({len(starter_plan['divergent'])}) — informational; never applied ==")
    for rel in starter_plan["divergent"]:
        print(f"~ {rel}")
    print()
    print(f"== starter local-only ({len(starter_plan['local_only'])}) ==")
    for rel in starter_plan["local_only"]:
        print(f"? {rel}")
    print()
    print(f"== starter unchanged ({len(starter_plan['unchanged'])} files match source) ==")
    print()


def _is_feedback_starter(display: str) -> bool:
    """True if the starter destination is a `feedback_*.md` under a `.claude/memory/` dir."""
    return display.rsplit("/", 1)[-1].startswith("feedback_") and "/.claude/memory/" in f"/{display}"


def apply_paths(
    workspace: Path,
    source: Path,
    plan: dict,
    starter_plan: dict,
    paths: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Copy named paths from source to workspace.

    `paths` may mix upstream-owned relpaths (e.g. `.claude/skills/foo/SKILL.md`)
    and starter display paths (e.g. `workspace/.claude/memory/feedback_foo.md`).

    Returns (applied, skipped_with_reason, feedback_hints) — feedback_hints names
    any feedback starter files that landed in workspace memory, so the caller can
    surface a "consider updating MEMORY.md" nudge.
    """
    synced_eligible = set(plan["update"]) | set(plan["new"])
    starter_eligible = set(starter_plan["new"])
    applied: list[str] = []
    skipped: list[str] = []
    feedback_hints: list[str] = []

    for path in paths:
        if path in synced_eligible:
            src = source / path
            dst = workspace / path
            if dst.is_symlink():
                skipped.append(f"{path} (refused: dst is a symlink to {dst.resolve()}; remove the symlink and re-run)")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            applied.append(path)
        elif path in starter_eligible:
            src = starter_plan["sources"][path]
            dst = starter_plan["dests"][path]
            if dst.is_symlink():
                skipped.append(f"{path} (refused: dst is a symlink to {dst.resolve()}; remove the symlink and re-run)")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            applied.append(path)
            if _is_feedback_starter(path):
                feedback_hints.append(path)
        elif path in starter_plan["divergent"]:
            skipped.append(f"{path} (starter divergent — never auto-applied; edit by hand if needed)")
        else:
            skipped.append(f"{path} (not in any actionable bucket)")

    return applied, skipped, feedback_hints


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Sync upstream-owned content from boilerplate source to workspace.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--workspace", required=True, help="Workspace path.")
    p.add_argument("--source", help="Boilerplate source path. Defaults to <workspace>/.claude/.source.")
    p.add_argument("--apply", nargs="+", metavar="RELPATH", help="Apply these update/new paths.")
    p.add_argument("--apply-all", action="store_true", help="Apply every update + new path.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.apply and args.apply_all:
        die("--apply and --apply-all are mutually exclusive.")

    workspace = resolve_workspace(args.workspace)
    source = resolve_source(args.source, workspace)
    plan = build_plan(workspace, source)
    starter_plan = build_starter_plan(workspace, source)

    missing_includes = claude_md_missing_memory_include(workspace)

    if not args.apply and not args.apply_all:
        print_plan(workspace, source, plan, starter_plan)
        print("-- CLAUDE layers (base/fork generated from templates; local seeded-if-missing) --")
        print("   (reconciled only on --apply-all, not on selective --apply)")
        for action in reconcile_claude_layers(workspace, source, apply=False):
            print(f"  {action}")
        print()
        print_claude_md_memory_advisory(missing_includes)
        return

    if args.apply_all:
        targets = plan["update"] + plan["new"] + starter_plan["new"]
    else:
        targets = args.apply
    applied, skipped, feedback_hints = apply_paths(workspace, source, plan, starter_plan, targets)

    # Regenerate the derived mmn launcher from the (possibly just-updated) template.
    # Derived artifact — always overwritten; profile wiring stays consent-gated (skill step 6).
    launcher.write_memnyx_sh(workspace, dry_run=False)
    applied.append("shell/memnyx.sh (mmn launcher, regenerated)")

    layer_actions = reconcile_claude_layers(workspace, source, apply=True) if args.apply_all else []

    print()
    print("=== sync apply ===")
    print(f"workspace: {workspace}")
    print(f"source:    {source}")
    print()
    print(f"Applied ({len(applied)}):")
    for rel in applied:
        print(f"  + {rel}")
    if layer_actions:
        print()
        print("CLAUDE layers:")
        for action in layer_actions:
            print(f"  {action}")
    if skipped:
        print()
        print(f"Skipped ({len(skipped)}):")
        for note in skipped:
            print(f"  · {note}")
    if feedback_hints:
        print()
        print("Hint: the following feedback starter file(s) landed but your MEMORY.md")
        print("was not modified (starters are user-owned post-init). To add the index")
        print("line, copy the matching bullet from the boilerplate's MEMORY.md:")
        for display in feedback_hints:
            print(f"  · {display}")
    print_claude_md_memory_advisory(missing_includes)
    print()


if __name__ == "__main__":
    main()
