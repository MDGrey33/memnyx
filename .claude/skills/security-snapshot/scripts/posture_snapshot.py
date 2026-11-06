#!/usr/bin/env python3
"""
posture_snapshot.py — Inspector V2 full posture + fan-out analysis

Usage:
    python3 posture_snapshot.py             # print to stdout
    python3 posture_snapshot.py --save      # also write posture-YYYYMMDD.md here
    python3 posture_snapshot.py --raw       # also write raw-YYYYMMDD.json here
    python3 posture_snapshot.py --save --raw

AWS profile and region come from config.json (aws_profile / aws_region).
The account ID is derived at runtime via STS — never hardcoded.

Sections produced:
  1. Coverage (ECR images / EC2 / Lambda)
  2. Total findings (C / H / M)
  3. Fan-out summary (unique CVEs, average fan-out)
  4. Top CVEs by C+H (TITLE aggregation)
  5. Top packages by finding count
  6. Repositories ranked by C+H
  7. Dominant base layers (IMAGE_LAYER aggregation, deduplicated)
  8. EC2 AMI summary
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from config_util import (
    load_config as _load_config,
    require as _require,
    resolve_reports_dir as _resolve_reports_dir,
)
from movement import KERNEL_PACKAGES

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    sys.exit("boto3 not installed: pip install boto3")

# The optional captures degrade to "status failed" on any AWS error: an API
# refusal (ClientError) or a transport failure such as a timeout or a dropped
# connection (BotoCoreError). Either must cost the block, never the snapshot.
AWS_ERRORS = (ClientError, BotoCoreError)


def _code(e):
    return e.response.get("Error", {}).get("Code", "ClientError") if isinstance(e, ClientError) else type(e).__name__


_CFG    = _load_config()
PROFILE = _require(_CFG, "aws_profile")
REGION  = _require(_CFG, "aws_region")



# ── AWS client ────────────────────────────────────────────────────────────────

def inspector_client():
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    # Adaptive retries absorb transient Inspector throttling so it rarely
    # surfaces as a ClientError at all (see paginate_aggregations for what
    # happens when one does).
    return session.client("inspector2", config=Config(retries={"mode": "adaptive", "max_attempts": 8}))


def ecr_client():
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    return session.client("ecr", config=Config(retries={"mode": "adaptive", "max_attempts": 8}))


# ── Aggregation helpers ───────────────────────────────────────────────────────

def paginate_aggregations(c, agg_type, agg_request, max_results=100, required=True):
    """
    Page through list_finding_aggregations, returning all responses.

    `required` sections fail the run on any AWS error rather than continuing
    with partial pages: these aggregations feed the account-wide headline
    numbers and the immutable snapshot history, and a mid-pagination failure
    yields a count that looks complete while silently under-reporting.
    Optional sections warn and return an empty list instead, never a partial one.
    """
    results = []
    kwargs = {
        "aggregationType": agg_type,
        "aggregationRequest": agg_request,
        "maxResults": max_results,
    }
    while True:
        try:
            resp = c.list_finding_aggregations(**kwargs)
        except AWS_ERRORS as e:
            if required:
                sys.exit(f"error: {agg_type} aggregation failed after {len(results)} pages — "
                         f"refusing to report partial account-wide numbers; rerun the snapshot: {e}")
            print(f"  WARN: {agg_type} aggregation failed — section left empty: {e}", file=sys.stderr)
            return []  # never the pages gathered so far: a truncated list reads as complete
        results.extend(resp.get("responses", []))
        token = resp.get("nextToken")
        if not token:
            break
        kwargs["nextToken"] = token
    return results


def get_coverage_counts(c):
    """Return {resource_type: count} for EC2, ECR, Lambda."""
    resource_types = [
        "AWS_EC2_INSTANCE",
        "AWS_ECR_CONTAINER_IMAGE",
        "AWS_LAMBDA_FUNCTION",
    ]
    counts = {}
    for rt in resource_types:
        total = 0
        kwargs = {
            "filterCriteria": {"resourceType": [{"comparison": "EQUALS", "value": rt}]},
            "maxResults": 200,
        }
        while True:
            resp = c.list_coverage(**kwargs)
            total += len(resp.get("coveredResources", []))
            token = resp.get("nextToken")
            if not token:
                break
            kwargs["nextToken"] = token
        counts[rt] = total
    return counts


def _parse_generated_at(s):
    """'2026-10-07 15:05 UTC' → aware datetime, or None."""
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def previous_capture(reports_dir, date_slug):
    """(folder, capture time) of the newest raw.json in a folder dated before date_slug.

    Strictly before: a same-day rerun overwrites today's folder, so today's own
    raw.json is never the basis. Returns (None, None) when there is none.
    """
    if reports_dir is None or not Path(reports_dir).is_dir():
        return None, None
    for folder in sorted(Path(reports_dir).iterdir(), reverse=True):
        if not (folder.is_dir() and folder.name.isdigit() and len(folder.name) == 8 and folder.name < date_slug):
            continue
        raw = folder / "raw.json"
        if not raw.exists():
            continue
        try:
            ts = _parse_generated_at(json.loads(raw.read_text()).get("generated_at"))
        except (OSError, ValueError):
            ts = None
        if ts:
            return folder.name, ts
    return None, None


def _as_dt(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


FIRST_SEEN_TOP_PACKAGES = 50


def first_seen_since(c, since, until, basis=None):
    """Critical+high findings first observed in (since, until], still active now.

    Answers "did the scanner catch up, or did new exposure appear?". For ECR,
    each finding is split by whether its image was pushed before `since`
    (existing image, so the finding is new detection on unchanged code) or
    after (a rebuild, whose findings are all new by construction). Advisory
    publication date is split the same way where the vendor supplies one.

    Never returns partial counts: a failure mid-pagination returns a status
    block with counts set to None, because a partial count reads as complete.
    """
    out = {"status": "ok", "basis_snapshot": basis,
           "since": since.isoformat(), "until": until.isoformat()}
    kwargs = {
        "filterCriteria": {
            "severity": [{"comparison": "EQUALS", "value": "CRITICAL"},
                         {"comparison": "EQUALS", "value": "HIGH"}],
            "findingStatus": [{"comparison": "EQUALS", "value": "ACTIVE"}],
            "firstObservedAt": [{"startInclusive": since, "endInclusive": until}],
        },
        "maxResults": 100,
    }
    total = 0
    by_resource = defaultdict(int)
    ecr = {"existing_images": 0, "pushed_since": 0, "push_time_unknown": 0}
    ecr_images = {"existing_images": set(), "pushed_since": set()}
    pkg = defaultdict(lambda: {"existing_images": 0, "pushed_since": 0, "other": 0})
    advisory = {"published_before_window": 0, "published_in_window": 0, "date_unknown": 0}
    pages = 0
    while True:
        try:
            resp = c.list_findings(**kwargs)
        except AWS_ERRORS as e:
            print(f"  WARN: first-seen query failed after {pages} pages — field left empty: {e}", file=sys.stderr)
            return {**out, "status": f"failed: {_code(e)}",
                    "total": None, "by_resource_type": None, "ecr": None, "by_package": None, "advisory": None}
        pages += 1
        for f in resp.get("findings", []):
            total += 1
            res = (f.get("resources") or [{}])[0]
            by_resource[res.get("type") or "UNKNOWN"] += 1
            vuln = f.get("packageVulnerabilityDetails") or {}
            pkgs = vuln.get("vulnerablePackages") or []
            name = pkgs[0].get("name") if pkgs else None
            bucket = "other"
            if res.get("type") == "AWS_ECR_CONTAINER_IMAGE":
                img = (res.get("details") or {}).get("awsEcrContainerImage") or {}
                pushed = _as_dt(img.get("pushedAt"))
                if pushed is None:
                    ecr["push_time_unknown"] += 1
                else:
                    bucket = "pushed_since" if pushed > since else "existing_images"
                    ecr[bucket] += 1
                    ecr_images[bucket].add(res.get("id") or img.get("imageHash"))
            if name:
                pkg[name][bucket] += 1
            published = _as_dt(vuln.get("vendorCreatedAt"))
            if published is None:
                advisory["date_unknown"] += 1
            elif published <= since:
                advisory["published_before_window"] += 1
            else:
                advisory["published_in_window"] += 1
        if pages % 20 == 0:
            print(f"   … {total:,d} findings over {pages} pages", file=sys.stderr, flush=True)
        token = resp.get("nextToken")
        if not token:
            break
        kwargs["nextToken"] = token
    ecr["images_existing"] = len(ecr_images["existing_images"])
    ecr["images_pushed_since"] = len(ecr_images["pushed_since"])
    ranked = sorted(pkg.items(), key=lambda kv: -sum(kv[1].values()))[:FIRST_SEEN_TOP_PACKAGES]
    return {**out, "total": total, "by_resource_type": dict(by_resource), "ecr": ecr,
            "by_package": [{"package": k, **v} for k, v in ranked], "advisory": advisory}


# A repo is flagged when images pushed in the window carry at least this many
# times the critical+high per image of its older live images, AND at least
# REBUILD_FLAG_MIN_GAP more per image — the ratio alone fires on tiny bases.
REBUILD_FLAG_RATIO = 1.5
REBUILD_FLAG_MIN_GAP = 50


def _failed(out, what, err):
    code = _code(err)
    print(f"  WARN: rebuild comparison — {what} failed, field left empty: {err}", file=sys.stderr)
    return {**out, "status": f"failed: {what}: {code}", "repos": None, "not_comparable": None, "totals": None}


def rebuild_comparison(c, ecr, since, basis=None):
    """Per ECR repo: critical+high per image, images pushed in the window vs older ones.

    Every image compared is actively scanned, so all of them are scored against
    the same vulnerability database on the same day: a gap between the two
    groups comes from what is in the images (base, system packages,
    dependencies), not from database timing. Images whose scan eligibility has
    expired are excluded — their counts are frozen against an older database.

    The groups are not the same code: older images are often other branches.
    A flag says "look here", not "this build regressed".
    """
    out = {"status": "ok", "basis_snapshot": basis, "since": since.isoformat(),
           "flag_rule": f">= {REBUILD_FLAG_RATIO}x and >= {REBUILD_FLAG_MIN_GAP} more C+H per image"}
    # 1. Actively scanned images — the population.
    active, inactive = {}, 0
    kwargs = {"filterCriteria": {"resourceType": [{"comparison": "EQUALS", "value": "AWS_ECR_CONTAINER_IMAGE"}]},
              "maxResults": 200}
    try:
        while True:
            resp = c.list_coverage(**kwargs)
            for r in resp.get("coveredResources", []):
                if (r.get("scanStatus") or {}).get("statusCode") != "ACTIVE":
                    inactive += 1
                    continue
                repo = (((r.get("resourceMetadata") or {}).get("ecrRepository")) or {}).get("name")
                digest = r.get("resourceId", "").rpartition("/")[2]
                if repo and digest.startswith("sha256:"):
                    active[r["resourceId"]] = (repo, digest)
            if not resp.get("nextToken"):
                break
            kwargs["nextToken"] = resp["nextToken"]
    except AWS_ERRORS as e:
        return _failed(out, "coverage", e)
    # 2. Critical+high per image. Images absent from the aggregation have none.
    ch = defaultdict(int)
    kwargs = {"aggregationType": "AWS_ECR_CONTAINER", "aggregationRequest": {"awsEcrContainerAggregation": {}},
              "maxResults": 100}
    try:
        while True:
            resp = c.list_finding_aggregations(**kwargs)
            for a in resp.get("responses", []):
                agg = a.get("awsEcrContainerAggregation") or {}
                sc = agg.get("severityCounts") or {}
                ch[agg.get("resourceId")] = sc.get("critical", 0) + sc.get("high", 0)
            if not resp.get("nextToken"):
                break
            kwargs["nextToken"] = resp["nextToken"]
    except AWS_ERRORS as e:
        return _failed(out, "findings per image", e)
    # 3. Push times from ECR, per repo.
    pushed = {}
    for repo in sorted({r for r, _ in active.values()}):
        try:
            kw = {"repositoryName": repo, "maxResults": 1000}
            while True:
                resp = ecr.describe_images(**kw)
                for d in resp.get("imageDetails", []):
                    pushed[(repo, d.get("imageDigest"))] = _as_dt(d.get("imagePushedAt"))
                if not resp.get("nextToken"):
                    break
                kw["nextToken"] = resp["nextToken"]
        except AWS_ERRORS as e:
            if _code(e) == "RepositoryNotFoundException":
                continue  # repo deleted since the scan; its images fall to "push time unknown"
            return _failed(out, f"push times ({repo})", e)
    # 4. Group and compare.
    groups = defaultdict(lambda: {"old": [], "new": []})
    unknown = 0
    for rid, (repo, digest) in active.items():
        t = pushed.get((repo, digest))
        if t is None:
            unknown += 1
            continue
        groups[repo]["new" if t > since else "old"].append(ch.get(rid, 0))
    repos, not_comparable = [], []
    tot = {"old_images": 0, "old_ch": 0, "new_images": 0, "new_ch": 0}
    for repo, g in sorted(groups.items()):
        tot["old_images"] += len(g["old"]); tot["old_ch"] += sum(g["old"])
        tot["new_images"] += len(g["new"]); tot["new_ch"] += sum(g["new"])
        if not g["old"] or not g["new"]:
            not_comparable.append({"repo": repo, "reason": "no older live images" if g["new"] else "no images pushed in window",
                                   "images": len(g["old"]) + len(g["new"])})
            continue
        old_pi = sum(g["old"]) / len(g["old"])
        new_pi = sum(g["new"]) / len(g["new"])
        repos.append({"repo": repo, "old_images": len(g["old"]), "old_ch_per_image": round(old_pi, 1),
                      "new_images": len(g["new"]), "new_ch_per_image": round(new_pi, 1),
                      "gap_per_image": round(new_pi - old_pi, 1),
                      "flagged": new_pi - old_pi >= REBUILD_FLAG_MIN_GAP and new_pi >= REBUILD_FLAG_RATIO * old_pi})
    repos.sort(key=lambda r: -r["gap_per_image"])
    tot.update({"inactive_images_excluded": inactive, "push_time_unknown": unknown})
    return {**out, "repos": repos, "not_comparable": not_comparable, "totals": tot}


def get_title_stats(responses):
    """
    Summarise TITLE aggregation responses.
    Returns a dict with unique_count, the number of packages named in titles
    and the top CVEs.
    """
    pkg_totals = defaultdict(lambda: {"c": 0, "h": 0, "m": 0, "titles": 0})
    all_titles = []

    for r in responses:
        t = r.get("titleAggregation", {})
        sc = t.get("severityCounts", {})
        c = sc.get("critical", 0)
        h = sc.get("high", 0)
        m = sc.get("medium", 0)
        title = t.get("title", "")

        # Extract package name from "CVE-XXXX - pkgname" pattern
        parts = title.split(" - ")
        pkg = parts[1].strip() if len(parts) > 1 else "unknown"

        pkg_totals[pkg]["c"] += c
        pkg_totals[pkg]["h"] += h
        pkg_totals[pkg]["m"] += m
        pkg_totals[pkg]["titles"] += 1
        all_titles.append({"title": title, "c": c, "h": h, "m": m})

    # Top 50 by CRITICAL+HIGH
    top = sorted(all_titles, key=lambda x: x["c"] + x["h"], reverse=True)[:50]

    return {
        "unique_count": len(responses),
        "pkg_count": len(pkg_totals),
        "top_by_ch": top,
    }


def get_layer_stats(responses):
    """
    Deduplicate IMAGE_LAYER aggregation by hash.
    Returns top layers sorted by CRITICAL+HIGH, each with affected repo/image counts.
    """
    by_hash = defaultdict(lambda: {"c": 0, "h": 0, "m": 0, "repos": set(), "images": set()})

    for r in responses:
        l = r.get("imageLayerAggregation", {})
        sc = l.get("severityCounts", {})
        h = l.get("layerHash", "")
        if not h:
            continue
        by_hash[h]["c"] += sc.get("critical", 0)
        by_hash[h]["h"] += sc.get("high", 0)
        by_hash[h]["m"] += sc.get("medium", 0)
        if l.get("repository"):
            by_hash[h]["repos"].add(l["repository"])
        if l.get("resourceId"):
            by_hash[h]["images"].add(l["resourceId"])

    result = [
        {
            "layer": k,
            "c": v["c"], "h": v["h"], "m": v["m"],
            "repos": len(v["repos"]),
            "repo_list": sorted(r for r in v["repos"] if r),
            "images": len(v["images"]),
        }
        for k, v in by_hash.items()
    ]
    return sorted(result, key=lambda x: x["c"] + x["h"], reverse=True)


BASE_LAYERS_SHOWN = 20


def all_layers_compact(layers):
    """Every layer with any critical+high finding, for the held-layer control.

    The dashboard keeps showing the top BASE_LAYERS_SHOWN. The movement report
    needs the rest: a layer that drops out of a top-N list looks like it
    disappeared when it only got overtaken.
    """
    return [{"layer": x["layer"], "c": x["c"], "h": x["h"], "images": x["images"], "repo_list": x["repo_list"]}
            for x in layers if x["c"] + x["h"] > 0]


def previous_package_managers(reports_dir, basis):
    """{package: manager} from the basis snapshot's raw.json, or {}."""
    if not (reports_dir and basis):
        return {}
    try:
        rows = json.loads((Path(reports_dir) / basis / "raw.json").read_text()).get("package_managers") or []
    except (OSError, ValueError):
        return {}
    return {r["package"]: r["manager"] for r in rows if isinstance(r, dict) and r.get("package") and r.get("manager")}


