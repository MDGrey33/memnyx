"""levers.py — the remediation levers in one snapshot. Pure arithmetic.

Turns the current findings into a short list of changes, each with who acts,
where, and how many critical+high findings it removes. The ranking is
findings removed; the order of work is the team's call, not this module's.

Reads one snapshot dict shaped like movement.py's. No I/O, no clock. A block
the snapshot lacks gives a lever of None, never an empty lever: an empty one
reads as "nothing to do".
"""
from __future__ import annotations

LAYERS_SHOWN = 10
# A layer in at least this many repos is a base image. Layers in one repo are
# the service's own (its dependencies, its apt installs), which the dependency
# lever already counts, so they are left out rather than promised twice.
SHARED_LAYER_MIN_REPOS = 2
ROWS_SHOWN = 15

LEVERS = {
    "kernel_headers": {
        "title": "Remove kernel headers from runtime images",
        "owner": "service team, per Dockerfile",
        "action": ("Run on the slim variant of the base image and drop compilers and -dev packages from the "
                   "runtime image; build in a separate stage only where a dependency compiles from source. "
                   "Rebuilding on a current base closes the findings that have a fixed version, and new kernel "
                   "advisories reopen them."),
    },
    "bundled_runtimes": {
        "title": "Bump bundled runtimes and binaries",
        "owner": "service team or base image owner",
        "action": "Move to a base image or tool version that ships the fixed runtime; a rebuild on the same tag does not change them.",
    },
    "base_layers": {
        "title": "Refresh shared base images",
        "owner": "base image owner",
        "action": ("Rebuild the shared base on a current tag, or move it to slim, then rebuild the repos on it. "
                   "One change reaches every repo listed."),
    },
    "dependabot_dependencies": {
        "title": "Bump the packages Dependabot also flags",
        "owner": "service team",
        "action": "Inspector finds these in the images and Dependabot in the source. Bump them in the service; a Dependabot PR may already be open.",
    },
}


def _get(snap, *path):
    o = snap
    for k in path:
        if not isinstance(o, dict) or k not in o:
            return None
        o = o[k]
    return o


def _pct(part, whole):
    return round(100 * part / whole, 1) if whole else None


def _lever(key, removes, rows, **extra):
    return {"key": key, **LEVERS[key], "removes_ch": removes, "rows": rows, **extra}


def _breakdown_rows(curr):
    b = _get(curr, "raw", "package_breakdown")
    if not isinstance(b, dict) or b.get("status") != "ok" or not isinstance(b.get("rows"), list):
        return None
    return b["rows"]


def kernel_headers(rows, kernel_packages):
    """Per repo: findings, images, OS, header versions, share with a fixed version."""
    by_repo = {}
    for r in rows:
        if r["package"] not in kernel_packages:
            continue
        x = by_repo.setdefault(r["repo"], {"repo": r["repo"], "ch": 0, "fix_available": 0, "images": 0,
                                           "platforms": set(), "versions": set()})
        x["ch"] += r["ch"]
        x["fix_available"] += r["fix_available"]
        x["images"] = max(x["images"], r["images"])  # the same images carry several header packages
        x["platforms"].update(r.get("platforms") or [])
        x["versions"].update(r.get("versions") or [])
    out = sorted(by_repo.values(), key=lambda x: (-x["ch"], x["repo"]))
    for x in out:
        x["platforms"], x["versions"] = sorted(x["platforms"]), sorted(x["versions"])
        x["fix_pct"] = _pct(x["fix_available"], x["ch"])
    total = sum(x["ch"] for x in out)
    return _lever("kernel_headers", total, out[:ROWS_SHOWN], repos=len(out),
                  fix_pct=_pct(sum(x["fix_available"] for x in out), total))


def bundled_runtimes(rows, kernel_packages):
    """Per package: findings, the repos that carry it, share with a fixed version."""
    by_pkg = {}
    for r in rows:
        if r["package"] in kernel_packages:
            continue
        x = by_pkg.setdefault(r["package"], {"package": r["package"], "ch": 0, "fix_available": 0, "repos": []})
        x["ch"] += r["ch"]
        x["fix_available"] += r["fix_available"]
        x["repos"].append(r["repo"])
    out = sorted(by_pkg.values(), key=lambda x: (-x["ch"], x["package"]))
    for x in out:
        x["repos"] = sorted(set(x["repos"]))
        x["fix_pct"] = _pct(x["fix_available"], x["ch"])
    total = sum(x["ch"] for x in out)
    return _lever("bundled_runtimes", total, out[:ROWS_SHOWN],
                  fix_pct=_pct(sum(x["fix_available"] for x in out), total))


