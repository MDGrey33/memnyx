"""movement.py — what moved between two security snapshots. Pure arithmetic.

Answers "what moved" deterministically and never "why": the cause is the
agent's job (SKILL.md, Explain the movement). No I/O, no clock. Every function
takes two snapshot dicts shaped {"raw": ..., "github": ..., "snapshot": ...,
"correlation": ...}, any of which may be None, and is null-safe: the schema
grows over time and older snapshots genuinely lack whole blocks.

The cardinal rule: a value that is absent is None, never 0. Writing 0 into a
history that predates a metric invents a fall that never happened.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from levers import remediation_levers

# A headline count that rises by at least this percent is flagged for a capture
# check before anyone explains it. Rises only: a fall to zero is what finished
# remediation looks like, and an empty fetch is a collector problem this
# report cannot tell apart from it.
OUTLIER_PCT = 100

# Critical counts are small, so a percentage alone fires on a handful of
# alerts; a critical metric must also rise by at least this many to flag.
CRITICAL_OUTLIER_MIN_DELTA = 25

DEFAULT_MOVER_LIMIT = 10

# Kernel and kernel-header packages. In a container they are build headers,
# not a running kernel, and they leave the image when it stops carrying a
# toolchain. posture_snapshot imports this; the reverse would need boto3.
KERNEL_PACKAGES = {"linux", "linux-libc-dev", "linux-headers"}

# The single place field paths live. `sum` metrics go None if ANY part is
# missing — a partial sum understates and reads as a fall.
METRICS = [
    {"key": "inspector_ch", "label": "Inspector critical + high", "headline": True,
     "sum": [("raw", "account_totals", "critical"), ("raw", "account_totals", "high")]},
    {"key": "inspector_critical", "label": "Inspector critical", "headline": True,
     "outlier_min_delta": CRITICAL_OUTLIER_MIN_DELTA, "path": ("raw", "account_totals", "critical")},
    {"key": "inspector_high", "label": "Inspector high", "path": ("raw", "account_totals", "high")},
    {"key": "inspector_medium", "label": "Inspector medium", "path": ("raw", "account_totals", "medium")},
    {"key": "ecr_covered", "label": "ECR images covered", "path": ("raw", "coverage", "AWS_ECR_CONTAINER_IMAGE")},
    {"key": "ec2_covered", "label": "EC2 instances covered", "path": ("raw", "coverage", "AWS_EC2_INSTANCE")},
    {"key": "lambda_covered", "label": "Lambda functions covered", "path": ("raw", "coverage", "AWS_LAMBDA_FUNCTION")},
    {"key": "unique_cves", "label": "Distinct Inspector CVE titles", "path": ("raw", "title_stats", "unique_count")},
    {"key": "gh_vuln_total", "label": "Dependabot alerts (open)", "headline": True, "path": ("snapshot", "github", "vuln_total")},
    {"key": "gh_vuln_critical", "label": "Dependabot critical", "headline": True,
     "outlier_min_delta": CRITICAL_OUTLIER_MIN_DELTA, "path": ("snapshot", "github", "vuln_critical")},
    {"key": "gh_code_total", "label": "Code scanning alerts (open)", "path": ("snapshot", "github", "code_total")},
    {"key": "gh_secrets_total", "label": "Secret scanning alerts (open)", "headline": True, "path": ("snapshot", "github", "secrets_total")},
    {"key": "zone_a_pkgs", "label": "Packages flagged by both sources", "headline": True, "path": ("snapshot", "correlation", "zone_a_pkgs")},
]


_METRIC = {m["key"]: m for m in METRICS}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _get(snap, path):
    o = snap
    for k in path:
        if not isinstance(o, dict) or k not in o:
            return None
        o = o[k]
    return o


def read_metric(snap, metric):
    if "sum" in metric:
        parts = [_num(_get(snap, p)) for p in metric["sum"]]
        return None if any(p is None for p in parts) else sum(parts)
    return _num(_get(snap, metric["path"]))


def _pct(prev, curr):
    if prev is None or curr is None or prev == 0:
        return None
    return round(100 * (curr - prev) / prev, 1)


def count_movements(prev, curr):
    out = []
    for m in METRICS:
        p, c = read_metric(prev, m), read_metric(curr, m)
        comparable = p is not None and c is not None
        out.append({"key": m["key"], "label": m["label"], "headline": m.get("headline", False),
                    "prev": p, "curr": c, "comparable": comparable,
                    "delta": (c - p) if comparable else None, "pct": _pct(p, c) if comparable else None})
    return out


# ── Inspector ────────────────────────────────────────────────────────────────

def _ch(counts):
    counts = counts or {}
    return (counts.get("critical") or 0) + (counts.get("high") or 0)


def _repos(snap):
    rows = _get(snap, ("raw", "repositories"))
    if not isinstance(rows, list):
        return None
    out = {}
    for r in rows:
        a = r.get("repositoryAggregation") or {}
        if a.get("repository"):
            out[a["repository"]] = {"ch": _ch(a.get("severityCounts")), "images": a.get("affectedImages") or 0}
    return out


def inspector_decomposition(prev, curr):
    """ECR critical+high = images with findings × critical+high per image.

    An identity, so it holds whatever the cause: it says which way to look,
    not why. A count moves when inventory changes as much as when risk does.
    The remainder (EC2, Lambda) is reported beside it, not folded in.
    """
    rp, rc = _repos(prev), _repos(curr)
    if rp is None or rc is None:
        return None

    def side(repos, snap):
        ch = sum(v["ch"] for v in repos.values())
        images = sum(v["images"] for v in repos.values())
        acct = read_metric(snap, _METRIC["inspector_ch"])
        return {"ecr_ch": ch, "images": images, "per_image": round(ch / images, 1) if images else None,
                "non_ecr_ch": (acct - ch) if acct is not None else None}

    p, c = side(rp, prev), side(rc, curr)
    ratio = lambda a, b: round(b / a, 3) if a and b is not None else None  # noqa: E731
    return {"prev": p, "curr": c,
            "images_ratio": ratio(p["images"], c["images"]),
            "per_image_ratio": ratio(p["per_image"], c["per_image"]),
            "ecr_ch_ratio": ratio(p["ecr_ch"], c["ecr_ch"])}


def held_layers(prev, curr):
    """Base layers present in both snapshots with an unchanged image count.

    The same digest is the same layer content, so findings moving on a held
    layer are new detections against unchanged software, not fan-out. Snapshots
    taken before the full `layers` list existed hold only the top layers; the
    check then covers that subset and says so (`complete` is False).
    """
    full_p, full_c = _get(prev, ("raw", "layers")), _get(curr, ("raw", "layers"))
    complete = isinstance(full_p, list) and isinstance(full_c, list)
    lp, lc = (full_p, full_c) if complete else (_get(prev, ("raw", "base_layers")), _get(curr, ("raw", "base_layers")))
    # A failed layer capture writes layers=None and leaves base_layers empty:
    # that is no data, not zero held layers (levers.base_layers reads it the same way).
    if not isinstance(lp, list) or not isinstance(lc, list) or (not complete and not (lp and lc)):
        return None
    cur = {x.get("layer"): x for x in lc}
    held = []
    for x in lp:
        y = cur.get(x.get("layer"))
        if y and x.get("images") == y.get("images"):
            held.append({"layer": x["layer"], "images": x.get("images"),
                         "prev_ch": (x.get("c") or 0) + (x.get("h") or 0),
                         "curr_ch": (y.get("c") or 0) + (y.get("h") or 0),
                         "repos": y.get("repo_list") or []})
    pc, cc = sum(h["prev_ch"] for h in held), sum(h["curr_ch"] for h in held)
    held.sort(key=lambda h: -(h["curr_ch"] - h["prev_ch"]))
    # A layer whose findings fall to zero leaves the list, exactly like a layer
    # whose images were all deleted. The control cannot tell the two apart, so
    # it reports what left rather than counting it either way.
    left = [x for x in lp if x.get("layer") not in cur] if complete else []
    return {"layers": held, "prev_ch": pc, "curr_ch": cc, "pct": _pct(pc, cc) if held else None,
            "captured_prev": len(lp), "captured_curr": len(lc), "complete": complete,
            "left_layers": len(left), "left_prev_ch": sum((x.get("c") or 0) + (x.get("h") or 0) for x in left)}


def repo_image_stability(prev, curr):
    """Repos whose image count did not change. Context only.

    An unchanged count is NOT unchanged images: retention swaps rebuilt images
    in while the count holds. The control for new detections on unchanged
    images is first_seen.ecr.existing_images, or held_layers above.
    """
    rp, rc = _repos(prev), _repos(curr)
    if rp is None or rc is None:
        return None
    same = [k for k in rp if k in rc and rp[k]["images"] == rc[k]["images"]]
    pc, cc = sum(rp[k]["ch"] for k in same), sum(rc[k]["ch"] for k in same)
    return {"repos": len(same), "images": sum(rp[k]["images"] for k in same),
            "prev_ch": pc, "curr_ch": cc, "pct": _pct(pc, cc) if same else None}


def _packages(snap):
    rows = _get(snap, ("raw", "packages"))
    if not isinstance(rows, list):
        return None
    out = {}
    for r in rows:
        a = r.get("packageAggregation") or {}
        if a.get("packageName"):
            out[a["packageName"]] = _ch(a.get("severityCounts"))
    return out


def _zone_a_packages(snap):
    rows = _get(snap, ("correlation", "correlation", "zone_a_pkg_overlap"))
    return {r.get("package") for r in rows if r.get("package")} if isinstance(rows, list) else None


# Groups are named by the action that fixes them, so each line of the report
# says who acts. Order is report order.
GROUPS = {
    "kernel headers": "Remove from runtime images: slim base, no compilers or -dev packages in the final stage.",
    "OS packages": "Rebuild on a refreshed base image, or move to slim/distroless.",
    "bundled runtimes and binaries": "Bump the base image version; a rebuild on the same tag does not change them.",
    "application dependencies": "Bump the dependency in the service.",
    "unknown": "No package manager captured for this package.",
}
APPLICATION_MANAGERS = {"NODE", "PYTHON", "JAR", "GOBINARY", "GO", "GEMSPEC", "GEM", "NUGET", "POM", "POETRY",
                        "PIPENV", "NPM", "YARN", "PNPM", "CARGO", "COMPOSER", "CONAN", "GRADLE", "PIP"}


def _managers(snap):
    rows = _get(snap, ("raw", "package_managers"))
    if not isinstance(rows, list):
        return None
    return {r.get("package"): r.get("manager") for r in rows if isinstance(r, dict) and r.get("package")}


def package_group(name, managers):
    """The action group for a package. Kernel names win over their OS manager."""
    if name in KERNEL_PACKAGES:
        return "kernel headers"
    m = (managers or {}).get(name)
    if m is None:
        return "unknown"
    if m == "OS":
        return "OS packages"
    if m == "GENERIC":
        return "bundled runtimes and binaries"
    return "application dependencies" if m in APPLICATION_MANAGERS else "unknown"


def _merged_managers(prev, curr):
    """Both snapshots' package-manager maps, the current one winning; None when neither has one."""
    mp, mc = _managers(prev), _managers(curr)
    return None if mp is None and mc is None else {**(mp or {}), **{k: v for k, v in (mc or {}).items() if v}}


