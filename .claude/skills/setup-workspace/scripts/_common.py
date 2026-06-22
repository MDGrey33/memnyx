#!/usr/bin/env python3
"""Shared helpers for the setup-workspace scripts (init.py, sync.py, launcher.py).

Kept deliberately small: the marker-path constants, the error-exit helper, the
workspace/boilerplate detectors, and a single workspace resolver whose strictness
is parameterised (init may target a workspace that does not exist yet; sync and
launcher require an already-initialised one).
"""

from __future__ import annotations

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