def package_managers(c, names, known):
    """Package manager (OS, NODE, PYTHON, GENERIC, ...) for each package name.

    The per-package aggregation does not carry it and Inspector cannot filter
    on it, so it is read off one finding per package. A package's manager does
    not change, so names already in `known` are not queried again. A name
    whose lookup fails or finds nothing gets None — shown as unknown, never
    guessed.
    """
    out, queried, failed = {}, 0, 0
    for name in sorted(names):
        if known.get(name):
            out[name] = known[name]
            continue
        queried += 1
        try:
            resp = c.list_findings(maxResults=1, filterCriteria={
                "vulnerablePackages": [{"name": {"comparison": "EQUALS", "value": name}}]})
        except AWS_ERRORS:
            failed += 1
            out[name] = None
            continue
        manager = None
        for f in resp.get("findings", []):
            for vp in (f.get("packageVulnerabilityDetails") or {}).get("vulnerablePackages") or []:
                if vp.get("name") == name and vp.get("packageManager"):
                    manager = vp["packageManager"]
                    break
        out[name] = manager
    # Keep packages seen before but absent now: the movement report needs the
    # manager of a package that left between two snapshots. The map only grows.
    merged = {**{k: v for k, v in known.items() if v}, **out}
    rows = [{"package": k, "manager": v} for k, v in sorted(merged.items())]
    return rows, {"queried": queried, "reused": len(names) - queried, "failed": failed,
                  "unknown": sum(1 for v in out.values() if v is None)}


