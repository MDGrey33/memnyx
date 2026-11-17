#!/usr/bin/env python3
"""Turn real snapshot folders into a masked test-fixture set.

Every identifier that could tie a snapshot to its owner (AWS account, GitHub
org, repository names, ECR namespaces, image-layer digests, AMI ids) is
replaced with a fake alias. Package names, CVE ids, severities, dates and
counts stay real, so the arithmetic in the fixtures stays realistic.

Fail-closed: every string field in the input must be classified in FIELD_ROLES,
either as an identifier role or as PUBLIC. An unclassified field stops the run,
so a field added to a collector later cannot reach a fixture unmasked.

Aliases are assigned in one pass over the whole set, so the same real repo
gets the same alias on every date. No mapping file is written: a regeneration
renames everything, which is fine because tests assert on arithmetic and
structure, never on names. Fake values are derived from the alias, never from
the real value, so nothing in a fixture can be reversed.

Usage:
    fixture_mask.py --reports-dir <dir> --dates 20260923 20261007 --out <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SNAPSHOT_FILES = ("raw.json", "github-raw.json", "correlation.json", "snapshot.json")

FAKE_ACCOUNT = "123456789012"
FAKE_ORG = "example-org"
FAKE_REGION = "xx-example-1"

# Role of every string field, keyed "<file>:<path>". `[]` marks a list element.
# ECR_REPO is a full "namespace/name"; REPO is a bare name. Both map the name
# part to the same alias, because correlation matches on the basename.
FIELD_ROLES = {
    # raw.json — Inspector
    "raw.json:.account": "ACCOUNT",
    "raw.json:.packages[].packageAggregation.accountId": "ACCOUNT",
    "raw.json:.repositories[].repositoryAggregation.accountId": "ACCOUNT",
    "raw.json:.amis[].amiAggregation.accountId": "ACCOUNT",
    "raw.json:.repositories[].repositoryAggregation.repository": "ECR_REPO",
    "raw.json:.base_layers[].repo_list[]": "ECR_REPO",
    "raw.json:.base_layers[].layer": "LAYER",
    "raw.json:.layers[].layer": "LAYER",
    "raw.json:.layers[].repo_list[]": "ECR_REPO",
    "raw.json:.package_managers[].package": "PUBLIC",
    "raw.json:.package_managers[].manager": "PUBLIC",
    "raw.json:.amis[].amiAggregation.ami": "AMI",
    "raw.json:.generated_at": "PUBLIC",
    "raw.json:.region": "REGION",
    "raw.json:.title_stats.top_by_ch[].title": "PUBLIC",
    "raw.json:.packages[].packageAggregation.packageName": "PUBLIC",
    "raw.json:.first_seen.status": "PUBLIC",
    "raw.json:.first_seen.basis_snapshot": "PUBLIC",
    "raw.json:.first_seen.since": "PUBLIC",
    "raw.json:.first_seen.until": "PUBLIC",
    "raw.json:.first_seen.by_package[].package": "PUBLIC",
    "raw.json:.rebuild_comparison.status": "PUBLIC",
    "raw.json:.rebuild_comparison.basis_snapshot": "PUBLIC",
    "raw.json:.rebuild_comparison.since": "PUBLIC",
    "raw.json:.rebuild_comparison.flag_rule": "PUBLIC",
    "raw.json:.rebuild_comparison.repos[].repo": "ECR_REPO",
    "raw.json:.rebuild_comparison.not_comparable[].repo": "ECR_REPO",
    "raw.json:.rebuild_comparison.not_comparable[].reason": "PUBLIC",
    "raw.json:.package_breakdown.status": "PUBLIC",
    "raw.json:.package_breakdown.packages[]": "PUBLIC",
    "raw.json:.package_breakdown.rows[].package": "PUBLIC",
    "raw.json:.package_breakdown.rows[].repo": "ECR_REPO",
    "raw.json:.package_breakdown.rows[].platforms[]": "PUBLIC",
    "raw.json:.package_breakdown.rows[].versions[]": "PUBLIC",
    "raw.json:.package_breakdown.rows[].layers[].layer": "LAYER",
    "raw.json:.package_breakdown.kernel_repos[].repo": "ECR_REPO",
    "raw.json:.package_breakdown.kernel_repos[].platforms[]": "PUBLIC",
    "raw.json:.package_breakdown.kernel_repos[].versions[]": "PUBLIC",
    "raw.json:.package_breakdown.kernel_repos[].layers[].layer": "LAYER",
    "raw.json:.node_scan.status": "PUBLIC",
    "raw.json:.node_scan.platforms[].platform": "PUBLIC",
    "raw.json:.node_os.status": "PUBLIC",
    "raw.json:.node_os.nodes[].os": "PUBLIC",
    "raw.json:.node_os.nodes[].k8s": "PUBLIC",
    "raw.json:.node_os.nodes[].arch": "PUBLIC",
    "raw.json:.node_os.nodes[].version": "PUBLIC",
    "raw.json:.node_os.nodes[].image_created": "PUBLIC",
    "raw.json:.node_os.nodes[].latest": "PUBLIC",
    "raw.json:.node_os.nodes[].latest_published": "PUBLIC",
    "raw.json:.node_os.other_archs[]": "PUBLIC",
    "raw.json:.scan_coverage.status": "PUBLIC",
    "raw.json:.scan_coverage.windows.push": "PUBLIC",
    "raw.json:.scan_coverage.windows.use": "PUBLIC",
    "raw.json:.scan_coverage.windows.mode": "PUBLIC",
    "raw.json:.scan_coverage.images[].repo": "ECR_REPO",
    "raw.json:.scan_coverage.images[].digest": "LAYER",
    "raw.json:.scan_coverage.images[].status": "PUBLIC",
    "raw.json:.scan_coverage.images[].reason": "PUBLIC",
    "raw.json:.scan_coverage.images[].pushed_at": "PUBLIC",
    "raw.json:.scan_coverage.images[].last_in_use_at": "PUBLIC",
    "raw.json:.scan_coverage.images[].last_pulled_at": "PUBLIC",
    "raw.json:.scan_coverage.images[].last_scanned_at": "PUBLIC",
    "raw.json:.scan_coverage.images[].lapse_at": "PUBLIC",
    "raw.json:.scan_coverage.images[].platforms[].digest": "LAYER",
    "raw.json:.scan_coverage.images[].platforms[].platform": "PUBLIC",
    "raw.json:.scan_coverage.functions[].function": "FUNCTION",
    "raw.json:.scan_coverage.functions[].repo": "ECR_REPO",
    "raw.json:.scan_coverage.functions[].digest": "LAYER",
    "raw.json:.scan_coverage.functions[].last_modified": "PUBLIC",
    "raw.json:.scan_coverage.functions[].status": "PUBLIC",
    "raw.json:.scan_coverage.functions[].reason": "PUBLIC",
    "raw.json:.scan_coverage.functions[].lapse_at": "PUBLIC",
    "raw.json:.scan_coverage.functions[].pushed_at": "PUBLIC",
    "raw.json:.scan_coverage.functions[].last_pulled_at": "PUBLIC",
    # github-raw.json
    "github-raw.json:.org": "ORG",
    "github-raw.json:.vuln_agg.top_repos[].repo": "REPO",
    "github-raw.json:.vuln_agg.no_fix_critical_high[].repo": "REPO",
    "github-raw.json:.code_scanning[].repo": "REPO",
    "github-raw.json:.vuln_alerts_detail[].repo": "REPO",
    "github-raw.json:.secret_scanning[].repo": "REPO",
    "github-raw.json:.generated_at": "PUBLIC",
    "github-raw.json:.vuln_agg.top_packages[].package": "PUBLIC",
    "github-raw.json:.vuln_agg.top_packages[].cves[]": "PUBLIC",
    "github-raw.json:.vuln_agg.no_fix_critical_high[].package": "PUBLIC",
    "github-raw.json:.vuln_agg.no_fix_critical_high[].severity": "PUBLIC",
    "github-raw.json:.vuln_agg.no_fix_critical_high[].cve": "PUBLIC",
    "github-raw.json:.vuln_agg.no_fix_critical_high[].summary": "PUBLIC",
    "github-raw.json:.code_scanning_status": "PUBLIC",
    "github-raw.json:.code_scanning[].rule_id": "PUBLIC",
    "github-raw.json:.code_scanning[].severity": "PUBLIC",
    "github-raw.json:.code_scanning[].tool": "PUBLIC",
    "github-raw.json:.code_scanning[].state": "PUBLIC",
    "github-raw.json:.code_scanning[].created": "PUBLIC",
    "github-raw.json:.secret_scanning_status": "PUBLIC",
    "github-raw.json:.secret_scanning[].secret_type": "PUBLIC",
    "github-raw.json:.secret_scanning[].state": "PUBLIC",
    "github-raw.json:.secret_scanning[].created": "PUBLIC",
    "github-raw.json:.vuln_alerts_detail[].severity": "PUBLIC",
    "github-raw.json:.vuln_alerts_detail[].summary": "PUBLIC",
    "github-raw.json:.vuln_alerts_detail[].cve": "PUBLIC",
    "github-raw.json:.vuln_alerts_detail[].package": "PUBLIC",
    "github-raw.json:.vuln_alerts_detail[].ecosystem": "PUBLIC",
    "github-raw.json:.vuln_alerts_detail[].vuln_range": "PUBLIC",
    "github-raw.json:.vuln_alerts_detail[].state": "PUBLIC",
    "github-raw.json:.vuln_alerts_detail[].created": "PUBLIC",
    "github-raw.json:.vuln_alerts_detail[].patched": "PUBLIC",
    # correlation.json
    "correlation.json:.correlation.offender_convergence[].repo": "REPO",
    "correlation.json:.correlation.repo_combined_ranking[].repo": "REPO",
    "correlation.json:.correlation.zone_a_cve_overlap[].gh_repos[]": "REPO",
    "correlation.json:.correlation.zone_c_github_only[].repos[]": "REPO",
    "correlation.json:.correlation.offender_convergence[].signals[]": "PUBLIC",
    "correlation.json:.correlation.package_quickwin[].effort_label": "PUBLIC",
    "correlation.json:.correlation.package_quickwin[].package": "PUBLIC",
    "correlation.json:.correlation.package_quickwin[].patched": "PUBLIC",
    "correlation.json:.correlation.zone_a_cve_overlap[].cve": "PUBLIC",
    "correlation.json:.correlation.zone_a_cve_overlap[].package": "PUBLIC",
    "correlation.json:.correlation.zone_a_pkg_overlap[].package": "PUBLIC",
    "correlation.json:.correlation.zone_b_inspector_only[].cve": "PUBLIC",
    "correlation.json:.correlation.zone_b_inspector_only[].package": "PUBLIC",
    "correlation.json:.correlation.zone_b_inspector_only[].title": "PUBLIC",
    "correlation.json:.correlation.zone_c_github_only[].cve": "PUBLIC",
    "correlation.json:.correlation.zone_c_github_only[].package": "PUBLIC",
    "correlation.json:.correlation.zone_c_github_only[].severity": "PUBLIC",
    "correlation.json:.generated_at": "PUBLIC",
    "correlation.json:.inputs.github": "PUBLIC",
    "correlation.json:.inputs.inspector": "PUBLIC",
    # snapshot.json
    "snapshot.json:.account": "ACCOUNT",
    "snapshot.json:.inspector.top_repos[].name": "REPO",
    "snapshot.json:.github.cs_by_repo[].repo": "REPO",
    "snapshot.json:.github.top_repos[].repo": "REPO",
    "snapshot.json:.github.secrets_by_repo[].repo": "REPO",
    "snapshot.json:.correlation.convergence[].repo": "REPO",
    "snapshot.json:.correlation.repo_ranking[].repo": "REPO",
    "snapshot.json:.generated_at": "PUBLIC",
    "snapshot.json:.region": "REGION",
    "snapshot.json:.inspector.top_pkgs[].name": "PUBLIC",
    "snapshot.json:.github.top_pkgs[].package": "PUBLIC",
    "snapshot.json:.github.top_pkgs[].cves[]": "PUBLIC",
    "snapshot.json:.github.secrets_by_type[].type": "PUBLIC",
    "snapshot.json:.correlation.convergence[].signals[]": "PUBLIC",
    "snapshot.json:.correlation.pkg_quickwin[].pkg": "PUBLIC",
    "snapshot.json:.correlation.pkg_quickwin[].label": "PUBLIC",
    "snapshot.json:.correlation.pkg_quickwin[].color": "PUBLIC",
}

# LAYER also covers image digests: the same sha256 shape, aliased the same way.
IDENTIFIER_ROLES = {"ACCOUNT", "ORG", "ECR_REPO", "REPO", "LAYER", "AMI", "REGION", "FUNCTION"}

# Alias grammar. The committed fixture test asserts every identifier position
# matches its pattern, which works upstream where no real data exists.
ALIAS_PATTERNS = {
    "ACCOUNT": re.compile(rf"^{FAKE_ACCOUNT}$"),
    "ORG": re.compile(rf"^{FAKE_ORG}$"),
    "REGION": re.compile(rf"^{FAKE_REGION}$"),
    "REPO": re.compile(r"^svc-\d{2,}$"),
    "ECR_REPO": re.compile(r"^ns-\d+/svc-\d{2,}$"),
    "LAYER": re.compile(r"^sha256:[0-9a-f]{64}$"),
    "AMI": re.compile(r"^ami-[0-9a-f]{17}$"),
    "FUNCTION": re.compile(r"^fn-\d{2,}$"),
}


class UnclassifiedField(Exception):
    pass


class LeakDetected(Exception):
    pass


def iter_strings(obj, path=""):
    """Yield (path, value) for every string leaf. List elements use `[]`."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from iter_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_strings(v, f"{path}[]")
    elif isinstance(obj, str):
        yield path, obj


