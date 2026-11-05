#!/usr/bin/env python3
"""
github_security_snapshot.py — GitHub security alerts snapshot

Fetches for all repos in an org:
  - Vulnerability alerts (Dependabot)  via GraphQL  — needs: repo, read:org
  - Code scanning alerts               via REST     — needs: security_events (graceful skip if absent)
  - Secret scanning alerts             via REST     — needs: security_events (graceful skip if absent)

Usage:
    python3 github_security_snapshot.py [--org ORG] [--save] [--raw]

The org comes from config.json (github_org); --org overrides for a single run.
The gh CLI must be authenticated as an account with access to that org.
"""
import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone


from config_util import (
    load_config as _load_config,
    require as _require,
    resolve_reports_dir as _resolve_reports_dir,
)

ORG       = _require(_load_config(), "github_org")
GH        = "gh"         # gh CLI binary; must be authenticated


# ── gh helpers ────────────────────────────────────────────────────────────────

GH_TIMEOUT = 120  # seconds per gh call — a stalled network/auth call must not hang the snapshot


def _gh_run(cmd: list[str]) -> subprocess.CompletedProcess:
    """subprocess.run wrapper: every gh call gets a timeout."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=GH_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"gh call timed out after {GH_TIMEOUT}s: {' '.join(cmd[:3])} ...")


def _classify_gh_error(err: str) -> int:
    """
    Map gh error output to a status code. 403 is reserved for true scope/permission
    problems: GitHub also answers HTTP 403 for rate limiting and SSO enforcement,
    and callers treat 403 as "token lacks security_events scope" — misclassifying
    a rate-limited run as a scope gap would make an incomplete snapshot look expected.
    """
    low = err.lower()
    if "rate limit" in low:
        return 429
    if "bad credentials" in low or "sso" in low or "saml" in low or "401" in err:
        return 401
    if "must have admin rights" in low or "not accessible" in low or "oauth scope" in low or "403" in err:
        return 403
    if "not found" in low or "404" in err:
        return 404
    return 500


def gh_graphql(query: str, variables: dict | None = None) -> dict:
    cmd = [GH, "api", "graphql", "-f", f"query={query}"]
    if variables:
        for k, v in variables.items():
            cmd += ["-F", f"{k}={v}"]
    result = _gh_run(cmd)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def gh_rest_paginated(path: str, params: dict | None = None) -> tuple[int, list]:
    """
    GET a paginated REST endpoint, returning (status, all_items).
    Parameters are embedded as URL query string (not -F flags) to avoid
    gh-cli quirks where -F on GET requests may not pass params correctly.
    """
    from urllib.parse import urlencode
    all_items: list = []
    page = 1
    while True:
        qp = dict(params or {})
        qp["per_page"] = qp.get("per_page", "100")
        qp["page"] = str(page)
        url = f"{path}?{urlencode(qp)}"
        result = _gh_run([GH, "api", url])
        if result.returncode != 0:
            return _classify_gh_error(result.stderr + result.stdout), []
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            break
        if not isinstance(data, list):
            return 200, [data] if data else []
        all_items.extend(data)
        if len(data) < int(qp["per_page"]):
            break    # last page
        page += 1
    return 200, all_items


# ── Step 1: list all repos ────────────────────────────────────────────────────

def list_all_repos(org: str) -> list[dict]:
    """Return all non-archived repos with name + vuln alert totalCount."""
    repos = []
    cursor = None
    while True:
        query = """
        query($org: String!, $after: String) {
          organization(login: $org) {
            repositories(first: 50, after: $after, orderBy: {field: NAME, direction: ASC}) {
              pageInfo { hasNextPage endCursor }
              nodes {
                name
                isArchived
                vulnerabilityAlerts(states: OPEN) { totalCount }
                hasVulnerabilityAlertsEnabled
              }
            }
          }
        }"""
        vars = {"org": org}
        if cursor:
            vars["after"] = cursor
        data = gh_graphql(query, vars)
        page = data["data"]["organization"]["repositories"]
        for r in page["nodes"]:
            if not r["isArchived"]:
                repos.append({
                    "name": r["name"],
                    "vuln_total": r["vulnerabilityAlerts"]["totalCount"],
                    "vuln_enabled": r["hasVulnerabilityAlertsEnabled"],
                })
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return repos


# ── Step 2: vulnerability alert details ──────────────────────────────────────

VULN_DETAIL_QUERY = """
query($org: String!, $repo: String!, $after: String) {
  repository(owner: $org, name: $repo) {
    vulnerabilityAlerts(first: 100, after: $after, states: OPEN) {
      pageInfo { hasNextPage endCursor }
      nodes {
        securityAdvisory {
          severity
          summary
          identifiers { type value }
          cvss { score }
        }
        securityVulnerability {
          package { name ecosystem }
          vulnerableVersionRange
          firstPatchedVersion { identifier }
        }
        state
        dismissedAt
        createdAt
      }
    }
  }
}"""


def get_vuln_details(org: str, repo: str) -> list[dict]:
    alerts = []
    cursor = None
    while True:
        vars = {"org": org, "repo": repo}
        if cursor:
            vars["after"] = cursor
        data = gh_graphql(VULN_DETAIL_QUERY, vars)
        page = data["data"]["repository"]["vulnerabilityAlerts"]
        for node in page["nodes"]:
            adv  = node["securityAdvisory"]
            vuln = node["securityVulnerability"]
            cve  = next(
                (i["value"] for i in adv.get("identifiers", []) if i["type"] == "CVE"),
                None,
            )
            alerts.append({
                "repo":       repo,
                "severity":   adv["severity"],
                "summary":    adv["summary"],
                "cve":        cve,
                "cvss":       adv.get("cvss", {}).get("score"),
                "package":    vuln["package"]["name"],
                "ecosystem":  vuln["package"]["ecosystem"],
                "vuln_range": vuln.get("vulnerableVersionRange"),
                "patched":    vuln["firstPatchedVersion"]["identifier"] if vuln["firstPatchedVersion"] else None,
                "fix_available": vuln["firstPatchedVersion"] is not None,
                "state":      node["state"],
                "dismissed":  node["dismissedAt"],
                "created":    node["createdAt"],
            })
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return alerts


# ── Steps 3+4: code scanning + secret scanning (need security_events) ─────────

def _scan_all_repos(org: str, repos: list[str], endpoint: str, label: str,
                    parse) -> tuple[str, list[dict]]:
    """
    Iterate every repo against /repos/{org}/{repo}/{endpoint}, aggregating alerts.
    Scanning availability is per-repo (404 = not enabled on that repo), so org-wide
    state is never concluded from a single probe. Short-circuits only when the first
    few repos ALL return 403 (token genuinely lacks the scope — every repo would
    fail the same way) or on rate-limit / auth failure (further calls just burn
    the limit against a dead token).
    """
    if not repos:
        return "no_repos", []
    alerts: list[dict] = []
    statuses: list[int] = []
    for i, repo in enumerate(repos, 1):
        print(f"   {label} [{i}/{len(repos)}] {repo}", flush=True)
        s, items = gh_rest_paginated(f"/repos/{org}/{repo}/{endpoint}", {"state": "open"})
        statuses.append(s)
        if s == 200:
            alerts.extend(parse(repo, a) for a in items)
        elif s == 429:
            print(f"   WARN: rate limited at {repo} — aborting {label} scan, results are partial",
                  file=sys.stderr)
            return "rate_limited", alerts
        elif s == 401:
            print(f"   WARN: authentication failed at {repo} — aborting {label} scan, results are partial",
                  file=sys.stderr)
            return "auth_error", alerts
    # Decide on the FULL repo set (no early short-circuit — denied repos early in
    # the list must not stop us querying readable ones later). Status meaning:
    #   200 = scanned   403 = denied (alerts may exist but are hidden — a real gap)
    #   404 = scanning not enabled on that repo (expected; nothing to undercount)
    if 403 in statuses and 200 not in statuses:
        # Every accessible repo was denied → token lacks the scope org-wide.
        return "no_scope", []
    if 403 in statuses:
        # Some repos scanned, others denied → loud partial signal.
        return "partial_permissions", alerts
    if 200 in statuses:
        return "ok", alerts
    return "not_enabled", []   # all 404 — scanning simply not enabled anywhere


def get_code_scanning(org: str, repos: list[str]) -> tuple[str, list[dict]]:
    """Returns (status, alerts) across all repos."""
    return _scan_all_repos(org, repos, "code-scanning/alerts", "cs", lambda repo, a: {
        "repo":      repo,
        "rule_id":   a.get("rule", {}).get("id"),
        "severity":  a.get("rule", {}).get("severity"),
        "tool":      a.get("tool", {}).get("name"),
        "state":     a.get("state"),
        "created":   a.get("created_at"),
    })


def get_secret_scanning(org: str, repos: list[str]) -> tuple[str, list[dict]]:
    """Returns (status, alerts) across all repos."""
    return _scan_all_repos(org, repos, "secret-scanning/alerts", "ss", lambda repo, a: {
        "repo":        repo,
        "secret_type": a.get("secret_type"),
        "state":       a.get("state"),
        "created":     a.get("created_at"),
        "resolved":    a.get("resolved_at"),
    })


# ── Aggregation ───────────────────────────────────────────────────────────────

SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}


def aggregate_vuln(alerts: list[dict]) -> dict:
    by_severity = defaultdict(int)
    by_repo     = defaultdict(lambda: defaultdict(int))
    by_package  = defaultdict(lambda: {"repos": set(), "c": 0, "h": 0, "m": 0, "l": 0, "no_fix": 0, "cves": set()})
    no_fix      = []

    for a in alerts:
        s = a["severity"]
        by_severity[s] += 1
        by_repo[a["repo"]][s] += 1

        p = a["package"]
        by_package[p]["repos"].add(a["repo"])
        key = {"CRITICAL": "c", "HIGH": "h", "MODERATE": "m", "LOW": "l"}.get(s, "l")
        by_package[p][key] += 1
        if not a["fix_available"]:
            by_package[p]["no_fix"] += 1
        if a["cve"]:
            by_package[p]["cves"].add(a["cve"])
        if not a["fix_available"] and s in ("CRITICAL", "HIGH"):
            no_fix.append(a)

    # Serialise sets
    pkg_list = [
        {
            "package": pkg,
            "repos": len(v["repos"]),
            "critical": v["c"], "high": v["h"], "moderate": v["m"], "low": v["l"],
            "no_fix": v["no_fix"],
            "cves": sorted(v["cves"]),
        }
        for pkg, v in by_package.items()
    ]
    pkg_list.sort(key=lambda x: (x["critical"] + x["high"]) * -1)

    repo_list = [
        {"repo": repo, **dict(counts)}
        for repo, counts in by_repo.items()
    ]
    repo_list.sort(key=lambda x: x.get("CRITICAL", 0) + x.get("HIGH", 0), reverse=True)

    return {
        "total": len(alerts),
        "by_severity": dict(by_severity),
        "top_repos": repo_list,
        "top_packages": pkg_list[:50],
        "no_fix_critical_high": [
            {"repo": a["repo"], "package": a["package"], "severity": a["severity"],
             "cve": a["cve"], "summary": a["summary"]}
            for a in sorted(no_fix, key=lambda x: SEV_ORDER.get(x["severity"], 9))[:NO_FIX_ROWS]
        ],
        "no_fix_critical_high_total": len(no_fix),
    }


NO_FIX_ROWS = 30


# ── Report builder ────────────────────────────────────────────────────────────

def md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(lines)


def build_report(raw: dict) -> str:
    ts  = raw["generated_at"]
    org = raw["org"]
    va  = raw.get("vuln_agg", {})
    cs_status  = raw.get("code_scanning_status", "unknown")
    ss_status  = raw.get("secret_scanning_status", "unknown")
    notes = []
    if "no_scope" in (cs_status, ss_status):
        notes.append("> **Code scanning and/or secret scanning unavailable**: "
                     "add `security_events` scope to the GitHub token to enable these.")
    if "partial_permissions" in (cs_status, ss_status):
        notes.append("> **Some repos denied (403) during scanning** — counts below are partial; "
                     "check repo-level permissions and rerun once access is granted.")
    if "rate_limited" in (cs_status, ss_status):
        notes.append("> **GitHub API rate limit hit mid-scan** — scanning counts below are "
                     "partial; rerun after the limit resets.")
    if "auth_error" in (cs_status, ss_status):
        notes.append("> **Authentication failed mid-scan** (token expiry / SSO) — scanning "
                     "counts below are partial; re-authenticate and rerun.")
    fails = raw.get("vuln_fetch_failures", [])
    if fails:
        notes.append(f"> **Vulnerability data missing for {len(fails)} repo(s)**: "
                     f"{', '.join(fails)} — counts undercount these; rerun to refetch.")
    scope_note = ("\n" + "\n".join(notes) + "\n") if notes else ""

    lines = [
        "# GitHub Security Snapshot",
        "",
        f"**Generated**: {ts}  |  **Org**: {org}",
        scope_note,
        "## Coverage",
        "",
        md_table(
            ["Source", "Status", "Total alerts"],
            [
                ("Vulnerability alerts (Dependabot)", f"⚠ {len(fails)} repo(s) failed" if fails else "✓ active",
                 f"{va.get('total', 0):,d}"),
                ("Code scanning",   "✓ active" if cs_status == "ok" else f"⚠ {cs_status}", str(len(raw.get("code_scanning", [])))),
                ("Secret scanning", "✓ active" if ss_status == "ok" else f"⚠ {ss_status}", str(len(raw.get("secret_scanning", [])))),
            ],
        ),
        "",
        "## Vulnerability Alerts (Dependabot)",
        "",
    ]

    if va:
        sev = va.get("by_severity", {})
        lines += [
            md_table(
                ["Severity", "Count"],
                [
                    ("CRITICAL", f"{sev.get('CRITICAL', 0):,d}"),
                    ("HIGH",     f"{sev.get('HIGH', 0):,d}"),
                    ("MODERATE", f"{sev.get('MODERATE', 0):,d}"),
                    ("LOW",      f"{sev.get('LOW', 0):,d}"),
                    ("**Total**", f"**{va['total']:,d}**"),
                ],
            ),
            "",
            "### Top Repositories by CRITICAL+HIGH",
            "",
            md_table(
                ["Repository", "CRITICAL", "HIGH", "MODERATE", "LOW"],
                [
                    [r["repo"], r.get("CRITICAL", 0), r.get("HIGH", 0), r.get("MODERATE", 0), r.get("LOW", 0)]
                    for r in va.get("top_repos", [])[:20]
                ],
            ),
            "",
            "### Top Packages by CRITICAL+HIGH",
            "",
            md_table(
                ["Package", "CRITICAL", "HIGH", "MODERATE", "Repos", "No-fix", "CVEs"],
                [
                    [p["package"], p["critical"], p["high"], p["moderate"],
                     p["repos"], p["no_fix"], ", ".join(p["cves"][:3]) or "–"]
                    for p in va.get("top_packages", [])[:25]
                ],
            ),
        ]

        if va.get("no_fix_critical_high"):
            lines += [
                "",
                "### CRITICAL/HIGH with No Fix Available",
                f"> No patched version published yet. Showing {len(va['no_fix_critical_high'])} of "
                f"{va.get('no_fix_critical_high_total', len(va['no_fix_critical_high']))}.",
                "",
                md_table(
                    ["Repository", "Package", "Severity", "CVE", "Summary"],
                    [
                        [a["repo"], a["package"], a["severity"], a["cve"] or "–",
                         a["summary"][:70]]
                        for a in va["no_fix_critical_high"]
                    ],
                ),
            ]

    if cs_status == "ok" and raw.get("code_scanning"):
        cs = raw["code_scanning"]
        by_sev = defaultdict(int)
        for a in cs:
            by_sev[a.get("severity", "unknown")] += 1
        lines += [
            "",
            "## Code Scanning Alerts",
            "",
            md_table(
                ["Severity", "Count"],
                [(s, c) for s, c in sorted(by_sev.items(), key=lambda x: SEV_ORDER.get(x[0].upper(), 9))],
            ),
        ]

    if ss_status == "ok" and raw.get("secret_scanning"):
        ss = raw["secret_scanning"]
        by_type = defaultdict(int)
        for a in ss:
            by_type[a.get("secret_type", "unknown")] += 1
        lines += [
            "",
            "## Secret Scanning Alerts",
            "",
            f"Total: {len(ss)} open alerts.",
            "",
            md_table(
                ["Secret type", "Count"],
                sorted(by_type.items(), key=lambda x: -x[1]),
            ),
        ]

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GitHub security alerts snapshot")
    parser.add_argument("--org",  default=ORG, help=f"GitHub org (default: {ORG})")
    parser.add_argument("--save", action="store_true", help="Write .md report to reports_dir")
    parser.add_argument("--raw",  action="store_true", help="Write raw .json to reports_dir")
    parser.add_argument("--reports-dir", help="Directory for snapshot read/write (overrides $SECURITY_SNAPSHOT_REPORTS_DIR)")
    args = parser.parse_args()
    org = args.org

    now       = datetime.now(timezone.utc)   # one clock read — ts and date_slug must agree across midnight
    ts        = now.strftime("%Y-%m-%d %H:%M UTC")
    date_slug = now.strftime("%Y%m%d")

    # Step 1: list repos
    print(f"→ listing repos for {org} ...", flush=True)
    repos = list_all_repos(org)
    active_repos = [r["name"] for r in repos]
    repos_with_alerts = [r["name"] for r in repos if r["vuln_total"] > 0]
    print(f"   {len(repos)} repos total, {len(repos_with_alerts)} with open vulnerability alerts", flush=True)

    # Step 2: vulnerability alert details
    print("→ fetching vulnerability alert details ...", flush=True)
    all_vuln = []
    failed_repos: list[str] = []
    for i, repo in enumerate(repos_with_alerts, 1):
        print(f"   [{i}/{len(repos_with_alerts)}] {repo}", flush=True)
        try:
            all_vuln.extend(get_vuln_details(org, repo))
        except Exception as e:
            failed_repos.append(repo)
            print(f"   WARN: {repo} failed: {e}", flush=True)
    print(f"   {len(all_vuln)} vulnerability alerts fetched", flush=True)
    if failed_repos:
        # Partial data is acceptable only when it is loudly partial: the failures
        # travel with the artefact (raw + report) so downstream consumers see the
        # gap, and the user is prompted to refetch. Past ~10% the undercount would
        # make headline numbers misleading — refuse to mint that snapshot.
        print(f"\n⚠ vulnerability fetch FAILED for {len(failed_repos)}/{len(repos_with_alerts)} repos: "
              f"{', '.join(failed_repos)}\n  Counts undercount these repos — rerun later to refetch.",
              file=sys.stderr)
        if len(failed_repos) > 0.10 * len(repos_with_alerts):
            sys.exit("error: >10% of repos failed vulnerability fetch — refusing to save a "
                     "misleading snapshot; rerun when GitHub is reachable")
    vuln_agg = aggregate_vuln(all_vuln)

    # Step 3: code scanning
    print("→ code scanning (all repos) ...", flush=True)
    cs_status, cs_alerts = get_code_scanning(org, active_repos)
    print(f"   {len(cs_alerts)} open code scanning alerts ({cs_status})", flush=True)

    # Step 4: secret scanning
    print("→ secret scanning ...", flush=True)
    ss_status, ss_alerts = get_secret_scanning(org, active_repos)
    print(f"   {len(ss_alerts)} open secret scanning alerts ({ss_status})", flush=True)

    raw = {
        "generated_at":           ts,
        "org":                    org,
        "repos_total":            len(repos),
        "repos_with_vuln_alerts": len(repos_with_alerts),
        "vuln_agg":               vuln_agg,
        "code_scanning_status":   cs_status,
        "code_scanning":          cs_alerts,
        "secret_scanning_status": ss_status,
        "secret_scanning":        ss_alerts,
        "vuln_fetch_failures":    failed_repos,
        # Store full alert list for correlation with Inspector data
        "vuln_alerts_detail":     all_vuln,
    }

    report = build_report(raw)
    print("\n" + report)

    date_dir = None
    if args.save or args.raw:
        date_dir = _resolve_reports_dir(args) / date_slug
        date_dir.mkdir(parents=True, exist_ok=True)
    if args.save:
        path = date_dir / "github.md"
        path.write_text(report)
        print(f"\n✓ Saved report → {path}", file=sys.stderr)
    if args.raw:
        path = date_dir / "github-raw.json"
        path.write_text(json.dumps(raw, indent=2, default=str))
        print(f"✓ Saved raw data → {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
