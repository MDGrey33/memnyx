#!/usr/bin/env python3
"""emit_movement.py — the only file in the movement feature that touches disk.

Reads two snapshot folders, hands them to movement.py and movement_markdown.py,
and writes <reports-dir>/<date>/movement.md (against the previous snapshot) and
movement-vs-<basis>.md (against the 30-day basis, when that is a different
snapshot). Everything below the generated marker in an existing file survives.

Usage:
    emit_movement.py --reports-dir <dir> [--date YYYYMMDD] [--compare-to YYYYMMDD]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from movement import security_movement  # noqa: E402
from movement_markdown import render_movement_markdown  # noqa: E402

FILES = {"raw": "raw.json", "github": "github-raw.json", "snapshot": "snapshot.json", "correlation": "correlation.json"}
LONG_BASIS_DAYS = 30


def _d(s):
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def long_basis(dates, target, days=LONG_BASIS_DAYS):
    """Newest snapshot at least `days` before target, or None."""
    cutoff = _d(target) - timedelta(days=days)
    earlier = [d for d in dates if d < target and _d(d) <= cutoff]
    return earlier[-1] if earlier else None


def resolve_targets(dates, target=None, compare_to=None):
    """Which pairs to compare and what each output is called. Pure.

    Returns {"error": ...}, {"skip": ...}, or {"date": d, "pairs": [(basis, filename), ...]}.
    The default basis writes movement.md; any other basis gets its own file,
    because written notes below the marker would otherwise end up under a
    different comparison's numbers.
    """
    dates = sorted(dates)
    if not dates:
        return {"error": "no snapshots found"}
    target = target or dates[-1]
    if target not in dates:
        return {"error": f"snapshot {target} not found"}
    i = dates.index(target)
    default = dates[i - 1] if i > 0 else None
    if compare_to:
        if compare_to not in dates:
            return {"error": f"comparison snapshot {compare_to} not found"}
        if compare_to >= target:
            return {"error": f"comparison snapshot {compare_to} is not before {target}"}
        return {"date": target, "pairs": [(compare_to, "movement.md" if compare_to == default else f"movement-vs-{compare_to}.md")]}
    if default is None:
        return {"skip": f"{target} is the first snapshot; nothing to compare"}
    pairs = [(default, "movement.md")]
    lb = long_basis(dates, target)
    if lb and lb != default:
        pairs.append((lb, f"movement-vs-{lb}.md"))
    return {"date": target, "pairs": pairs}


def load(folder: Path):
    out = {}
    for key, name in FILES.items():
        p = folder / name
        try:
            out[key] = json.loads(p.read_text()) if p.exists() else None
        except ValueError as e:
            print(f"warning: {p} unreadable ({e}); treated as missing", file=sys.stderr)
            out[key] = None
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reports-dir", required=True, type=Path)
    ap.add_argument("--date")
    ap.add_argument("--compare-to")
    args = ap.parse_args(argv)
    dates = [p.name for p in args.reports_dir.iterdir()
             if p.is_dir() and p.name.isdigit() and len(p.name) == 8 and (p / "raw.json").exists()]
    plan = resolve_targets(dates, args.date, args.compare_to)
    if "error" in plan:
        print(f"error: {plan['error']}", file=sys.stderr)
        return 1
    if "skip" in plan:
        print(plan["skip"])
        return 0
    curr = load(args.reports_dir / plan["date"])
    for basis, fname in plan["pairs"]:
        mv = security_movement(load(args.reports_dir / basis), curr, basis, plan["date"])
        out = args.reports_dir / plan["date"] / fname
        prior = out.read_text() if out.exists() else ""
        out.write_text(render_movement_markdown(mv, prior))
        print(f"✓ {out} ({plan['date']} vs {basis}; {len(mv['data_quality'])} data-quality flag(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