def _ch_filter(extra):
    severity = [{"comparison": "EQUALS", "value": v} for v in ("CRITICAL", "HIGH")]
    return {"severity": severity, "findingStatus": [{"comparison": "EQUALS", "value": "ACTIVE"}], **extra}


BREAKDOWN_WORKERS = 8


def package_breakdown(c, names, repos=None, workers=BREAKDOWN_WORKERS, kernel_names=None):
    """Critical+high per (package, ECR repo) for the packages one image change removes.

    Each row holds every finding that names its package, as the Inspector
    console counts it, so a finding naming two packages appears in both rows.
    Inspector reports each kernel advisory against both `linux` and
    `linux-libc-dev`, so summing kernel rows counts most findings twice.
    `kernel_repos` counts them once: one record per repo, built from every
    finding that names any of `kernel_names`. Without `kernel_names` there is
    no record (None), never an empty one: an empty one reads as no kernel
    findings at all.

    A row's `layers` is the base-layer netting basis, so each finding sits in
    the layers of one row only: a finding that also names a kernel package is
    netted through the kernel record, and one that names two other packages is
    netted under the first row that holds it. Inspector leaves the in-use fields off an image it has never seen
    running, so a missing count reads as not running. When no finding in the
    capture carries one, in-use tracking is not reporting, and every
    `running_ch` is None rather than a zero nobody measured.

    Kernel headers and bundled runtimes are fixed per Dockerfile, so the
    remediation question is "which repos", which the per-package aggregation
    cannot answer. Each row carries what the fix needs: distinct images, how
    many findings already have a fixed version, the image OS, the installed
    package versions, and the layers its findings sit in, for the base-layer
    lever to net off (see below for which findings each row carries there).

    One query per (package, repo) when `repos` is given, run in parallel: a
    single kernel package can carry tens of thousands of findings, and one
    paginated stream of them takes minutes.

    Never partial: any failure returns status failed and rows None.
    """
    out = {"status": "ok", "packages": sorted(names)}
    units = [(n, r) for n in sorted(names) for r in (sorted(repos) if repos else [None])]

    def fetch(unit):
        name, repo = unit
        crit = {"resourceType": [{"comparison": "EQUALS", "value": "AWS_ECR_CONTAINER_IMAGE"}],
                "vulnerablePackages": [{"name": {"comparison": "EQUALS", "value": name}}]}
        if repo:
            crit["ecrImageRepositoryName"] = [{"comparison": "EQUALS", "value": repo}]
        kwargs = {"filterCriteria": _ch_filter(crit), "maxResults": 100}
        found = []
        while True:
            resp = c.list_findings(**kwargs)
            found += [(name, f) for f in resp.get("findings", [])]
            token = resp.get("nextToken")
            if not token:
                return found
            kwargs["nextToken"] = token

    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            results = list(pool.map(fetch, units))
    except AWS_ERRORS as e:
        print(f"  WARN: package breakdown failed — field left empty: {e}", file=sys.stderr)
        return {**out, "status": f"failed: {_code(e)}", "rows": None, "kernel_repos": None}
    acc, kernel, tracked, netted = {}, {}, False, set()
    for found in results:
        for name, f in found:
                vp = next((v for v in (f.get("packageVulnerabilityDetails") or {}).get("vulnerablePackages") or []
                           if v.get("name") == name), None)
                if vp is None:
                    continue
                res = (f.get("resources") or [{}])[0]
                img = (res.get("details") or {}).get("awsEcrContainerImage") or {}
                repo = img.get("repositoryName") or "unknown"
                r = acc.setdefault((name, repo), {"ch": 0, "fix_available": 0, "images": set(), "platforms": set(),
                                                  "versions": set(), "layers": defaultdict(int),
                                                  "running_ch": 0, "running_images": set()})
                r["ch"] += 1
                running = _running(img)
                tracked |= running is not None
                if running:
                    r["running_ch"] += 1
                    r["running_images"].add(res.get("id"))
                r["fix_available"] += f.get("fixAvailable") == "YES"
                r["images"].add(res.get("id"))
                if img.get("platform"):
                    r["platforms"].add(img["platform"])
                if vp.get("version"):
                    r["versions"].add(vp["version"])
                netted_as_kernel = kernel_names is not None and name not in kernel_names and any(
                    v.get("name") in kernel_names
                    for v in (f.get("packageVulnerabilityDetails") or {}).get("vulnerablePackages") or [])
                # Only an ARN proves two rows hold the same finding; without one, count it.
                arn = f.get("findingArn")
                if vp.get("sourceLayerHash") and not netted_as_kernel and not (arn and arn in netted):
                    if arn:
                        netted.add(arn)
                    r["layers"][vp["sourceLayerHash"]] += 1
                if kernel_names is not None and name in kernel_names:
                    _kernel_finding(kernel, repo, f, res, img, kernel_names)
    rows = [{"package": k[0], "repo": k[1], "ch": v["ch"], "fix_available": v["fix_available"],
             "images": len(v["images"]), "platforms": sorted(v["platforms"]), "versions": sorted(v["versions"]),
             "layers": [{"layer": h, "ch": n} for h, n in sorted(v["layers"].items(), key=lambda kv: -kv[1])],
             "running_ch": v["running_ch"] if tracked else None,
             "running_images": len(v["running_images"]) if tracked else None}
            for k, v in acc.items()]
    rows.sort(key=lambda r: (-r["ch"], r["package"], r["repo"]))
    return {**out, "rows": rows, "kernel_repos": None if kernel_names is None else _kernel_repos(kernel, tracked)}