def movers(prev, curr, limit=DEFAULT_MOVER_LIMIT):
    """Largest critical+high movers by ECR repo and by Inspector package.

    Packages are grouped by the action that fixes them (GROUPS), using the
    package-manager maps of both snapshots (the current one wins).
    `github` tags a package Dependabot also flags, which means a dependency PR
    path already exists. A movement that looks estate-wide is routinely one
    repo or one package.
    """
    out = {"repos": None, "packages": None, "package_groups": None}
    rp, rc = _repos(prev), _repos(curr)
    if rp is not None and rc is not None:
        rows = []
        for k in set(rp) | set(rc):
            a, b = rp.get(k), rc.get(k)
            rows.append({"repo": k, "prev_ch": a["ch"] if a else None, "curr_ch": b["ch"] if b else None,
                         "prev_images": a["images"] if a else None, "curr_images": b["images"] if b else None,
                         "delta": (b["ch"] if b else 0) - (a["ch"] if a else 0)})
        rows.sort(key=lambda r: (-abs(r["delta"]), r["repo"]))
        out["repos"] = rows[:limit]
    pp, pc = _packages(prev), _packages(curr)
    if pp is not None and pc is not None:
        zone_a = _zone_a_packages(curr) or set()
        managers = _merged_managers(prev, curr)
        rows, groups = [], {}
        for k in set(pp) | set(pc):
            d = pc.get(k, 0) - pp.get(k, 0)
            g = package_group(k, managers)
            groups[g] = groups.get(g, 0) + d
            rows.append({"package": k, "prev_ch": pp.get(k), "curr_ch": pc.get(k), "delta": d, "group": g,
                         "github": k in zone_a})
        rows.sort(key=lambda r: (-abs(r["delta"]), r["package"]))
        out["packages"] = rows[:limit]
        # Share of all movement, rises and falls together: against the net
        # total, groups moving in opposite directions give shares past 100%.
        gross = sum(abs(v) for v in groups.values())
        out["package_groups"] = [{"group": g, "delta": groups[g], "fix": GROUPS[g],
                                  "share_pct": round(100 * abs(groups[g]) / gross, 1) if gross else None}
                                 for g in GROUPS if g in groups]
        out["managers_captured"] = managers is not None
        # The groups' own scale: Inspector counts a finding once per package it names,
        # across every resource type, so these run above the ECR finding count.
        out["package_totals"] = {"prev": sum(pp.values()), "curr": sum(pc.values())}
    return out


