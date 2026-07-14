#!/usr/bin/env python3
"""Scaffold a project under <workspace>/projects/<slug>/ and register it.

Usage:
    add_project.py <slug> [description] [--dry-run]

Workspace = cwd (per v2 design — sessions are workspace-rooted, so the script
is always invoked from the workspace root). The project directory must
already exist at <workspace>/projects/<slug>/, as a real dir or a symlink.
Create it first:

    mkdir <workspace>/projects/<slug>                       # fresh project
    ln -s /path/to/repo <workspace>/projects/<slug>         # symlink existing

Idempotent. Re-running is safe: existing files are preserved, missing pieces
are filled in. The /project-registry add call at the end is skipped when the
slug is already registered.

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
import json
import re
import subprocess
from pathlib import Path

from _common import CLAUDE_MD_MEMORY_INCLUDE  # noqa: E402

SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")
WORKSPACE_MARKER = ".claude/skills/setup-workspace"
PROJECT_TEMPLATE_REL = ".claude/skills/setup-workspace/templates/project-CLAUDE.md.tmpl"
STARTERS_DIR_REL = ".claude/skills/setup-workspace/templates/starters/project"
REGISTRY_PATH_REL = ".claude/projects-index.json"
REGISTRY_SCRIPT_REL = ".claude/skills/project-registry/scripts/registry.py"

# Dirs to create at project root
PROJECT_ROOT_DIRS = ["workstreams", "sessions/active", "artifacts"]

# Patterns appended to the project's .gitignore
GITIGNORE_PATTERNS = [
    "workstreams/",
    "sessions/",
    "collected/",
    "artifacts/",
    "contributions/",
]
GITIGNORE_HEADER = "# Per-engineer working state — never commit"

# Starter files copied (only written if missing). Edit the files under
# templates/starters/project/ to change starter content. To add or remove a
# starter, edit `_starter_maps.PROJECT_STARTERS` so init, add_project, and
# sync stay aligned.
from _starter_maps import PROJECT_STARTERS as STARTER_MAP  # noqa: E402

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


def find_workspace() -> Path:
    cwd = Path.cwd()
    if not (cwd / WORKSPACE_MARKER).is_dir():
        die(
            f"cwd ({cwd}) doesn't look like a v2 workspace "
            f"(missing {WORKSPACE_MARKER}/).\n"
            f"hint: cd to the workspace root, "
            f"or run /setup-workspace init first."
        )
    return cwd


def validate_slug(slug: str) -> None:
    if not SLUG_RE.match(slug):
        die(f"invalid slug '{slug}': lowercase + hyphens only, must start with a letter")


def project_dir(slug: str) -> Path:
    return workspace() / "projects" / slug


def validate_project_dir_exists(slug: str) -> None:
    pdir = project_dir(slug)
    if not pdir.exists():
        die(
            f"project directory does not exist: {pdir}\n"
            f"create it first:\n"
            f"  mkdir {pdir}                       # fresh project\n"
            f"  ln -s /path/to/repo {pdir}         # symlink existing repo"
        )


def is_already_registered(slug: str) -> bool:
    p = workspace() / REGISTRY_PATH_REL
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    return slug in data.get("projects", {})


def create_dirs(slug: str, created: list, skipped: list) -> None:
    pdir = project_dir(slug)
    for d in PROJECT_ROOT_DIRS:
        path = pdir / d
        if path.exists():
            skipped.append(f"projects/{slug}/{d}/ (exists)")
        else:
            if not is_dry_run():
                path.mkdir(parents=True, exist_ok=True)
            created.append(f"projects/{slug}/{d}/")
    claude_memory = pdir / ".claude/memory"
    if claude_memory.exists():
        skipped.append(f"projects/{slug}/.claude/memory/ (exists)")
    else:
        if not is_dry_run():
            claude_memory.mkdir(parents=True, exist_ok=True)
        created.append(f"projects/{slug}/.claude/memory/")


def write_starter(path: Path, content: str, label: str, created: list, skipped: list) -> None:
    if path.exists():
        skipped.append(f"{label} (exists)")
        return
    if not is_dry_run():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    created.append(label)


def deploy_starters(slug: str, created: list, skipped: list) -> None:
    pdir = project_dir(slug)
    starters_dir = workspace() / STARTERS_DIR_REL
    for src_name, dst_rel in STARTER_MAP:
        src = starters_dir / src_name
        if not src.is_file():
            die(
                f"starter missing at {src}\n"
                f"hint: re-run /setup-workspace init to redeploy."
            )
        write_starter(
            pdir / dst_rel,
            src.read_text(),
            f"projects/{slug}/{dst_rel}",
            created,
            skipped,
        )


MEMORY_SECTION_HEADING = "## Memory"
MEMORY_HEADING_RE = re.compile(r"(?m)^" + re.escape(MEMORY_SECTION_HEADING) + r"\s*$")


def extract_template_section(template_text: str, heading: str) -> str | None:
    """Extract one section from the project-CLAUDE.md template: the line
    matching `heading` up to (not including) the next Markdown heading line
    of any level. Returns None if `heading` isn't found. Kept generic (not
    hardcoded to Memory) so it stays correct if the template is reordered."""
    lines = template_text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == heading), None)
    if start is None:
        return None
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"^#{1,6}\s", lines[i])),
        len(lines),
    )
    return "\n".join(lines[start:end]).rstrip("\n") + "\n"


def generate_claude_md(
    slug: str, description: str, created: list, skipped: list, patched: list
) -> None:
    template = workspace() / PROJECT_TEMPLATE_REL
    dst = project_dir(slug) / "CLAUDE.md"
    if not template.is_file():
        die(f"template missing at {template}\nhint: re-run /setup-workspace init to redeploy.")
    template_text = template.read_text()

    if dst.exists():
        existing = dst.read_text()
        if CLAUDE_MD_MEMORY_INCLUDE in existing:
            skipped.append(f"projects/{slug}/CLAUDE.md (exists, Memory section present)")
            return
        if MEMORY_HEADING_RE.search(existing):
            # A '## Memory' heading already exists but isn't the Memnyx
            # include — could be the project's own, unrelated convention.
            # Appending our block would produce two same-named, conflicting
            # headings, so leave it alone and let a human reconcile it.
            skipped.append(
                f"projects/{slug}/CLAUDE.md (exists, has its own '## Memory' section — "
                f"add `{CLAUDE_MD_MEMORY_INCLUDE}` to it by hand if that's intended)"
            )
            return
        # Pre-existing CLAUDE.md (typical when symlinking to a real repo that
        # already has its own) predates or hand-wrote the Memory convention.
        # Never regenerate/overwrite a real file — surgically append just the
        # Memory section so the project still gets the MEMORY.md auto-load.
        memory_section = extract_template_section(template_text, MEMORY_SECTION_HEADING)
        if memory_section is None:
            die(
                f"template at {template} is missing a '{MEMORY_SECTION_HEADING}' heading\n"
                f"hint: re-run /setup-workspace init to redeploy the template."
            )
        if not is_dry_run():
            dst.write_text(existing.rstrip("\n") + "\n\n" + memory_section)
        patched.append(
            f"projects/{slug}/CLAUDE.md (merged in Memory section — pre-existing file preserved)"
        )
        return

    if not is_dry_run():
        content = template_text.replace("{{project_name}}", slug)
        content = content.replace("{{description}}", description or "")
        dst.write_text(content)
    created.append(f"projects/{slug}/CLAUDE.md")


def update_gitignore(slug: str, created: list, skipped: list) -> None:
    pdir = project_dir(slug)
    gi = pdir / ".gitignore"

    if gi.exists():
        existing_lines = gi.read_text().splitlines()
        existing_set = {line.strip() for line in existing_lines}
        missing = [p for p in GITIGNORE_PATTERNS if p not in existing_set]
        if not missing:
            skipped.append(f"projects/{slug}/.gitignore (all patterns present)")
            return
        if not is_dry_run():
            with gi.open("a") as f:
                if existing_lines and existing_lines[-1].strip() != "":
                    f.write("\n")
                f.write(f"\n{GITIGNORE_HEADER}\n")
                for p in missing:
                    f.write(f"{p}\n")
        n = len(missing)
        created.append(
            f"projects/{slug}/.gitignore (appended {n} pattern{'s' if n != 1 else ''})"
        )
    else:
        if not is_dry_run():
            with gi.open("w") as f:
                f.write(f"{GITIGNORE_HEADER}\n")
                for p in GITIGNORE_PATTERNS:
                    f.write(f"{p}\n")
        created.append(f"projects/{slug}/.gitignore")


def register(slug: str, description: str, created: list, skipped: list) -> None:
    if is_already_registered(slug):
        skipped.append(f"registry entry '{slug}' (already registered)")
        return
    if is_dry_run():
        created.append(f"registry entry '{slug}' (would call /project-registry add)")
        return
    script = workspace() / REGISTRY_SCRIPT_REL
    if not script.is_file():
        die(f"registry script missing at {script}\nhint: re-run /setup-workspace init to redeploy.")
    cmd = ["python3", str(script), "add", slug]
    if description:
        cmd.append(description)
    result = subprocess.run(cmd, cwd=str(workspace()), capture_output=True, text=True)
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip() or "registry add failed (no output)"
        die(f"registry add failed:\n{msg}")
    created.append(f"registry entry '{slug}'")


def print_summary(slug: str, created: list, skipped: list, patched: list) -> None:
    print()
    if is_dry_run():
        print("=== /setup-workspace add-project [DRY RUN] ===")
        print("(no files written; this is a preview)")
    else:
        print("=== /setup-workspace add-project complete ===")
    print(f"Project: {project_dir(slug)}")
    print()
    if created:
        verb = "Would create" if is_dry_run() else "Created"
        print(f"{verb} ({len(created)}):")
        for item in created:
            print(f"  + {item}")
    if patched:
        verb = "Would patch" if is_dry_run() else "Patched"
        print(f"\n{verb} ({len(patched)}):")
        for item in patched:
            print(f"  ~ {item}")
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
        print(
            f"  - Customise {project_dir(slug)}/CLAUDE.md "
            "(slug + description substituted; rest is template)."
        )
        print(f"  - Start working on it: refer to '{slug}' from this workspace.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scaffold a project under <workspace>/projects/<slug>/ and register it.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("slug", help="Project slug (lowercase + hyphens, must start with a letter).")
    parser.add_argument(
        "description",
        nargs="?",
        default="",
        help="Optional one-line description.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing anything.")
    return parser.parse_args()


def main() -> None:
    global _WORKSPACE, _DRY_RUN
    args = parse_args()
    _DRY_RUN = args.dry_run
    _WORKSPACE = find_workspace()

    validate_slug(args.slug)
    validate_project_dir_exists(args.slug)

    if _DRY_RUN:
        print("=== DRY RUN — nothing will be written ===\n")
    print(f"Workspace: {_WORKSPACE}")
    print(f"Slug:      {args.slug}")
    print(f"Project:   {project_dir(args.slug)}")
    print()

    created: list = []
    skipped: list = []
    patched: list = []

    create_dirs(args.slug, created, skipped)
    deploy_starters(args.slug, created, skipped)
    generate_claude_md(args.slug, args.description, created, skipped, patched)
    update_gitignore(args.slug, created, skipped)
    register(args.slug, args.description, created, skipped)
    print_summary(args.slug, created, skipped, patched)


if __name__ == "__main__":
    main()
