#!/usr/bin/env python3
"""Shared helpers for the setup-workspace scripts (init.py, sync.py, launcher.py).

Kept deliberately small: the marker-path constants, the error-exit helper, the
workspace/boilerplate detectors, and a single workspace resolver whose strictness
is parameterised (init may target a workspace that does not exist yet; sync and
launcher require an already-initialised one).
"""

from __future__ import annotations

import functools
import subprocess
import sys
from pathlib import Path

# Marker files that identify a workspace vs a boilerplate source clone.
WORKSPACE_MARKER_REL = ".claude/.workspace"
BOILERPLATE_MARKER_REL = ".claude/skills/setup-workspace/templates/workspace-CLAUDE.md.tmpl"


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def is_v2_workspace(p: Path) -> bool:
    return (p / WORKSPACE_MARKER_REL).is_file()


def is_v2_boilerplate(p: Path) -> bool:
    return (p / BOILERPLATE_MARKER_REL).is_file()


def resolve_workspace(workspace_arg: str, *, require_workspace: bool = True) -> Path:
    """Resolve a workspace path argument to an absolute Path.

    require_workspace=True  (sync, launcher): the path must be an existing,
        initialised workspace (has the .workspace marker).
    require_workspace=False (init): the workspace may not exist yet — init
        creates it — so only reject a path that exists but is not a directory.
    """
    p = Path(workspace_arg).expanduser().resolve()
    if not require_workspace:
        if p.exists() and not p.is_dir():
            die(f"workspace path is not a directory: {p}")
        return p
    if not p.is_dir():
        die(f"workspace path is not a directory: {p}")
    if not is_v2_workspace(p):
        die(f"{p} is not a v2 workspace (missing {WORKSPACE_MARKER_REL}). Run /setup-workspace init first.")
    return p


# --- CLAUDE.md layering (base / fork overlay / local overlay) --------------
#
# A workspace's CLAUDE.md is layered: an upstream base, an optional fork overlay
# (CLAUDE.fork.md), and a native CLAUDE.local.md. Whether a source ships a fork
# overlay is decided by git provenance — the actual definition of a fork — not by
# a flag or by the overlay's contents (which may be temporarily empty).

# owner/repo of the canonical Memnyx upstream; a source whose origin is this is
# canonical, anything else is a fork.
CANONICAL_REPO = "mdgrey33/memnyx"

# The fork overlay template ships WITH the skill (identical in Memnyx and forks):
# Memnyx ships a stub, a fork fills it. A fork overlay is "active" only when the
# source is a fork AND actually ships this template (see fork_overlay_active).
FORK_OVERLAY_TEMPLATE_REL = ".claude/skills/setup-workspace/templates/CLAUDE.fork.md.tmpl"

# Seed for the local overlay (CLAUDE.local.md). Managed by the layer logic —
# seeded if missing, never overwritten — NOT the generic starter walk, so seeding
# can be gated on the base being layered (avoids duplicating Conventions onto a
# not-yet-split monolith).
LOCAL_OVERLAY_SEED_REL = ".claude/skills/setup-workspace/templates/starters/workspace/CLAUDE.local.md"

# Injected into the base CLAUDE.md's "Layered overlays" section in place of the
# {{fork_overlay_include}} placeholder when a fork overlay is active; empty otherwise.
FORK_OVERLAY_INCLUDE_BLOCK = (
    "- **`CLAUDE.fork.md`** — fork-specific additions, owned by the boilerplate fork; "
    "overwritten from source on sync.\n\n@CLAUDE.fork.md\n"
)

# Marks a base CLAUDE.md as layered (vs a legacy monolith). Both init and sync gate
# overlay seeding on its presence, so it lives here, shared by one definition.
LAYERED_OVERLAYS_MARKER = "## Layered overlays"


def render_template(path: Path, workspace: Path) -> str:
    """Substitute the workspace placeholders in a template's text. One renderer
    shared by init and sync, so the base/fork/local files render identically."""
    return (
        path.read_text(encoding="utf-8")
        .replace("{{workspace_name}}", workspace.name)
        .replace("{{workspace_path}}", str(workspace))
    )


def _normalize_repo(url: str) -> str:
    """Reduce a git remote URL to a lowercase `owner/repo`, ignoring protocol,
    host, and a trailing `.git` (handles both https and scp-style ssh URLs)."""
    u = url.strip()
    if u.endswith(".git"):
        u = u[:-4]
    u = u.replace(":", "/")  # git@github.com:owner/repo -> .../owner/repo
    parts = [p for p in u.split("/") if p]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else u.lower()


@functools.lru_cache(maxsize=None)
def classify_source(source: Path) -> str:
    """'canonical' if the source's git `origin` is the canonical Memnyx repo,
    'fork' if it resolves to any other repo, or 'unknown' if the origin can't be
    read (not a git clone, git unavailable, lookup times out). Cached — the origin
    is invariant for the process. Callers MUST NOT coerce 'unknown' into a layer
    mutation: an unreadable origin on a canonical workspace must not silently flip
    it to fork shape (see reconcile_claude_layers)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return "canonical" if _normalize_repo(result.stdout) == CANONICAL_REPO else "fork"


def source_is_fork(source: Path) -> bool:
    """True only when the source is provably a fork. 'unknown' is not a fork — at
    init that means no overlay is deployed (safe default on a fresh workspace)."""
    return classify_source(source) == "fork"


def fork_overlay_active(source: Path) -> bool:
    """A fork overlay is active only when the source is a fork AND ships the
    overlay template — so the base never gets an `@CLAUDE.fork.md` include for a
    file that would never be created."""
    return source_is_fork(source) and (source / FORK_OVERLAY_TEMPLATE_REL).is_file()


def fork_include_block(source: Path) -> str:
    return FORK_OVERLAY_INCLUDE_BLOCK if fork_overlay_active(source) else ""