def map_strings(obj, fn, path=""):
    """Return a copy of obj with every string leaf replaced by fn(path, value)."""
    if isinstance(obj, dict):
        return {k: map_strings(v, fn, f"{path}.{k}") for k, v in obj.items()}
    if isinstance(obj, list):
        return [map_strings(v, fn, f"{path}[]") for v in obj]
    if isinstance(obj, str):
        return fn(path, obj)
    return obj


def _split_ecr(value: str) -> tuple[str, str]:
    ns, _, name = value.rpartition("/")
    return ns, name


def _fake_hex(seed: str, length: int) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:length]


def build_aliases(snapshot_set: dict) -> dict:
    """Collect every real identifier across all dates and assign aliases.

    snapshot_set: {date: {filename: parsed_json}}. Raises UnclassifiedField
    on any string field not in FIELD_ROLES.
    """
    names, namespaces, layers, amis, accounts, orgs, regions, functions = set(), set(), set(), set(), set(), set(), set(), set()
    unclassified = set()
    for files in snapshot_set.values():
        for fname, data in files.items():
            for path, value in iter_strings(data):
                role = FIELD_ROLES.get(f"{fname}:{path}")
                if role is None:
                    unclassified.add(f"{fname}:{path}")
                elif role == "ECR_REPO":
                    ns, name = _split_ecr(value)
                    namespaces.add(ns)
                    names.add(name)
                elif role == "REPO":
                    names.add(value)
                elif role == "LAYER":
                    layers.add(value)
                elif role == "AMI":
                    amis.add(value)
                elif role == "ACCOUNT":
                    accounts.add(value)
                elif role == "ORG":
                    orgs.add(value)
                elif role == "REGION":
                    regions.add(value)
                elif role == "FUNCTION":
                    functions.add(value)
    if unclassified:
        raise UnclassifiedField(
            "Unclassified string fields — add each to FIELD_ROLES as an identifier role or PUBLIC:\n  "
            + "\n  ".join(sorted(unclassified)))
    width = max(2, len(str(len(names))))
    return {
        "name": {n: f"svc-{i:0{width}d}" for i, n in enumerate(sorted(names), 1)},
        "ns": {n: f"ns-{i}" for i, n in enumerate(sorted(namespaces), 1)},
        "layer": {v: f"sha256:{_fake_hex(f'layer-{i}', 64)}" for i, v in enumerate(sorted(layers), 1)},
        "ami": {v: f"ami-{_fake_hex(f'ami-{i}', 17)}" for i, v in enumerate(sorted(amis), 1)},
        "account": {v: FAKE_ACCOUNT for v in accounts},
        "org": {v: FAKE_ORG for v in orgs},
        "region": {v: FAKE_REGION for v in regions},
        "function": {v: f"fn-{i:02d}" for i, v in enumerate(sorted(functions), 1)},
    }