def _running(img):
    """Whether Inspector saw the image in use (running in a cluster) when it last
    checked. An image no longer in use keeps its findings until it ages out of the
    rescan window, so counts that ignore this overstate what is exposed now.
    None when the image carries no in-use count, which Inspector does for an
    image it has never seen running; the caller decides what that means."""
    if img.get("inUseCount") is None:
        return None
    return img["inUseCount"] > 0


def _finding_key(f, res):
    """A finding's identity. The ARN when present; otherwise the image and the
    advisory, which together name one finding."""
    return f.get("findingArn") or (res.get("id"), (f.get("packageVulnerabilityDetails") or {}).get("vulnerabilityId"),
                                   f.get("title"), f.get("firstObservedAt"))


def _kernel_finding(kernel, repo, f, res, img, kernel_names):
    """Fold one kernel finding into its repo's record, once per finding: every
    kernel package's query returns the same finding, so the first sighting
    records it and later ones are skipped. Versions and layers come from all of
    the finding's kernel entries, not only the queried package's."""
    k = kernel.setdefault(repo, {"findings": set(), "fix_available": 0, "images": set(), "platforms": set(),
                                 "versions": set(), "layers": defaultdict(int),
                                 "running": set(), "running_images": set()})
    key = _finding_key(f, res)
    if key in k["findings"]:
        return
    k["findings"].add(key)
    if _running(img):
        k["running"].add(key)
        k["running_images"].add(res.get("id"))
    k["fix_available"] += f.get("fixAvailable") == "YES"
    k["images"].add(res.get("id"))
    if img.get("platform"):
        k["platforms"].add(img["platform"])
    entries = [v for v in (f.get("packageVulnerabilityDetails") or {}).get("vulnerablePackages") or []
               if v.get("name") in kernel_names]
    k["versions"].update(v["version"] for v in entries if v.get("version"))
    for layer in {v["sourceLayerHash"] for v in entries if v.get("sourceLayerHash")}:
        k["layers"][layer] += 1