def capture_blocks(curr):
    """The current snapshot's first-seen and rebuild-comparison blocks, or None when absent."""
    fs = _get(curr, ("raw", "first_seen"))
    rb = _get(curr, ("raw", "rebuild_comparison"))
    return {"first_seen": fs if isinstance(fs, dict) else None,
            "rebuild": rb if isinstance(rb, dict) else None}


# ── GitHub and correlation ───────────────────────────────────────────────────

def _advisories(snap):
    rows = _get(snap, ("github", "vuln_alerts_detail"))
    if not isinstance(rows, list):
        return None
    out = {}
    for r in rows:
        if (r.get("state") or "OPEN").upper() != "OPEN":
            continue
        key = (r.get("package"), r.get("cve") or r.get("summary"))
        out[key] = out.get(key, 0) + 1
    return out


def instances_vs_distinct(prev, curr, limit=DEFAULT_MOVER_LIMIT):
    """Dependabot alert instances against distinct advisories (package + CVE).

    Instances up with distinct flat is fan-out: known advisories reaching more
    repos. Distinct up is new advisories. They call for different responses.
    """
    ap, ac = _advisories(prev), _advisories(curr)
    if ap is None or ac is None:
        return None
    new = sorted(((k, v) for k, v in ac.items() if k not in ap), key=lambda kv: (-kv[1], str(kv[0])))
    gone = [k for k in ap if k not in ac]
    return {"prev_instances": sum(ap.values()), "curr_instances": sum(ac.values()),
            "prev_distinct": len(ap), "curr_distinct": len(ac),
            "new_distinct": len(new), "gone_distinct": len(gone),
            "new_instances": sum(v for _, v in new),
            "top_new": [{"package": k[0], "advisory": k[1], "instances": v} for k, v in new[:limit]]}