def mask_value(role: str, value: str, aliases: dict) -> str:
    if role == "ECR_REPO":
        ns, name = _split_ecr(value)
        return f"{aliases['ns'][ns]}/{aliases['name'][name]}"
    if role == "REPO":
        return aliases["name"][value]
    if role == "LAYER":
        return aliases["layer"][value]
    if role == "AMI":
        return aliases["ami"][value]
    if role == "ACCOUNT":
        return aliases["account"][value]
    if role == "ORG":
        return aliases["org"][value]
    if role == "REGION":
        return aliases["region"][value]
    if role == "FUNCTION":
        return aliases["function"][value]
    return value


def mask_set(snapshot_set: dict) -> tuple[dict, dict]:
    aliases = build_aliases(snapshot_set)
    masked = {}
    for date, files in snapshot_set.items():
        masked[date] = {}
        for fname, data in files.items():
            masked[date][fname] = map_strings(
                data, lambda p, v, f=fname: mask_value(FIELD_ROLES[f"{f}:{p}"], v, aliases))
    return masked, aliases


def trim_alert_detail(snapshot_set: dict, keep_repos: int) -> dict:
    """Keep per-alert GitHub detail for the `keep_repos` repos with most alerts on the
    newest date, the same repos on every date, so instances against distinct
    advisories still compares like with like. Alert detail is most of a fixture's
    size and no fixture test asserts on its totals; the aggregates stay whole.
    """
    newest = max(snapshot_set)
    counts = {}
    if keep_repos < 1:
        raise ValueError("keep_repos must be at least 1")
    for a in (snapshot_set[newest].get("github-raw.json") or {}).get("vuln_alerts_detail") or []:
        if a.get("repo"):
            counts[a["repo"]] = counts.get(a["repo"], 0) + 1
    if not counts:
        raise ValueError(f"{newest} has no GitHub alert detail to choose repos from")
    keep = set(sorted(counts, key=lambda r: (-counts[r], str(r)))[:keep_repos])
    out = {}
    for date, files in snapshot_set.items():
        out[date] = dict(files)
        gh = files.get("github-raw.json")
        if isinstance(gh, dict) and isinstance(gh.get("vuln_alerts_detail"), list):
            out[date]["github-raw.json"] = {**gh, "vuln_alerts_detail": [a for a in gh["vuln_alerts_detail"]
                                                                           if a.get("repo") in keep]}
    return out