def _kernel_repos(kernel, tracked=True):
    out = [{"repo": repo, "ch": len(k["findings"]), "fix_available": k["fix_available"], "images": len(k["images"]),
            "platforms": sorted(k["platforms"]), "versions": sorted(k["versions"]),
            "layers": [{"layer": h, "ch": n} for h, n in sorted(k["layers"].items(), key=lambda kv: -kv[1])],
            "running_ch": len(k["running"]) if tracked else None,
            "running_images": len(k["running_images"]) if tracked else None}
           for repo, k in kernel.items()]
    return sorted(out, key=lambda x: (-x["ch"], x["repo"]))


def node_scan(c):
    """What Inspector can say about the EC2 hosts the containers run on.

    Containers share the host's kernel, so kernel exposure is measured on the
    host. Some host OSes are covered by Inspector yet return no package
    findings at all; package_findings separates "scanned and clean" from
    "not measured", which a zero alone cannot.
    """
    out = {"status": "ok"}
    scanned, platforms = 0, defaultdict(int)
    kwargs = {"filterCriteria": {"resourceType": [{"comparison": "EQUALS", "value": "AWS_EC2_INSTANCE"}]},
              "maxResults": 200}
    try:
        while True:
            resp = c.list_coverage(**kwargs)
            for r in resp.get("coveredResources", []):
                if (r.get("scanStatus") or {}).get("statusCode") == "ACTIVE":
                    scanned += 1
            if not resp.get("nextToken"):
                break
            kwargs["nextToken"] = resp["nextToken"]
        by_type, kernel_ch = defaultdict(int), 0
        kwargs = {"filterCriteria": {"resourceType": [{"comparison": "EQUALS", "value": "AWS_EC2_INSTANCE"}],
                                     "findingStatus": [{"comparison": "EQUALS", "value": "ACTIVE"}]},
                  "maxResults": 100}
        while True:
            resp = c.list_findings(**kwargs)
            for f in resp.get("findings", []):
                by_type[f.get("type") or "UNKNOWN"] += 1
                d = ((f.get("resources") or [{}])[0].get("details") or {}).get("awsEc2Instance") or {}
                if d.get("platform"):
                    platforms[d["platform"]] += 1
                names = [v.get("name") or "" for v in (f.get("packageVulnerabilityDetails") or {}).get("vulnerablePackages") or []]
                if f.get("severity") in ("CRITICAL", "HIGH") and any(n.startswith(("kernel", "linux")) for n in names):
                    kernel_ch += 1
            if not resp.get("nextToken"):
                break
            kwargs["nextToken"] = resp["nextToken"]
    except AWS_ERRORS as e:
        print(f"  WARN: node scan failed — field left empty: {e}", file=sys.stderr)
        return {"status": f"failed: {_code(e)}",
                "instances_scanned": None, "package_findings": None, "kernel_ch": None, "platforms": None}
    pkg = by_type.get("PACKAGE_VULNERABILITY", 0)
    return {**out, "instances_scanned": scanned, "package_findings": pkg,
            "kernel_ch": kernel_ch if pkg else None,
            "platforms": [{"platform": k, "findings": v} for k, v in sorted(platforms.items())]}


BOTTLEROCKET_NAME = re.compile(r"bottlerocket-aws-k8s-(?P<k8s>[\d.]+)-(?P<arch>[a-z0-9_]+)-v(?P<version>[\d.]+)")


# Image names spell the architecture as the kernel does; the public SSM
# parameters use the package-manager spelling.
SSM_ARCH = {"aarch64": "arm64"}


