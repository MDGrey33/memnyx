#!/usr/bin/env python3
"""Skill-table parity check.

Guards against the drift that the post-merge adversarial review caught: the
on-disk skill set and the skill tables in the user-facing docs getting out of
sync (a dead row pointing at a deleted skill, or a real skill missing from a
table). Three doc surfaces must together account for EXACTLY the skills on disk:

  - README.md                                              (Skills Reference table)
  - CLAUDE.md                                              (Available Skills table)
  - .claude/skills/setup-workspace/templates/
        workspace-CLAUDE.md.tmpl                           (generated-workspace table)

The third is the one the original reconciliation missed — init.py emits it
verbatim as every fresh workspace's CLAUDE.md, so a stale table there ships
straight to users.

Fork overlay: a fork carries its added skills in CLAUDE.fork.md rather than
repeating them in every base table, and each workspace `@`-includes that overlay
alongside its base CLAUDE.md. So a surface counts as complete when its own rows
UNION the overlay's rows cover the disk set — a base table may list upstream
skills only and lean on CLAUDE.fork.md for the fork's. Canonical memnyx has no
CLAUDE.fork.md, so its union is empty and the check reduces to base-table equality
(unchanged). Dead rows (a documented slug with no skill) are still attributed to
whichever file carries them, the overlay included.

Run: python3 scripts/check_skill_tables.py
Exit 0 if every surface (unioned with CLAUDE.fork.md) accounts for the on-disk
skill set with no dead rows; exit 1 (with a diff) otherwise. Wired into CI via
.github/workflows/skill-table-parity.yml.

Convention: directories under .claude/skills/ whose name starts with "_"
(e.g. _shared/) are shared assets, not skills, and are excluded.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"

# Doc surfaces whose rows, unioned with the fork overlay, must account for the disk set.
DOC_SURFACES = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "CLAUDE.md",
    SKILLS_DIR / "setup-workspace" / "templates" / "workspace-CLAUDE.md.tmpl",
]

# Fork overlay — present only in a fork; its rows count toward every surface's
# completeness. Absent in canonical memnyx (union contributes the empty set).
FORK_OVERLAY = REPO_ROOT / "CLAUDE.fork.md"

# Matches a markdown table row whose first cell is a slash command, e.g.
#   | `/setup-voice` | Manual | ... |
TABLE_ROW = re.compile(r"^\|\s*`/([a-z0-9][a-z0-9-]*)`\s*\|")


def disk_skills() -> set[str]:
    return {
        p.name
        for p in SKILLS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith("_") and (p / "SKILL.md").is_file()
    }


def table_slugs(doc: Path) -> set[str]:
    if not doc.is_file():
        return set()
    return {
        m.group(1)
        for line in doc.read_text().splitlines()
        if (m := TABLE_ROW.match(line))
    }


def main() -> int:
    disk = disk_skills()
    if not disk:
        print(f"error: no skills found under {SKILLS_DIR}", file=sys.stderr)
        return 1

    fork_slugs = table_slugs(FORK_OVERLAY)  # empty set when absent (canonical memnyx)

    ok = True
    print(f"On-disk skills ({len(disk)}): {', '.join(sorted(disk))}\n")
    if fork_slugs:
        print(f"Fork overlay (CLAUDE.fork.md) contributes: {', '.join(sorted(fork_slugs))}\n")
    for doc in DOC_SURFACES:
        rel = doc.relative_to(REPO_ROOT)
        own = table_slugs(doc)
        missing = disk - (own | fork_slugs)   # completeness: own rows + overlay must cover disk
        extra = own - disk                     # dead rows attributed to the surface that carries them
        if missing or extra:
            ok = False
            print(f"✗ {rel}")
            if missing:
                print(f"    MISSING (not in this table or CLAUDE.fork.md): {', '.join(sorted(missing))}")
            if extra:
                print(f"    DEAD rows (no skill): {', '.join(sorted(extra))}")
        elif fork_slugs:
            print(f"✓ {rel} ({len(own)} own rows, complete with CLAUDE.fork.md)")
        else:
            print(f"✓ {rel} ({len(own)} skills, matches disk)")

    fork_extra = fork_slugs - disk             # dead rows in the overlay itself
    if fork_extra:
        ok = False
        print("✗ CLAUDE.fork.md")
        print(f"    DEAD rows (no skill): {', '.join(sorted(fork_extra))}")

    if not ok:
        print("\nSkill tables are out of sync with the on-disk skill set.", file=sys.stderr)
        return 1
    print("\nAll skill tables match the on-disk skill set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