def trim_code_scanning(snapshot_set: dict, cap: int) -> dict:
    """Keep at most `cap` code-scanning alerts per date, in a stable order. Only the
    dashboard counts them; the movement code never reads the list."""
    if cap < 1:
        raise ValueError("cap must be at least 1")
    out = {}
    for date, files in snapshot_set.items():
        out[date] = dict(files)
        gh = files.get("github-raw.json")
        if isinstance(gh, dict) and isinstance(gh.get("code_scanning"), list):
            kept = sorted(gh["code_scanning"], key=lambda a: json.dumps(a, sort_keys=True))[:cap]
            out[date]["github-raw.json"] = {**gh, "code_scanning": kept}
    return out


def find_leaks(masked: dict, aliases: dict, extra_terms: tuple[str, ...] = ()) -> list[str]:
    """Search masked output for any real identifier.

    Account, org, namespaces, layers, AMIs and extra_terms are searched as
    substrings of the whole serialised output. Repo names are checked at every
    repo position, and as whole tokens in any field when they contain a hyphen.
    A single-word repo name (`custom`, `curl`) is not searched for in public
    fields: it is also an ordinary word or package name, and on its own it
    identifies nobody.
    """
    leaks = []
    substrings = (set(aliases["account"]) | set(aliases["org"]) | set(aliases["layer"]) | set(aliases["ami"])
                  | set(aliases.get("region", {})) | set(aliases.get("function", {})))
    substrings |= {f"{ns}/" for ns in aliases["ns"] if ns}
    substrings |= {t for t in extra_terms if t}
    real_names = set(aliases["name"])
    hyphenated = [n for n in real_names if "-" in n]
    token_re = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, sorted(hyphenated, key=len, reverse=True))) + r")(?![\w-])") if hyphenated else None
    for date, files in masked.items():
        for fname, data in files.items():
            text = json.dumps(data)
            for s in substrings:
                if s in text:
                    leaks.append(f"{date}/{fname}: contains real value {s!r}")
            for path, value in iter_strings(data):
                role = FIELD_ROLES.get(f"{fname}:{path}")
                if role in ("REPO", "ECR_REPO") and _split_ecr(value)[1] in real_names:
                    leaks.append(f"{date}/{fname}:{path}: real repo name {value!r}")
                elif token_re and token_re.search(value):
                    leaks.append(f"{date}/{fname}:{path}: real repo name inside text {value!r}")
    return leaks


