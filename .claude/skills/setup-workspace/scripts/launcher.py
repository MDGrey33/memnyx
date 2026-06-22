#!/usr/bin/env python3
"""Install the `mmn` shell launcher for a memnyx workspace.

Usage:
    launcher.py --workspace <path> [--wire-profile] [--profile <path>]
                [--shell <name>] [--dry-run]

Two stages, separated so profile editing is opt-in (the agent gets the user's
consent before touching a shell profile):

1. Always: write `<workspace>/shell/memnyx.sh` from the template, substituting
   the workspace path. This file is a DERIVED artifact — overwritten on every
   run (and on `/setup-workspace sync`), so never hand-edit it.

2. With --wire-profile: insert/refresh a delimited managed block in the user's
   shell profile that sources memnyx.sh. Idempotent — the block between markers
   is replaced, never duplicated. A one-time backup of the profile is written
   before the first edit.

Shell detection picks a sensible default profile (zsh -> ~/.zshrc, bash ->
~/.bashrc, otherwise ~/.profile). Override with --profile when the user's setup
differs (e.g. macOS login bash reading ~/.bash_profile). memnyx.sh itself is
POSIX-safe, so any of these can source it.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 10):
    sys.exit(
        f"Python 3.10+ required (detected {sys.version_info.major}.{sys.version_info.minor})."
    )

import argparse
import os
import shlex
import shutil
from pathlib import Path

from _common import die, resolve_workspace

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "memnyx.sh.tmpl"
MEMNYX_SH_REL = "shell/memnyx.sh"

BEGIN = "# >>> memnyx >>> (managed by /setup-workspace — do not edit between these markers)"
END = "# <<< memnyx <<<"


def write_memnyx_sh(workspace: Path, dry_run: bool) -> Path:
    """Write <workspace>/shell/memnyx.sh from the template. Derived — overwrite."""
    if not TEMPLATE.is_file():
        die(f"template missing at {TEMPLATE} — re-clone the source")
    raw = TEMPLATE.read_text()
    if "{{workspace_path}}" not in raw:
        die(f"template {TEMPLATE} is missing the {{{{workspace_path}}}} token — refusing to write a launcher with an unset workspace path")
    # shlex.quote → the template must NOT pre-quote the token (it doesn't).
    content = raw.replace("{{workspace_path}}", shlex.quote(str(workspace)))
    dst = workspace / MEMNYX_SH_REL
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content)
    return dst


def managed_block(workspace: Path) -> str:
    sh = shlex.quote(str(workspace / MEMNYX_SH_REL))
    return f"{BEGIN}\n[ -f {sh} ] && . {sh}\n{END}\n"


def detect_profile(shell_arg: str | None) -> tuple[str, Path]:
    shell = shell_arg or os.path.basename(os.environ.get("SHELL", "")) or "sh"
    home = Path.home()
    if shell == "zsh":
        return shell, home / ".zshrc"
    if shell == "bash":
        return shell, home / ".bashrc"
    return shell, home / ".profile"


def wire_profile(profile: Path, workspace: Path, dry_run: bool) -> str:
    """Insert or refresh the managed block in `profile`. Returns an action word."""
    block = managed_block(workspace)
    existing = profile.read_text() if profile.exists() else ""

    has_begin, has_end = BEGIN in existing, END in existing
    if has_begin != has_end:
        # A partial block (one marker without the other) means a botched earlier
        # edit. Appending would leave a malformed, un-refreshable block — refuse
        # and let the user repair it rather than corrupt the profile further.
        stray = BEGIN if has_begin else END
        die(
            f"{profile} has a partial memnyx block: found '{stray}' without its pair. "
            f"Remove that line (or restore {profile.name}.memnyx-backup) and re-run."
        )

    if has_begin and has_end:
        head = existing.split(BEGIN, 1)[0]
        tail = existing.split(END, 1)[1]
        new = head.rstrip("\n") + ("\n\n" if head.strip() else "") + block + tail.lstrip("\n")
        action = "refreshed"
        if new == existing:
            return "unchanged"
    else:
        sep = "" if existing == "" or existing.endswith("\n") else "\n"
        new = existing + sep + ("\n" if existing.strip() else "") + block
        action = "added"

    if not dry_run:
        if profile.exists():
            backup = profile.with_name(profile.name + ".memnyx-backup")
            if not backup.exists():
                shutil.copy2(profile, backup)
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text(new)
    return action


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Install the mmn shell launcher.")
    p.add_argument("--workspace", required=True)
    p.add_argument("--wire-profile", action="store_true", help="Also edit the shell profile (needs user consent).")
    p.add_argument("--profile", help="Profile file to wire. Overrides shell-based detection.")
    p.add_argument("--shell", help="Shell name (zsh/bash/...). Defaults to $SHELL.")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ws = resolve_workspace(args.workspace)
    dry = args.dry_run

    if dry:
        print("=== DRY RUN — nothing will be written ===\n")

    sh = write_memnyx_sh(ws, dry)
    verb = "Would write" if dry else "Wrote"
    print(f"{verb}: {sh}")

    shell, default_profile = detect_profile(args.shell)
    profile = Path(args.profile).expanduser() if args.profile else default_profile

    if args.wire_profile:
        action = wire_profile(profile, ws, dry)
        verb = "Would update" if dry else "Updated"
        print(f"{verb} profile ({shell}): {profile}  [{action}]")
        print("Open a new terminal (or `. " + str(profile) + "`) to pick up `mmn`.")
    else:
        print(f"\nDetected shell: {shell}  ->  {profile}")
        print("Not wired yet. To enable `mmn`, add this to your profile (or re-run with --wire-profile):\n")
        print(managed_block(ws).rstrip())
        print()

    print("Usage once active:")
    print("  mmn            launch in the current folder + workspace")
    print("  mmn <slug>     jump to a registered project's clone, then launch")


if __name__ == "__main__":
    main()