def base_layers(curr, rows):
    """Shared base layers ranked by critical+high, net of findings the kernel-header and
    bundled-runtime levers already count.

    Without the breakdown the gross count is shown and says so: the same
    findings would otherwise be promised by two levers.
    """
    layers, complete = _get(curr, "raw", "layers"), True
    if not isinstance(layers, list):
        layers, complete = _get(curr, "raw", "base_layers"), False
        # Snapshots with the full list write layers=None only when the layer
        # capture failed (an optional aggregation returns nothing, never a
        # partial list), leaving base_layers empty: that is no data, not zero.
        if not layers:
            return None
    if not isinstance(layers, list):
        return None
    counted = {}
    for r in rows or []:
        for l in r.get("layers") or []:
            counted[l["layer"]] = counted.get(l["layer"], 0) + l["ch"]
    out = []
    for l in layers:
        gross = (l.get("c") or 0) + (l.get("h") or 0)
        net = gross - counted.get(l["layer"], 0)
        if net > 0 and len(l.get("repo_list") or []) >= SHARED_LAYER_MIN_REPOS:
            out.append({"layer": l["layer"], "ch": net, "gross_ch": gross, "images": l.get("images"),
                        "repos": len(l.get("repo_list") or []), "repo_list": l.get("repo_list") or []})
    out.sort(key=lambda x: (-x["ch"], x["layer"]))
    shown = out[:LAYERS_SHOWN]
    return _lever("base_layers", sum(x["ch"] for x in out), shown, net_of_other_levers=rows is not None,
                  layers_total=len(out), complete=complete)


def dependabot_dependencies(curr, managers, application_managers):
    """Application packages Inspector flags that Dependabot also flags, by critical+high.

    Each row also carries the GitHub side of the overlap: the package's critical +
    high Dependabot alerts and the repos they are in (None when not captured)."""
    zone = _get(curr, "correlation", "correlation", "zone_a_pkg_overlap")
    pkgs = _get(curr, "raw", "packages")
    if not isinstance(zone, list) or not isinstance(pkgs, list):
        return None
    by_name = {z["package"]: z for z in zone if z.get("package")}
    out = []
    for p in pkgs:
        a = p.get("packageAggregation") or {}
        n = a.get("packageName")
        if n in by_name and (managers or {}).get(n) in application_managers:
            sc = a.get("severityCounts") or {}
            ch = (sc.get("critical") or 0) + (sc.get("high") or 0)
            if ch:
                z = by_name[n]
                gh = (None if z.get("gh_crit") is None and z.get("gh_high") is None
                      else (z.get("gh_crit") or 0) + (z.get("gh_high") or 0))
                out.append({"package": n, "ch": ch, "manager": managers[n], "gh_ch": gh, "gh_repos": z.get("gh_repos")})
    out.sort(key=lambda x: (-x["ch"], x["package"]))
    return _lever("dependabot_dependencies", sum(x["ch"] for x in out), out[:ROWS_SHOWN], packages=len(out))


def node_evidence(curr):
    """Host kernel exposure, or an explicit "not measured"; never a bare zero."""
    n = _get(curr, "raw", "node_scan")
    if not isinstance(n, dict) or n.get("status") != "ok":
        return None
    if not n.get("instances_scanned"):
        state = "no_hosts_scanned"
    elif not n.get("package_findings"):
        state = "not_measured"
    else:
        state = "measured"
    rel = _get(curr, "raw", "node_os")
    release = None
    if isinstance(rel, dict) and rel.get("status") == "ok" and isinstance(rel.get("nodes"), list):
        release = {"nodes": rel["nodes"], "other_instances": rel.get("other_instances"),
                   "behind": sum(x.get("instances") or 0 for x in rel["nodes"] if x.get("on_latest") is False)}
    return {"state": state, "instances_scanned": n.get("instances_scanned"), "kernel_ch": n.get("kernel_ch"),
            "platforms": [p["platform"] for p in n.get("platforms") or []], "release": release}


def remediation_levers(curr, managers, kernel_packages, application_managers):
    """Every lever the snapshot can support, largest first, plus the host evidence."""
    rows = _breakdown_rows(curr)
    levers = []
    if rows is not None:
        levers += [kernel_headers(rows, kernel_packages), bundled_runtimes(rows, kernel_packages)]
    levers += [base_layers(curr, rows), dependabot_dependencies(curr, managers, application_managers)]
    levers = [l for l in levers if l is not None]
    levers.sort(key=lambda l: -l["removes_ch"])
    total = _get(curr, "raw", "account_totals")
    total_ch = None
    if isinstance(total, dict) and isinstance(total.get("critical"), int) and isinstance(total.get("high"), int):
        total_ch = total["critical"] + total["high"]
    for l in levers:
        l["share_pct"] = _pct(l["removes_ch"], total_ch)
    b = _get(curr, "raw", "package_breakdown")
    return {"levers": levers, "total_ch": total_ch, "nodes": node_evidence(curr),
            "breakdown_status": b.get("status") if isinstance(b, dict) else None}