def correlation_movement(prev, curr):
    zp, zc = _zone_a_packages(prev), _zone_a_packages(curr)
    if zp is None or zc is None:
        return None
    return {"entered": sorted(zc - zp), "left": sorted(zp - zc), "prev": len(zp), "curr": len(zc)}


# ── data quality ─────────────────────────────────────────────────────────────

def data_quality(prev, curr, counts):
    """Flags that mean "check the capture before explaining it". A flag is not a driver."""
    flags = []
    for m in counts:
        if not m["comparable"]:
            if m["prev"] is not None or m["curr"] is not None:
                flags.append({"kind": "not_comparable", "key": m["key"],
                              "note": f"{m['label']} is missing from one snapshot; no delta computed."})
        elif (m["headline"] and m["pct"] is not None and m["pct"] >= OUTLIER_PCT
              and abs(m["delta"]) >= _METRIC[m["key"]].get("outlier_min_delta", 0)):
            flags.append({"kind": "outlier", "key": m["key"],
                          "note": f"{m['label']} rose {m['pct']}%. Verify the capture before explaining it."})
        elif (m["headline"] and m["prev"] == 0 and m["curr"] > 0
              and m["curr"] >= _METRIC[m["key"]].get("outlier_min_delta", 0)):
            # No percentage from a zero baseline, and an empty previous capture
            # is exactly what a rise from zero can mean.
            flags.append({"kind": "outlier", "key": m["key"],
                          "note": f"{m['label']} rose from 0 to {m['curr']}. Verify the previous capture before explaining it."})
    for name in ("first_seen", "rebuild_comparison", "package_breakdown", "node_scan", "node_os", "scan_coverage"):
        b = _get(curr, ("raw", name))
        # no_previous_snapshot is the first run, not a capture problem.
        if isinstance(b, dict) and b.get("status") not in ("ok", None, "no_previous_snapshot"):
            flags.append({"kind": "capture_status", "key": name, "note": f"{name}: {b['status']}."})
    st = _get(curr, ("raw", "package_managers_stats"))
    if isinstance(st, dict) and st.get("failed"):
        flags.append({"kind": "capture_status", "key": "package_managers",
                      "note": f"package_managers: {st['failed']} lookup(s) failed; those packages show as unknown."})
    cov = next((m for m in counts if m["key"] == "ecr_covered"), None)
    if cov and cov["comparable"] and cov["pct"] is not None and abs(cov["pct"]) >= 20:
        flags.append({"kind": "inventory", "key": "ecr_covered",
                      "note": f"ECR images covered moved {cov['pct']:+}%. Inventory change: read the decomposition before the totals."})
    return flags