def load_set(reports_dir: Path, dates: list[str]) -> dict:
    snapshot_set = {}
    for d in dates:
        folder = reports_dir / d
        if not folder.is_dir():
            raise SystemExit(f"No snapshot folder {folder}")
        snapshot_set[d] = {f: json.loads((folder / f).read_text()) for f in SNAPSHOT_FILES if (folder / f).exists()}
        if not snapshot_set[d]:
            raise SystemExit(f"{folder} holds none of {SNAPSHOT_FILES}")
    return snapshot_set


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reports-dir", required=True, type=Path)
    ap.add_argument("--dates", required=True, nargs="+")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--alert-repos", type=int, default=None,
                    help="Keep per-alert GitHub detail for only this many repos (the same ones on every date)")
    ap.add_argument("--code-scanning", type=int, default=None,
                    help="Keep at most this many code-scanning alerts per date")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).parent))
    extra = ()
    try:
        from config_util import load_config
        cfg = load_config()
        extra = tuple(v for v in (cfg.get("github_org"), cfg.get("aws_profile")) if v)
    except Exception as e:  # config is optional for masking; the data carries the identifiers
        print(f"warning: config not loaded ({e}); leak check uses data-derived values only", file=sys.stderr)

    snapshot_set = load_set(args.reports_dir, args.dates)
    if args.alert_repos is not None and args.alert_repos < 1:
        ap.error("--alert-repos must be at least 1")
    if args.alert_repos is not None:
        snapshot_set = trim_alert_detail(snapshot_set, args.alert_repos)
    if args.code_scanning is not None:
        if args.code_scanning < 1:
            ap.error("--code-scanning must be at least 1")
        snapshot_set = trim_code_scanning(snapshot_set, args.code_scanning)
    try:
        masked, aliases = mask_set(snapshot_set)
    except UnclassifiedField as e:
        print(e, file=sys.stderr)
        return 2
    leaks = find_leaks(masked, aliases, extra)
    if leaks:
        print("Leak check FAILED — nothing written:\n  " + "\n  ".join(leaks[:20]), file=sys.stderr)
        return 3
    for date, files in masked.items():
        (args.out / date).mkdir(parents=True, exist_ok=True)
        for fname, data in files.items():
            (args.out / date / fname).write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n")
    print(f"Wrote {len(masked)} snapshot(s) to {args.out}: {len(aliases['name'])} repos, "
          f"{len(aliases['ns'])} namespaces, {len(aliases['layer'])} layers, {len(aliases['ami'])} AMIs masked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