def node_os(ec2, ssm):
    """Bottlerocket release on the running hosts against the latest published release.

    Bottlerocket ships the kernel inside each OS release and is updated by
    moving to a new release, not by patching packages, and Inspector returns
    no package findings for it. So host kernel exposure is read as "how far
    behind the latest release", which this records. Hosts on any other image
    are counted, not read. Never partial: a failure returns status failed.
    """
    try:
        by_image = defaultdict(int)
        for page in ec2.get_paginator("describe_instances").paginate(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]):
            for r in page.get("Reservations", []):
                for i in r.get("Instances", []):
                    by_image[i["ImageId"]] += 1
        images = ec2.describe_images(ImageIds=sorted(by_image))["Images"] if by_image else []
        groups, other = defaultdict(lambda: {"instances": 0, "image_created": None}), sum(by_image.values())
        for im in images:
            m = BOTTLEROCKET_NAME.search(im.get("Name") or "")
            if not m:
                continue
            g = groups[(m["k8s"], m["arch"], m["version"])]
            g["instances"] += by_image[im["ImageId"]]
            other -= by_image[im["ImageId"]]
            created = (im.get("CreationDate") or "")[:10] or None
            g["image_created"] = min(filter(None, [g["image_created"], created]), default=None)
    except AWS_ERRORS as e:
        print(f"  WARN: node OS capture failed — field left empty: {e}", file=sys.stderr)
        return {"status": f"failed: {_code(e)}", "nodes": None, "other_instances": None}
    # Looked up per group: a Kubernetes version or architecture with no
    # published parameter costs that group its comparison, not the others.
    latest = {}
    for k8s, arch in sorted({(k, a) for k, a, _ in groups}):
        name = f"/aws/service/bottlerocket/aws-k8s-{k8s}/{SSM_ARCH.get(arch, arch)}/latest/image_version"
        try:
            prm = ssm.get_parameter(Name=name)["Parameter"]
            latest[(k8s, arch)] = {"version": prm["Value"].split("-")[0], "published": _as_dt(prm.get("LastModifiedDate"))}
        except AWS_ERRORS as e:
            print(f"  WARN: no latest release for {name}: {_code(e)}", file=sys.stderr)
    nodes = []
    for (k8s, arch, version), g in sorted(groups.items()):
        lt = latest.get((k8s, arch))
        nodes.append({"os": "BOTTLEROCKET", "k8s": k8s, "arch": arch, "version": version, "instances": g["instances"],
                      "image_created": g["image_created"], "latest": lt["version"] if lt else None,
                      "latest_published": lt["published"].date().isoformat() if lt and lt["published"] else None,
                      "on_latest": _on_latest(version, lt["version"] if lt else None)})
    return {"status": "ok", "nodes": nodes, "other_instances": other}


def _on_latest(running, latest):
    a, b = _version(running), _version(latest)
    if a is None or b is None:
        return None
    n = max(len(a), len(b))  # 1.51 and 1.51.0 are the same release
    return a + (0,) * (n - len(a)) >= b + (0,) * (n - len(b))