# ── running but not scanned ──────────────────────────────────────────────────

# A running image whose rescanning lapses within this many days of the capture
# is listed before it lapses, so a rebuild can land first.
LAPSE_SOON_DAYS = 14


def _capture_time(snap):
    """The snapshot's own capture time ('2026-11-06 15:05 UTC'). The panel is
    measured from it, never from the clock, so a snapshot reads the same later."""
    try:
        return datetime.strptime(_get(snap, ("raw", "generated_at")) or "", "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# Kernel spelling (node_os) → image platform spelling.
NODE_ARCH = {"x86_64": "amd64", "aarch64": "arm64", "i386": "386"}


def _node_archs(snap):
    """Architectures every running instance uses, or None when any is unknown: node_os
    failed, a non-Bottlerocket host has no recorded architecture (older snapshots
    record only a count), or EC2 gave none. None means every platform of a running
    image index is checked. Fargate pods run on no instance and are not seen here."""
    n = _get(snap, ("raw", "node_os"))
    if not isinstance(n, dict) or n.get("status") != "ok" or not isinstance(n.get("nodes"), list):
        return None
    others = n.get("other_archs")
    if n.get("other_instances") and (not isinstance(others, list) or not others or None in others):
        return None
    archs = {NODE_ARCH.get(a, a) for a in [x.get("arch") for x in n["nodes"]] + (others or [])}
    return None if None in archs or not archs else archs


def scan_gaps(curr):
    """Workloads running now on an image Inspector no longer rescans, and those whose
    rescanning lapses within LAPSE_SOON_DAYS. Running means a container Lambda's
    current image, or an image Inspector saw in use on the cluster.

    None when the snapshot has no usable scan_coverage block (older snapshots,
    or the image read failed): absent, never an empty all-clear.
    """
    sc, at = _get(curr, ("raw", "scan_coverage")), _capture_time(curr)
    if not isinstance(sc, dict) or not isinstance(sc.get("images"), list) or at is None:
        return None
    soon = at + timedelta(days=LAPSE_SOON_DAYS)
    running = [{"kind": "lambda", "name": f["function"], "repo": f.get("repo"), "digest": f.get("digest"),
                "status": f.get("status"), "reason": f.get("reason"), "lapse_at": f.get("lapse_at")}
               for f in sc.get("functions") or []]
    by_digest = {(i["repo"], i["digest"]): i for i in sc["images"]}
    archs = _node_archs(curr)
    for i in sc["images"]:
        if not (i.get("in_use_count") or 0) > 0:
            continue
        if not i.get("index"):
            running.append({"kind": "cluster", "name": i["repo"], "repo": i["repo"], "digest": i["digest"],
                            "status": i.get("status"), "reason": i.get("reason"), "lapse_at": i.get("lapse_at")})
        elif i.get("platforms") is None:
            # A running index whose platform images could not be read: unknown, so listed.
            running.append({"kind": "cluster", "name": i["repo"], "repo": i["repo"], "digest": i["digest"],
                            "status": "PLATFORMS_UNKNOWN", "reason": None, "lapse_at": None})
        else:
            # Pods name the index; Inspector scans the platform images under it and
            # never sees them run, so each is judged on its own scan status.
            for pl in i["platforms"]:
                arch = ((pl.get("platform") or "").split("/") + [None, None])[1]
                if archs is not None and arch not in archs:
                    continue  # no node can run this platform
                c = by_digest.get((i["repo"], pl.get("digest"))) or {}
                running.append({"kind": "cluster", "name": f"{i['repo']} ({pl.get('platform') or 'unknown platform'})",
                                "repo": i["repo"], "digest": pl.get("digest"),
                                "status": c.get("status", "NOT_IN_COVERAGE"), "reason": c.get("reason"),
                                "lapse_at": c.get("lapse_at"), "index_platform": True})
    not_scanned, lapsing = [], []
    for r in running:
        if r["status"] != "ACTIVE":
            not_scanned.append(r)
        elif r["lapse_at"] and datetime.fromisoformat(r["lapse_at"]) <= soon:
            lapsing.append(r)
    lapsing.sort(key=lambda r: (r["lapse_at"], r["name"]))
    not_scanned.sort(key=lambda r: (r["kind"], r["name"]))
    return {"as_of": at.isoformat(), "soon_days": LAPSE_SOON_DAYS, "windows": sc.get("windows"),
            "running": len(running), "functions_measured": isinstance(sc.get("functions"), list),
            "not_scanned": not_scanned, "lapsing": lapsing}


# ── composed entry point ─────────────────────────────────────────────────────

def security_movement(prev, curr, prev_date=None, curr_date=None, limit=DEFAULT_MOVER_LIMIT):
    counts = count_movements(prev, curr)
    return {
        "prev_date": prev_date, "curr_date": curr_date,
        "counts": counts,
        "inspector": inspector_decomposition(prev, curr),
        "held_layers": held_layers(prev, curr),
        "repo_image_stability": repo_image_stability(prev, curr),
        "movers": movers(prev, curr, limit),
        "captures": capture_blocks(curr),
        "github": instances_vs_distinct(prev, curr, limit),
        "correlation": correlation_movement(prev, curr),
        "data_quality": data_quality(prev, curr, counts),
        "levers": remediation_levers(curr, _merged_managers(prev, curr), KERNEL_PACKAGES, APPLICATION_MANAGERS),
        "scan_gaps": scan_gaps(curr),
    }