def _version(v):
    """Numeric release tuple, or None when the value is not a dotted version (an
    optional leading "v" is allowed). Never a partial tuple: dropping a part that
    does not parse would compare a shorter version as older or newer at random."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (v or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


# ── Report builder ────────────────────────────────────────────────────────────

def severity_counts(d):
    sc = d.get("severityCounts", {})
    return sc.get("critical", 0), sc.get("high", 0), sc.get("medium", 0)


def md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(lines)


def build_report(raw):
    ts           = raw["generated_at"]
    totals       = raw["account_totals"]
    pkgs         = raw["packages"]
    repos        = raw["repositories"]
    amis         = raw["amis"]
    cov          = raw["coverage"]
    title_stats  = raw.get("title_stats", {})
    layer_stats  = raw.get("base_layers", [])

    c_total = totals.get("critical", 0)
    h_total = totals.get("high", 0)
    m_total = totals.get("medium", 0)
    raw_total = c_total + h_total + m_total

    unique_cves  = title_stats.get("unique_count", 0)
    fan_out      = round(raw_total / unique_cves, 1) if unique_cves else 0

    lines = [
        "# AWS Inspector V2 Posture Snapshot",
        "",
        f"**Generated**: {ts}  |  **Account**: {raw.get('account', '—')}  |  **Region**: {raw.get('region', REGION)}",
        "",
        "## Coverage",
        "",
        md_table(
            ["Resource type", "Count"],
            [(k, f"{v:,d}") for k, v in cov.items()]
            + [("**Total**", f"**{sum(cov.values()):,d}**")],
        ),
        "",
        "## Total Findings",
        "",
        md_table(
            ["Severity", "Count"],
            [
                ("CRITICAL", f"{c_total:,d}"),
                ("HIGH",     f"{h_total:,d}"),
                ("MEDIUM",   f"{m_total:,d}"),
                ("**Total**", f"**{raw_total:,d}**"),
            ],
        ),
        "",
        "## Fan-out Summary",
        "",
    ]

    if unique_cves:
        lines += [
            md_table(
                ["Metric", "Value"],
                [
                    ("Raw findings (C+H+M)",               f"{raw_total:,d}"),
                    ("Unique CVE titles",                   f"{unique_cves:,d}"),
                    ("Average fan-out",                     f"~{fan_out:,.0f}×"),
                ],
            ),
        ]
    else:
        lines.append("> Title aggregation not available in this run.")

    # Top CVEs
    if title_stats.get("top_by_ch"):
        lines += ["", "## Top CVEs by CRITICAL+HIGH", ""]
        cve_rows = [
            [t["title"][:80], f"{t['c']:,d}", f"{t['h']:,d}", f"{t['m']:,d}"]
            for t in title_stats["top_by_ch"][:25]
        ]
        lines.append(md_table(["CVE / Title", "CRITICAL", "HIGH", "MEDIUM"], cve_rows))

    # Top packages
    lines += ["", "## Top Packages by Finding Count", ""]
    pkg_rows = []
    for r in pkgs[:50]:
        p = r.get("packageAggregation", {})
        c, h, m = severity_counts(p)
        pkg_rows.append([p.get("packageName", ""), f"{c:,d}", f"{h:,d}", f"{m:,d}", f"{c+h+m:,d}"])
    lines.append(md_table(["Package", "CRITICAL", "HIGH", "MEDIUM", "Total"], pkg_rows))
    lines.append(f"\n> {len(pkgs)} packages total.")

    # Repositories
    lines += ["", "## Repositories (sorted by CRITICAL+HIGH)", ""]
    sorted_repos = sorted(
        repos,
        key=lambda x: sum(severity_counts(x.get("repositoryAggregation", {}))[:2]),
        reverse=True,
    )
    repo_rows = []
    for r in sorted_repos:
        a = r.get("repositoryAggregation", {})
        c, h, m = severity_counts(a)
        repo_rows.append([
            a.get("repository", ""),
            f"{c:,d}", f"{h:,d}", f"{m:,d}",
            str(a.get("affectedImages", 0)),
        ])
    lines.append(md_table(["Repository", "CRITICAL", "HIGH", "MEDIUM", "Images"], repo_rows))

    # Base layers
    if layer_stats:
        shared = [l for l in layer_stats if l.get("repos", 0) >= 2]
        lines += ["", "## Shared Base Layers", ""]
        lines += [
            f"> Layers present in two or more repos ({len(shared)} of {len(layer_stats)} captured). What to fix",
            "> next on the dashboard ranks the shared-layer change against the other levers.",
            "",
        ]
        layer_rows = [
            [
                l["layer"][:20] + "…",
                f"{l['repos']:,d}",
                f"{l['images']:,d}",
                f"{l['c']:,d}",
                f"{l['h']:,d}",
                f"{l['m']:,d}",
                f"{l['c']+l['h']+l['m']:,d}",
            ]
            for l in shared[:15]
        ]
        lines.append(
            md_table(
                ["Layer (prefix)", "Repos", "Images", "CRITICAL", "HIGH", "MEDIUM", "Total"],
                layer_rows,
            )
        )

    # AMI summary
    lines += ["", "## EC2 AMI Summary", ""]
    ami_rows = []
    for r in amis:
        a = r.get("amiAggregation", {})
        c, h, m = severity_counts(a)
        instances = a.get("affectedInstances", 0)
        per = round((h + m) / instances, 1) if instances else 0
        ami_rows.append([
            a.get("ami", ""), str(instances),
            f"{c:,d}", f"{h:,d}", f"{m:,d}", str(per),
        ])
    lines.append(
        md_table(["AMI", "Instances", "CRITICAL", "HIGH", "MEDIUM", "H+M/instance"], ami_rows)
    )

    lines += ["", "## Critical+High First Seen Since Last Snapshot", ""]
    fs = raw.get("first_seen")
    if not fs or fs.get("total") is None:
        status = (fs or {}).get("status", "not captured")
        lines.append(f"Not available ({status}).")
    else:
        e, a = fs["ecr"], fs["advisory"]
        lines.append(f"Window: since snapshot `{fs['basis_snapshot']}` ({fs['since']}) → {fs['until']}. "
                     f"Active findings only.\n")
        lines.append(md_table(["Measure", "Findings"], [
            ["Total first seen", f"{fs['total']:,d}"],
            ["ECR — images that existed before the window", f"{e['existing_images']:,d} ({e['images_existing']} images)"],
            ["ECR — images pushed in the window", f"{e['pushed_since']:,d} ({e['images_pushed_since']} images)"],
            ["ECR — push time unknown", f"{e['push_time_unknown']:,d}"],
            ["Advisory published before the window", f"{a['published_before_window']:,d}"],
            ["Advisory published in the window", f"{a['published_in_window']:,d}"],
            ["Advisory date not supplied by vendor", f"{a['date_unknown']:,d}"],
        ]))
        lines.append("\n> Findings on images that existed before the window are new detections "
                     "against unchanged images. Findings on images pushed in the window are new "
                     "by construction, so a rebuild cannot be read as new exposure from this alone.\n")
        lines.append(md_table(["Package", "Existing images", "Pushed in window", "Other resources"],
                              [[p["package"], f"{p['existing_images']:,d}", f"{p['pushed_since']:,d}",
                                f"{p['other']:,d}"] for p in fs["by_package"][:15]]))

    lines += ["", "## Rebuilt vs Older Images, Same Repo", ""]
    rb = raw.get("rebuild_comparison")
    if not rb or rb.get("repos") is None:
        lines.append(f"Not available ({(rb or {}).get('status', 'not captured')}).")
    else:
        t = rb["totals"]
        def per(ch_, n): return f"{ch_ / n:,.1f}" if n else "–"
        lines.append(f"Images pushed since snapshot `{rb['basis_snapshot']}` ({rb['since']}) against older live "
                     f"images in the same repo. Actively scanned images only, so both groups are scored against "
                     f"the same database today. Flag rule: {rb['flag_rule']}.\n")
        lines.append(md_table(["Group", "Images", "C+H per image"], [
            ["Older images", str(t["old_images"]), per(t["old_ch"], t["old_images"])],
            ["Pushed in window", str(t["new_images"]), per(t["new_ch"], t["new_images"])],
        ]))
        lines.append(f"\n> Excluded: {t['inactive_images_excluded']} images no longer scanned (counts frozen), "
                     f"{t['push_time_unknown']} with no push time. {len(rb['not_comparable'])} repos hold only one "
                     f"group and cannot be compared. Older images are often other branches, so a flag means "
                     f"look here, not that a build regressed.\n")
        lines.append(md_table(["Repository", "Older (n)", "C+H/img", "New (n)", "C+H/img", "Gap", "Flag"],
                              [[r["repo"], str(r["old_images"]), f"{r['old_ch_per_image']:,.1f}",
                                str(r["new_images"]), f"{r['new_ch_per_image']:,.1f}",
                                f"{r['gap_per_image']:+,.1f}", "⚑" if r["flagged"] else ""]
                               for r in rb["repos"]]))

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Inspector V2 posture + fan-out snapshot")
    parser.add_argument("--save", action="store_true", help="Write .md report to reports_dir")
    parser.add_argument("--raw",  action="store_true", help="Write raw .json to reports_dir")
    parser.add_argument("--reports-dir", help="Directory for snapshot read/write (overrides $SECURITY_SNAPSHOT_REPORTS_DIR)")
    parser.add_argument("--first-seen-only", action="store_true",
                        help="Run only the first-seen query for --since/--until and print JSON; writes nothing")
    parser.add_argument("--rebuild-only", action="store_true",
                        help="Run only the rebuilt-vs-older image comparison for --since and print JSON; writes nothing")
    parser.add_argument("--since", help="With --first-seen-only / --rebuild-only: window start, ISO 8601 (e.g. 2026-09-23T08:32Z)")
    parser.add_argument("--until", help="With --first-seen-only: window end, ISO 8601 (default: now)")
    args = parser.parse_args()

    c = inspector_client()
    now       = datetime.now(timezone.utc)   # one clock read — ts and date_slug must agree across midnight
    ts        = now.strftime("%Y-%m-%d %H:%M UTC")
    date_slug = now.strftime("%Y%m%d")

    if args.rebuild_only:
        since = _as_dt(args.since)
        if since is None:
            sys.exit("error: --rebuild-only needs --since as ISO 8601")
        started = datetime.now(timezone.utc)
        result = rebuild_comparison(c, ecr_client(), since)
        result["runtime_seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
        print(json.dumps(result, indent=2))
        return

    if args.first_seen_only:
        since, until = _as_dt(args.since), (_as_dt(args.until) if args.until else now)
        if since is None or until is None:
            sys.exit("error: --first-seen-only needs --since (and optionally --until) as ISO 8601")
        started = datetime.now(timezone.utc)
        result = first_seen_since(c, since, until)
        result["runtime_seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
        print(json.dumps(result, indent=2))
        return

    # Account ID derived at runtime — keeps it out of source while still
    # appearing in reports and the dashboard header.
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    account = session.client("sts").get_caller_identity()["Account"]

    print("→ account totals ...", flush=True)
    account_resp = paginate_aggregations(
        c, "ACCOUNT",
        {"accountAggregation": {"sortBy": "ALL", "sortOrder": "DESC"}},
    )
    totals = (
        account_resp[0].get("accountAggregation", {}).get("severityCounts", {})
        if account_resp else {}
    )

    print("→ title aggregation (unique CVEs) ...", flush=True)
    title_responses = paginate_aggregations(
        c, "TITLE",
        {"titleAggregation": {"sortBy": "ALL", "sortOrder": "DESC"}},
    )
    title_stats = get_title_stats(title_responses)
    print(f"   {title_stats['unique_count']:,d} unique CVE titles found", flush=True)

    print("→ image layer aggregation (base image identification) ...", flush=True)
    layer_responses = paginate_aggregations(
        c, "IMAGE_LAYER",
        {"imageLayerAggregation": {"sortBy": "ALL", "sortOrder": "DESC"}},
        max_results=100,
        required=False,   # display-only section — degrade rather than fail
    )
    all_layers = get_layer_stats(layer_responses)
    base_layers = all_layers[:BASE_LAYERS_SHOWN]
    layers = all_layers_compact(all_layers)
    print(f"   {len(all_layers)} layers, {len(layers)} with critical+high; top {len(base_layers)} shown", flush=True)

    print("→ package aggregations (all pages) ...", flush=True)
    packages = paginate_aggregations(
        c, "PACKAGE",
        {"packageAggregation": {"sortBy": "ALL", "sortOrder": "DESC"}},
    )

    print("→ repository aggregations ...", flush=True)
    repositories = paginate_aggregations(
        c, "REPOSITORY",
        {"repositoryAggregation": {"sortBy": "ALL", "sortOrder": "DESC"}},
    )

    print("→ AMI aggregations ...", flush=True)
    amis = paginate_aggregations(
        c, "AMI",
        {"amiAggregation": {"sortBy": "AFFECTED_INSTANCES", "sortOrder": "DESC"}},
        max_results=20,
        required=False,   # display-only section — degrade rather than fail
    )

    print("→ coverage counts ...", flush=True)
    coverage = get_coverage_counts(c)

    # Needs the previous snapshot's capture time, so it reads the reports dir
    # even when this run writes nothing.
    reports_dir = None
    if args.reports_dir or os.environ.get("SECURITY_SNAPSHOT_REPORTS_DIR"):
        reports_dir = _resolve_reports_dir(args)
    basis, since = previous_capture(reports_dir, date_slug)
    if since is None:
        print("→ first-seen since last snapshot: no previous snapshot — field left empty", flush=True)
        first_seen = {"status": "no_previous_snapshot", "basis_snapshot": None, "since": None,
                      "until": now.isoformat(), "total": None, "by_resource_type": None,
                      "ecr": None, "by_package": None, "advisory": None}
    else:
        print(f"→ first-seen since last snapshot ({basis}, {since:%Y-%m-%d %H:%M} UTC) ...", flush=True)
        first_seen = first_seen_since(c, since, now, basis)
        if first_seen["total"] is not None:
            print(f"   {first_seen['total']:,d} critical+high findings first seen in the window", flush=True)
    names = [p.get("packageAggregation", {}).get("packageName") for p in packages]
    names = [n for n in names if n]
    known = previous_package_managers(reports_dir, basis)
    print(f"→ package managers ({len(known)} known from the previous snapshot) ...", flush=True)
    manager_rows, manager_stats = package_managers(c, names, known)
    print(f"   queried {manager_stats['queried']}, reused {manager_stats['reused']}, "
          f"unknown {manager_stats['unknown']}", flush=True)
    managers = {r["package"]: r["manager"] for r in manager_rows}
    lever_pkgs = {n for n in names if n in KERNEL_PACKAGES or managers.get(n) == "GENERIC"}
    print(f"→ per-repo breakdown for {len(lever_pkgs)} kernel-header and bundled-runtime packages ...", flush=True)
    repo_names = [r.get("repositoryAggregation", {}).get("repository") for r in repositories]
    breakdown = package_breakdown(c, lever_pkgs, [r for r in repo_names if r], kernel_names=KERNEL_PACKAGES)
    print("→ node scan ...", flush=True)
    nodes = node_scan(c)
    print("→ node OS release ...", flush=True)
    session_ro = boto3.Session(profile_name=PROFILE, region_name=REGION)
    os_release = node_os(session_ro.client("ec2"), session_ro.client("ssm"))
    if since is None:
        rebuild = {"status": "no_previous_snapshot", "basis_snapshot": None, "since": None,
                   "repos": None, "not_comparable": None, "totals": None}
    else:
        print("→ rebuilt vs older images, per repo ...", flush=True)
        rebuild = rebuild_comparison(c, ecr_client(), since, basis)

    raw = {
        "generated_at":  ts,
        "account":       account,
        "region":        REGION,
        "account_totals": totals,
        "title_stats":   title_stats,
        "base_layers":   base_layers,
        "layers":        layers if layer_responses else None,
        "packages":      packages,
        "repositories":  repositories,
        "amis":          amis,
        "coverage":      coverage,
        "first_seen":    first_seen,
        "rebuild_comparison": rebuild,
        "package_managers": manager_rows,
        "package_managers_stats": manager_stats,
        "package_breakdown": breakdown,
        "node_scan":     nodes,
        "node_os":       os_release,
    }

    report = build_report(raw)
    print("\n" + report)

    date_dir = None
    if args.save or args.raw:
        date_dir = _resolve_reports_dir(args) / date_slug
        date_dir.mkdir(parents=True, exist_ok=True)

    if args.save:
        path = date_dir / "posture.md"
        path.write_text(report)
        print(f"\n✓ Saved report → {path}", file=sys.stderr)

    if args.raw:
        # Exclude the full title_responses (10K entries) from the JSON —
        # title_stats already contains the aggregated summary and top 50.
        path = date_dir / "raw.json"
        path.write_text(json.dumps(raw, indent=2, default=str))
        print(f"✓ Saved raw data → {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
