#!/usr/bin/env python3
"""
build_dashboard.py — Generate security-dashboard.html.

Each run saves a slim snapshot-YYYYMMDD.json (~15KB) alongside the full
correlation output. The dashboard embeds ALL available snapshots so the
reader can switch between dates without regenerating the file.

Usage:
    python3 build_dashboard.py              # auto-detect latest correlation-*.json
    python3 build_dashboard.py correlation-20260512.json

Output: security-dashboard.html — single file, all snapshot data embedded
        (no backend); chart and font libraries load from CDN, so rendering
        needs internet access. Works on file://, web server, and Google Apps
        Script HtmlService.
"""
import argparse
import json
import os
import re
import sys
from html import escape as html_escape
from collections import defaultdict
from pathlib import Path


from config_util import (
    load_config as _load_config,
    require as _require,
    resolve_reports_dir as _resolve_reports_dir,
)

_CFG  = _load_config()
ORG   = _require(_CFG, "github_org")
TITLE = (_CFG.get("dashboard_title") or "").strip() or "Security Dashboard"

# Event annotations rendered as vertical markers on the Trend tab.
# Maintained in config.json ("annotations") — add an entry whenever a
# significant remediation action or disclosure lands.
ANNOTATIONS = _CFG.get("annotations") or []


# ── Utilities ──────────────────────────────────────────────────────────────────

def latest_file(filename: str, reports_dir: Path) -> "Path | None":
    """Find the most recent dated-folder containing `filename` (e.g. 'correlation.json')."""
    files = sorted(reports_dir.glob(f"*/{filename}"),
                   key=lambda p: p.parent.name, reverse=True)
    return files[0] if files else None

def load(path: Path) -> dict:
    return json.loads(path.read_text())

def date_slug(path: Path) -> str:
    """For a file inside a dated folder, the date is the parent folder name."""
    return path.parent.name


# ── Extract: full correlation JSON → slim dashboard payload (~15KB) ────────────

def extract(corr_path: Path, reports_dir: Path) -> dict:
    corr_data  = load(corr_path)
    # Inputs are siblings of corr_path inside the same dated folder. Missing
    # siblings are a hard error: falling back to {} would mint a zeroed
    # snapshot into the immutable trend history instead of surfacing that the
    # input set is incomplete.
    inputs     = corr_data.get("inputs", {})
    insp_name  = inputs.get("inspector")
    gh_name    = inputs.get("github")
    if not insp_name or not gh_name:
        sys.exit(f"error: {corr_path} does not name its raw input files — regenerate the correlation")
    insp_path  = corr_path.parent / insp_name
    gh_path    = corr_path.parent / gh_name
    missing    = [p.name for p in (insp_path, gh_path) if not p.is_file()]
    if missing:
        sys.exit(f"error: missing sibling input(s) next to {corr_path.name}: {', '.join(missing)} — "
                 "refusing to build a zeroed dashboard")
    insp_raw   = load(insp_path)
    gh_raw     = load(gh_path)
    corr       = corr_data.get("correlation", {})
    gh_vuln    = gh_raw.get("vuln_agg", {})
    totals     = insp_raw.get("account_totals", {})
    ts         = insp_raw.get("title_stats", {})

    ss_by_type: dict = defaultdict(int)
    ss_by_repo: dict = defaultdict(int)
    for a in gh_raw.get("secret_scanning", []):
        ss_by_type[a.get("secret_type", "unknown")] += 1
        ss_by_repo[a.get("repo",         "unknown")] += 1

    cs_by_sev:  dict = defaultdict(int)
    cs_by_repo: dict = defaultdict(int)
    for a in gh_raw.get("code_scanning", []):
        cs_by_sev[a.get("severity", "?")]  += 1
        cs_by_repo[a.get("repo",     "?")] += 1

    # Cross-source severity buckets (mirror GitHub Security Overview).
    # CS rule-level severity isn't tracked — approximate: error→High, warning→Medium.
    # Secrets counted as Critical. Drift vs GitHub UI typically ≤5 per bucket.
    _vuln_total    = gh_vuln.get("total", 0)
    _vuln_critical = gh_vuln.get("by_severity", {}).get("CRITICAL", 0)
    _vuln_high     = gh_vuln.get("by_severity", {}).get("HIGH",     0)
    _vuln_mod      = gh_vuln.get("by_severity", {}).get("MODERATE", 0)
    _code_total    = sum(cs_by_sev.values())
    _code_errors   = cs_by_sev.get("error", 0)
    _code_warn     = max(_code_total - _code_errors, 0)
    _secrets       = len(gh_raw.get("secret_scanning", []))
    sev_critical = _vuln_critical + _secrets
    sev_high     = _vuln_high     + _code_errors
    sev_medium   = _vuln_mod      + _code_warn
    sev_low      = max(_vuln_total - _vuln_critical - _vuln_high - _vuln_mod, 0)

    EFFORT_COLOR = {"Trivial":"#22c55e","Bounded":"#3b82f6","Phantom":"#64748b","Structural":"#a855f7"}
    qw_chart = [
        {
            "pkg":   p["package"][:30],
            "effort": p["effort"],
            "label":  p["effort_label"],
            "x": p["effort"],
            "y": p["combined_ch"],
            "r": min(35, max(6, (p["quickwin_score"] / 15000) ** 0.5 * 20)),
            "repos":    p["gh_repos"],
            "insp_ch":  p["insp_crit"] + p["insp_high"],
            "gh_ch":    p["gh_crit"]   + p["gh_high"],
            "fix":   p["fix_available"],
            "score": p["quickwin_score"],
            "color": EFFORT_COLOR.get(p["effort_label"], "#94a3b8"),
        }
        for p in corr.get("package_quickwin", [])[:40]
    ]

    insp_repos = sorted(
        insp_raw.get("repositories", []),
        key=lambda x: x.get("repositoryAggregation",{}).get("severityCounts",{}).get("critical",0)
                    + x.get("repositoryAggregation",{}).get("severityCounts",{}).get("high",0),
        reverse=True,
    )[:12]

    zone_s = corr.get("summary", {})

    return {
        "generated_at": corr_data.get("generated_at", ""),
        "account":      insp_raw.get("account", ""),
        "region":       insp_raw.get("region",  ""),
        "inspector": {
            "critical":    totals.get("critical", 0),
            "high":        totals.get("high",     0),
            "medium":      totals.get("medium",   0),
            "unique_cves": ts.get("unique_count", 0),
            "fanout":      round(
                (totals.get("critical",0)+totals.get("high",0)+totals.get("medium",0))
                / max(ts.get("unique_count",1), 1)
            ),
            "top_repos": [
                {
                    "name": r.get("repositoryAggregation",{}).get("repository","").split("/")[-1],
                    "c":    r.get("repositoryAggregation",{}).get("severityCounts",{}).get("critical",0),
                    "h":    r.get("repositoryAggregation",{}).get("severityCounts",{}).get("high",0),
                    "m":    r.get("repositoryAggregation",{}).get("severityCounts",{}).get("medium",0),
                }
                for r in insp_repos
            ],
            "top_pkgs": [
                {
                    "name": p.get("packageAggregation",{}).get("packageName",""),
                    "c":    p.get("packageAggregation",{}).get("severityCounts",{}).get("critical",0),
                    "h":    p.get("packageAggregation",{}).get("severityCounts",{}).get("high",0),
                }
                for p in insp_raw.get("packages",[])[:15]
            ],
        },
        "github": {
            "vuln_total":    _vuln_total,
            "vuln_critical": _vuln_critical,
            "vuln_high":     _vuln_high,
            "vuln_mod":      _vuln_mod,
            "code_total":    _code_total,
            "code_errors":   _code_errors,
            "secrets_total": _secrets,
            "security_total":_vuln_total + _code_total + _secrets,
            "sev_critical":  sev_critical,
            "sev_high":      sev_high,
            "sev_medium":    sev_medium,
            "sev_low":       sev_low,
            "secrets_by_type": sorted(
                [{"type": k, "count": v} for k, v in ss_by_type.items()],
                key=lambda x: -x["count"])[:12],
            "secrets_by_repo": sorted(
                [{"repo": k, "count": v} for k, v in ss_by_repo.items()],
                key=lambda x: -x["count"])[:15],
            "cs_by_repo": sorted(
                [{"repo": k, "count": v} for k, v in cs_by_repo.items()],
                key=lambda x: -x["count"])[:15],
            "top_repos": gh_vuln.get("top_repos",    [])[:12],
            "top_pkgs":  gh_vuln.get("top_packages", [])[:15],
        },
        "correlation": {
            "zone_a_cves":   zone_s.get("cves_in_both",        0),
            "zone_a_pkgs":   zone_s.get("pkgs_in_both",        0),
            "zone_b":        zone_s.get("cves_inspector_only",  0),
            "zone_c":        zone_s.get("cves_github_only",     0),
            "convergence":   corr.get("offender_convergence",   []),
            "repo_ranking":  corr.get("repo_combined_ranking",  [])[:20],
            "pkg_quickwin":  qw_chart,
        },
    }


# ── Snapshot persistence ───────────────────────────────────────────────────────

def save_snapshot(slug: str, data: dict, reports_dir: Path) -> Path:
    from datetime import datetime, timezone
    date_dir = reports_dir / slug
    date_dir.mkdir(parents=True, exist_ok=True)
    path = date_dir / "snapshot.json"
    # Past dated folders are immutable history: only today's snapshot is
    # (re)written. Rebuilding the dashboard against an older correlation
    # reuses that day's existing snapshot untouched.
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    if path.exists() and slug != today:
        print(f"   snapshot.json exists for {slug} — preserved (past dates are immutable)", flush=True)
        return path
    path.write_text(json.dumps(data, default=str))
    return path

def load_all_snapshots(reports_dir: Path) -> dict:
    """Return {date_slug: extracted_data} for every <date>/snapshot.json present."""
    result = {}
    for f in sorted(reports_dir.glob("*/snapshot.json"),
                    key=lambda p: p.parent.name):
        # Only dated folders: the folder name becomes a key the page puts in
        # HTML attributes and JS strings.
        if re.fullmatch(r"\d{8}", f.parent.name):
            result[f.parent.name] = json.loads(f.read_text())
    return result

def build_trend_series(all_snaps: dict) -> list:
    """Return date-sorted slim metric objects for the Trend tab."""
    series = []
    for date in sorted(all_snaps.keys()):
        s    = all_snaps[date]
        insp = s.get("inspector",   {})
        gh   = s.get("github",      {})
        corr = s.get("correlation", {})
        gh_vuln_total = gh.get("vuln_total",    0)
        gh_code_total = gh.get("code_total",    0)
        gh_secrets    = gh.get("secrets_total", 0)
        gh_total      = gh.get("security_total")
        if gh_total is None:
            gh_total = gh_vuln_total + gh_code_total + gh_secrets

        # Prefer stored severity buckets from the snapshot; fall back to computing
        # them for legacy snapshots that pre-date the schema addition.
        sev_crit = gh.get("sev_critical")
        sev_high = gh.get("sev_high")
        sev_med  = gh.get("sev_medium")
        sev_low  = gh.get("sev_low")
        if sev_crit is None or sev_high is None or sev_med is None or sev_low is None:
            vuln_crit = gh.get("vuln_critical", 0)
            vuln_high = gh.get("vuln_high",     0)
            vuln_mod  = gh.get("vuln_mod",      0)
            cs_err    = gh.get("code_errors",   0)
            cs_warn   = max(gh_code_total - cs_err, 0)
            sev_crit  = vuln_crit + gh_secrets
            sev_high  = vuln_high + cs_err
            sev_med   = vuln_mod  + cs_warn
            sev_low   = max(gh_vuln_total - vuln_crit - vuln_high - vuln_mod, 0)

        series.append({
            "date":            date,
            "insp_crit":       insp.get("critical",    0),
            "insp_high":       insp.get("high",        0),
            "unique_cves":     insp.get("unique_cves", 0),
            "gh_vuln":         gh_vuln_total,
            "gh_code":         gh_code_total,
            "gh_secrets":      gh_secrets,
            "gh_total":        gh_total,
            "gh_sev_critical": sev_crit,
            "gh_sev_high":     sev_high,
            "gh_sev_medium":   sev_med,
            "gh_sev_low":      sev_low,
            "zone_a_cves":     corr.get("zone_a_cves", 0),
            "zone_a_pkgs":     corr.get("zone_a_pkgs", 0),
        })
    return series


# ── HTML template ──────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f172a;--surface:#1e293b;--surface2:#253047;--border:#334155;
  --text:#e2e8f0;--muted:#94a3b8;--primary:#146bfa;
  --crit:#ef4444;--high:#f97316;--med:#eab308;--low:#22c55e;
  --trivial:#22c55e;--bounded:#3b82f6;--structural:#a855f7;--phantom:#64748b;
}
body{font-family:'Roboto',sans-serif;background:var(--bg);color:var(--text);font-size:13px;line-height:1.5}
.page{max-width:1440px;margin:0 auto;padding:24px 20px}
/* Header */
.header{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:10px}
.header h1{font-size:22px;font-weight:700;color:var(--primary)}
.header p{color:var(--muted);font-size:12px;margin-top:2px}
.badge-conf{background:#dc262633;color:#fca5a5;border:1px solid #dc262666;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:500;white-space:nowrap}
/* Date picker */
.date-row{display:flex;align-items:center;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.date-label{font-size:11px;color:var(--muted);font-weight:500;text-transform:uppercase;letter-spacing:.06em}
.date-chip{padding:4px 11px;border-radius:4px;cursor:pointer;font-size:11px;font-weight:500;border:1px solid var(--border);background:var(--surface2);color:var(--muted);transition:all .15s;font-family:inherit}
.date-chip:hover{border-color:var(--primary);color:var(--text)}
.date-chip.active{background:var(--primary);border-color:var(--primary);color:#fff}
/* Tabs */
.tab-nav{display:flex;gap:0;border-bottom:1px solid var(--border);margin-bottom:20px}
.tab-btn{padding:10px 22px;cursor:pointer;color:var(--muted);border:none;background:transparent;font-family:inherit;font-size:13px;font-weight:500;border-bottom:2px solid transparent;transition:color .15s,border-color .15s}
.tab-btn:hover{color:var(--text)}
.tab-btn.active{color:var(--primary);border-bottom-color:var(--primary)}
.tab-pane{display:none}.tab-pane.active{display:block}
/* Cards & grids */
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px}
.card-title{font-size:14px;font-weight:600;color:var(--primary);margin-bottom:12px}
.grid-5{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:20px}
.grid-6{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:20px}
.grid-2{display:grid;gap:16px;margin-bottom:20px}
.grid-2-6{grid-template-columns:2fr 1fr}
.grid-2-eq{grid-template-columns:1fr 1fr}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:20px}
@media(max-width:1300px){.grid-6{grid-template-columns:repeat(3,1fr)}}
@media(max-width:1100px){.grid-5{grid-template-columns:repeat(3,1fr)}.grid-2-6,.grid-2-eq{grid-template-columns:1fr}.grid-3{grid-template-columns:1fr 1fr}}
@media(max-width:640px){.grid-5,.grid-6,.grid-3{grid-template-columns:1fr}}
/* KPIs */
.kpi-label{font-size:11px;font-weight:500;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:5px}
.kpi-val{font-size:26px;font-weight:700;line-height:1.1}
.kpi-sub{font-size:11px;color:var(--muted);margin-top:4px}
.kpi-val.c{color:var(--crit)}.kpi-val.h{color:var(--high)}.kpi-val.b{color:var(--primary)}.kpi-val.g{color:var(--low)}.kpi-val.p0{color:#fca5a5}
/* Banners */
.banner-p0{background:#ef444420;border:1px solid #ef444466;border-radius:8px;padding:14px 18px;margin-bottom:20px;display:flex;align-items:center;gap:12px}
.banner-p0 .icon{font-size:20px}
.banner-p0 .title{color:#fca5a5;font-weight:700;font-size:14px}
.banner-p0 .sub{color:var(--muted);font-size:12px;margin-top:2px}
/* Badges */
.signal-badge{display:inline-block;padding:2px 7px;border-radius:3px;font-size:10px;font-weight:600;margin:1px}
.s-insp{background:#146bfa22;color:var(--primary);border:1px solid #146bfa44}
.s-dep{background:#22c55e22;color:var(--low);border:1px solid #22c55e44}
.s-cs{background:#eab30822;color:var(--med);border:1px solid #eab30844}
.s-sec{background:#ef444422;color:var(--crit);border:1px solid #ef444444}
/* Table */
table{width:100%;border-collapse:collapse;font-size:12px}
thead th{text-align:left;padding:7px 10px;color:var(--muted);font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border)}
tbody tr{border-bottom:1px solid #1e293b}
tbody tr:hover{background:var(--surface2)}
tbody td{padding:8px 10px;vertical-align:middle}
/* Zone cards */
.zone-card{text-align:center;padding:16px}
.zone-val{font-size:32px;font-weight:700;margin:6px 0}
.zone-lbl{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.zone-desc{font-size:11px;color:var(--muted);margin-top:6px;line-height:1.5}
/* Exec summary */
.exec-col{display:grid;grid-template-columns:1fr 1fr;gap:24px}
@media(max-width:900px){.exec-col{grid-template-columns:1fr}}
.exec-section-title{font-size:16px;font-weight:700;color:var(--primary);margin-bottom:16px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.exec-item{display:flex;gap:14px;margin-bottom:16px;padding-bottom:16px;border-bottom:1px solid var(--border)}
.exec-item:last-child{border-bottom:none;margin-bottom:0;padding-bottom:0}
.exec-num{flex-shrink:0;width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700}
.exec-num-f{background:#ef444422;color:var(--crit);border:1px solid #ef444444}
.exec-num-p{background:#146bfa22;color:var(--primary);border:1px solid #146bfa44}
.exec-title{font-size:13px;font-weight:600;color:var(--text);margin-bottom:3px}
.exec-body{font-size:12px;color:var(--muted);line-height:1.6}
.exec-tag{display:inline-block;font-size:10px;font-weight:600;padding:1px 6px;border-radius:3px;margin-top:5px}
.tag-p0{background:#ef444422;color:#fca5a5;border:1px solid #ef444444}
.tag-insp{background:#146bfa22;color:var(--primary);border:1px solid #146bfa44}
.tag-gh{background:#22c55e22;color:var(--low);border:1px solid #22c55e44}
.tag-both{background:#a855f722;color:var(--structural);border:1px solid #a855f744}
a.repo-link{color:var(--text);text-decoration:none;border-bottom:1px dashed var(--border)}
a.repo-link:hover{color:var(--primary);border-bottom-color:var(--primary)}
/* Date picker trigger */
.snap-trigger{display:flex;align-items:center;gap:7px;padding:6px 14px;background:var(--surface);border:1px solid var(--border);border-radius:6px;cursor:pointer;font-family:inherit;font-size:12px;color:var(--text);transition:border-color .15s}
.snap-trigger:hover{border-color:var(--primary)}
.snap-trigger .snap-label{color:var(--muted);font-size:11px}
.snap-trigger .snap-date{font-weight:600;color:var(--primary)}
.snap-trigger .snap-caret{color:var(--muted);font-size:10px}
/* Modal */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:1000;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:10px;width:380px;max-width:90vw;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.modal-header{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border)}
.modal-title{font-size:14px;font-weight:600;color:var(--primary)}
.modal-close{background:none;border:none;color:var(--muted);cursor:pointer;font-size:18px;line-height:1;padding:0 4px}
.modal-close:hover{color:var(--text)}
.modal-body{padding:16px 20px}
.modal-footer{display:flex;gap:10px;justify-content:flex-end;padding:14px 20px;border-top:1px solid var(--border)}
/* Date list */
.date-list{display:flex;flex-direction:column;gap:6px;max-height:280px;overflow-y:auto}
.date-list-item{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-radius:6px;border:1px solid var(--border);cursor:pointer;transition:border-color .15s,background .15s}
.date-list-item:hover{background:var(--surface2);border-color:var(--primary)}
.date-list-item.selected{background:#146bfa18;border-color:var(--primary)}
.date-list-date{font-size:13px;font-weight:500;color:var(--text)}
.date-list-tags{display:flex;gap:5px}
.dtag{font-size:10px;font-weight:600;padding:1px 6px;border-radius:3px}
.dtag-latest{background:#22c55e22;color:var(--low);border:1px solid #22c55e44}
.dtag-current{background:#146bfa22;color:var(--primary);border:1px solid #146bfa44}
/* Single snapshot notice */
.snap-notice{padding:14px;background:var(--surface2);border-radius:6px;border:1px solid var(--border);color:var(--muted);font-size:12px;line-height:1.6;text-align:center}
.snap-notice b{color:var(--text)}
/* What Changed strip */
.wc-row{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
.wc-card{background:var(--surface);border-radius:6px;padding:12px 14px;border-left:3px solid var(--border)}
.wc-card.win{border-left-color:#22c55e;background:linear-gradient(135deg,#22c55e15,var(--surface) 55%)}
.wc-card.lose{border-left-color:#ef4444;background:linear-gradient(135deg,#ef444415,var(--surface) 55%)}
.wc-card.flat{border-left-color:#475569}
.wc-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px;font-weight:500}
.wc-main{display:flex;align-items:baseline;gap:6px;line-height:1.1}
.wc-arrow{font-size:20px;font-weight:700}
.wc-value{font-size:20px;font-weight:700}
.wc-win{color:#22c55e}.wc-lose{color:#ef4444}.wc-flat{color:#94a3b8}
.wc-sub{font-size:11px;color:var(--muted);margin-top:4px}
.wc-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.wc-title{font-size:12px;font-weight:600;color:var(--primary);text-transform:uppercase;letter-spacing:.06em}
.wc-since{font-size:11px;color:var(--muted)}
@media(max-width:1100px){.wc-row{grid-template-columns:repeat(3,1fr)}}
@media(max-width:640px){.wc-row{grid-template-columns:1fr}}
/* Buttons */
.btn{padding:7px 18px;border-radius:5px;font-family:inherit;font-size:12px;font-weight:500;cursor:pointer;border:1px solid var(--border);transition:all .15s}
.btn-primary{background:var(--primary);border-color:var(--primary);color:#fff}
.btn-primary:hover{background:#0d4fb8}
.btn-primary:disabled{opacity:.4;cursor:not-allowed}
.btn-ghost{background:transparent;color:var(--muted)}
.btn-ghost:hover{color:var(--text);border-color:var(--muted)}
</style>
</head>
<body>
<div class="page">

<div class="header">
  <div>
    <h1>__TITLE__</h1>
    <p>Account __ORG_ACCOUNT__ · Inspector V2 + GitHub</p>
  </div>
  <span class="badge-conf">CONFIDENTIAL — INTERNAL</span>
</div>

<div class="date-row">
  <button class="snap-trigger" onclick="openDateModal()">
    <span class="snap-label">Snapshot</span>
    <span class="snap-date" id="snapDisplay"></span>
    <span class="snap-caret">▾</span>
  </button>
</div>

<!-- Snapshot modal -->
<div class="modal-overlay" id="dateModal" onclick="handleOverlayClick(event)">
  <div class="modal" role="dialog" aria-modal="true">
    <div class="modal-header">
      <span class="modal-title">Select Snapshot</span>
      <button class="modal-close" onclick="closeDateModal()" aria-label="Close">✕</button>
    </div>
    <div class="modal-body" id="dateModalBody"></div>
    <div class="modal-footer" id="dateModalFooter"></div>
  </div>
</div>

<div class="tab-nav">
  <button class="tab-btn active" data-tab="breakdown" onclick="switchTab(this,'breakdown')">Breakdown</button>
  <button class="tab-btn"         data-tab="trend"     onclick="switchTab(this,'trend')">Trend</button>
  <button class="tab-btn"         data-tab="exec"      onclick="switchTab(this,'exec')">Executive Summary</button>
</div>

<!-- Executive Summary tab -->
<div id="tab-exec" class="tab-pane">
  <div id="execBanner"></div>
  <div class="exec-col">
    <div><div class="exec-section-title">Key Findings</div><div id="execFindings"></div></div>
    <div><div class="exec-section-title">Priority Actions</div><div id="execPriorities"></div></div>
  </div>
</div>

<!-- Breakdown tab -->
<div id="tab-breakdown" class="tab-pane active">
  <div id="secretsBanner"></div>
  <div id="whatChangedRow"></div>
  <div class="grid-6" id="kpiRow"></div>
  <div class="grid-3" style="margin-bottom:20px" id="zoneRow"></div>

  <div class="card" style="margin-bottom:20px">
    <div class="card-title">Top Offenders — Repos Flagged by Multiple Signals</div>
    <p style="color:var(--muted);font-size:11px;margin-bottom:12px">
      Repos in the top 15 of 2+ independent signal categories. Highest-confidence fix targets.
    </p>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>Repository</th><th>Signals</th><th>Insp C+H</th><th>GH C+H</th><th>Code Scan</th><th>Secrets</th><th>Score</th></tr></thead>
      <tbody id="convergenceTbody"></tbody>
    </table></div>
  </div>

  <div class="grid-2 grid-2-6" style="margin-bottom:20px">
    <div class="card">
      <div class="card-title">Combined Repo Rankings — All Four Signals</div>
      <p style="color:var(--muted);font-size:11px;margin-bottom:10px">Inspector (image) + GitHub Dependabot (source) + Code Scanning + Secrets. GitHub and secrets weighted higher — no fan-out inflation.</p>
      <div style="height:360px"><canvas id="repoRankChart"></canvas></div>
    </div>
    <div style="display:flex;flex-direction:column;gap:16px">
      <div class="card">
        <div class="card-title">Secret Scanning — Open Alerts</div>
        <p style="color:#fca5a5;font-size:11px;margin-bottom:10px">Credential-level exposures. Triage and rotate — not a backlog item.</p>
        <div style="height:180px"><canvas id="secretTypeChart"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">Code Scanning (SAST)</div>
        <div style="height:140px"><canvas id="csRepoChart"></canvas></div>
      </div>
    </div>
  </div>

  <div class="card" style="margin-bottom:20px">
    <div class="card-title">Package Quick-Win Matrix — Both Sources</div>
    <p style="color:var(--muted);font-size:11px;margin-bottom:8px">
      Zone A packages (Inspector <em>and</em> GitHub). Bubble size ∝ quick-win score.
      <b style="color:var(--trivial)">Top-left = fix now.</b> Hover for details.
    </p>
    <div style="height:360px"><canvas id="qwChart"></canvas></div>
    <div style="display:flex;gap:16px;margin-top:8px;flex-wrap:wrap;font-size:11px">
      <span><span style="color:var(--trivial)">●</span> Trivial (≤5 repos)</span>
      <span><span style="color:var(--bounded)">●</span> Bounded (6+ repos)</span>
      <span><span style="color:var(--phantom)">●</span> Phantom (no fix)</span>
      <span><span style="color:var(--structural)">●</span> Structural (migration)</span>
    </div>
  </div>

  <div class="grid-2 grid-2-eq" style="margin-bottom:20px">
    <div class="card"><div class="card-title">Inspector V2 — Top Repos</div><div style="height:300px"><canvas id="inspRepoChart"></canvas></div></div>
    <div class="card"><div class="card-title">GitHub Dependabot — Top Repos</div><div style="height:300px"><canvas id="ghRepoChart"></canvas></div></div>
  </div>
  <div class="grid-2 grid-2-eq" style="margin-bottom:20px">
    <div class="card"><div class="card-title">Inspector V2 — Top Packages</div><div style="height:300px"><canvas id="inspPkgChart"></canvas></div></div>
    <div class="card"><div class="card-title">GitHub Dependabot — Top Packages</div><div style="height:300px"><canvas id="ghPkgChart"></canvas></div></div>
  </div>
</div><!-- /tab-breakdown -->

<!-- Trend tab -->
<div id="tab-trend" class="tab-pane">
  <p id="trendMeta" style="color:var(--muted);font-size:11px;margin-bottom:16px"></p>
  <div class="grid-6" id="trendKpiRow" style="margin-bottom:20px"></div>
  <div class="card" style="margin-bottom:20px">
    <div class="card-title">Inspector V2 — Findings Trend</div>
    <p style="color:var(--muted);font-size:11px;margin-bottom:10px">Stacked bars: Critical + High raw findings (left axis). Blue line: unique CVEs (right axis) — cuts through fan-out noise to show distinct vulnerability classes being resolved.</p>
    <div style="height:340px"><canvas id="trendInspChart"></canvas></div>
  </div>
  <div class="card" style="margin-bottom:20px">
    <div class="card-title">GitHub Security Alerts — by Source</div>
    <p style="color:var(--muted);font-size:11px;margin-bottom:10px">Total open alerts (matches GitHub Security Overview) and the three source breakdowns: Dependabot vulnerabilities, Code Scanning (SAST), and Secret Scanning. Log Y axis — all four lines stay visible despite the scale gap (Dep ~3K vs Secrets ~150).</p>
    <div style="height:300px"><canvas id="trendGhChart"></canvas></div>
  </div>
  <div class="card">
    <div class="card-title">GitHub Security Alerts — by Severity</div>
    <p style="color:var(--muted);font-size:11px;margin-bottom:10px">Mirrors GitHub Security Overview's "Open alerts over time". Severity buckets computed across all three sources: Dependabot + Code Scanning (errors→High, warnings→Medium) + Secrets (counted as Critical). Small discrepancies vs GitHub's UI come from CS rule-level severity mapping which we approximate.</p>
    <div style="height:300px"><canvas id="trendGhSevChart"></canvas></div>
  </div>
</div><!-- /tab-trend -->

</div><!-- /page -->
<script>
const SNAPSHOTS    = __SNAPSHOTS__;
const DATES        = __DATES__;
const CURRENT_DATE = __CURRENT_DATE__;
const ORG          = '__ORG__';
const TREND_SERIES = __TREND_SERIES__;
const ANNOTATIONS  = __ANNOTATIONS__;
let D              = SNAPSHOTS[CURRENT_DATE];
const CHARTS       = {};

// ── Utilities ─────────────────────────────────────────────────────────────────
const fmt  = n => n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(0)+'K':String(n);
const fmtN = n => Number(n).toLocaleString();
// Repo, package and secret-type names come from scanner data. They reach innerHTML
// below, so every one passes through esc() first.
const ESC  = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
const esc  = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ESC[c]);
const DARK = {backgroundColor:'#1e293b',borderColor:'#334155',borderWidth:1,
              titleColor:'#e2e8f0',bodyColor:'#94a3b8',padding:10,displayColors:false};

// Parse YYYYMMDD slug into a Date.
function slugToDate(s){return new Date(s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8)+'T00:00:00Z')}

// Find the snapshot in TREND_SERIES closest to `targetDays` days before `currentSlug`,
// preferring snapshots ≥ targetDays old. Returns {base, ageDays} or null.
function pickBaseline(currentSlug, targetDays) {
  if (!TREND_SERIES || TREND_SERIES.length < 2) return null;
  const curDt = slugToDate(currentSlug);
  const target = new Date(curDt.getTime() - targetDays * 86400e3);
  let preferred = null, fallback = null;
  let preferredDiff = Infinity, fallbackAge = -Infinity;
  for (const s of TREND_SERIES) {
    if (s.date === currentSlug) continue;
    const dt = slugToDate(s.date);
    if (dt > curDt) continue;
    if (dt <= target) {
      const diff = Math.abs(dt - target);
      if (diff < preferredDiff) { preferredDiff = diff; preferred = s; }
    } else {
      const age = (curDt - dt) / 86400e3;
      if (age > fallbackAge) { fallbackAge = age; fallback = s; }
    }
  }
  const base = preferred || fallback;
  if (!base) return null;
  const ageDays = Math.round((curDt - slugToDate(base.date)) / 86400e3);
  return { base, ageDays };
}

// Format a delta block. While we have <30 days of history, the baseline is the
// earliest snapshot available — make that explicit so the number isn't read as a
// monthly trend.
function deltaSub(curVal, baseVal, ageDays, targetDays = 30) {
  const d = curVal - baseVal;
  const pct = baseVal > 0 ? (Math.abs(d) / baseVal * 100).toFixed(1) : '0.0';
  const dir = d > 0 ? '↑' : d < 0 ? '↓' : '→';
  const col = d > 0 ? 'var(--crit)' : d < 0 ? 'var(--low)' : 'var(--muted)';
  const txt = d === 0 ? 'no change' : `${dir} ${fmtN(Math.abs(d))} (${pct}%)`;
  const suffix = ageDays < targetDays
    ? ` vs ${ageDays}d ago — building ${targetDays}d baseline`
    : ` vs ${ageDays}d ago`;
  return `<span style="color:${col}">${txt}</span>${suffix}`;
}

function mkChart(id, config) {
  CHARTS[id]?.destroy();
  CHARTS[id] = new Chart(document.getElementById(id), config);
}

function hBar(id, labels, datasets) {
  mkChart(id, {
    type:'bar', data:{labels, datasets},
    options:{
      responsive:true, maintainAspectRatio:false, indexAxis:'x',
      scales:{
        x:{stacked:true,grid:{display:false},ticks:{color:'#e2e8f0',font:{size:9},maxRotation:38,minRotation:38}},
        y:{stacked:true,grid:{color:'#334155'},ticks:{color:'#94a3b8',font:{size:9},callback:v=>v>=1000?(v/1000)+'K':v}},
      },
      plugins:{
        legend:{labels:{color:'#94a3b8',font:{size:10},boxWidth:10,padding:8}},
        tooltip:{...DARK,callbacks:{label:i=>` ${i.dataset.label}: ${fmtN(i.raw)}`}},
      }
    }
  });
}

// ── Tab switching ─────────────────────────────────────────────────────────────
// Chart.js measures the canvas container at creation time. Creating charts inside
// a display:none tab gives them a 0×0 canvas, and .resize() can't always recover.
// We defer chart rendering until the breakdown/trend tabs are actually visible.
let breakdownRendered = false;
let trendRendered     = false;
let currentTab        = 'breakdown';  // matches the default `.tab-pane.active` in HTML

function switchTab(btn, id, skipUrl) {
  document.querySelectorAll('.tab-pane').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+id).classList.add('active');
  btn.classList.add('active');
  currentTab = id;

  if (id === 'breakdown' && !breakdownRendered) {
    renderDetail();
    breakdownRendered = true;
  } else if (id === 'breakdown') {
    // Already rendered. requestAnimationFrame waits a frame for CSS to apply,
    // then forces a measure pass — handles browser-side container size changes.
    requestAnimationFrame(() => Object.values(CHARTS).forEach(c => c?.resize()));
  } else if (id === 'trend' && !trendRendered) {
    renderTrend();
    trendRendered = true;
  } else if (id === 'trend') {
    requestAnimationFrame(() => Object.values(CHARTS).forEach(c => c?.resize()));
  }

  if (!skipUrl) urlWrite();
}

// ── URL routing — shareable per-tab + per-snapshot links ──────────────────────
// Hash format: #<tab>/<snapshot>   e.g.  #breakdown/20260525
// On Apps Script, the dashboard runs inside Google's sandbox iframe — direct
// location.hash changes only affect the iframe URL, not the parent address bar.
// google.script.history.push / google.script.url.getLocation bridge to the
// parent URL. On local file:// we fall back to native location.hash.
const TAB_IDS = ['breakdown','trend','exec'];
const GAS = typeof google !== 'undefined' && google.script && google.script.url;

function switchTabById(id, skipUrl) {
  if (!TAB_IDS.includes(id)) return;
  const btn = document.querySelector('.tab-btn[data-tab="'+id+'"]');
  if (btn) switchTab(btn, id, skipUrl);
}

function parseHash(raw) {
  const clean = (raw || '').replace(/^#/, '');
  if (!clean) return { tab: null, snap: null };
  const [t, s] = clean.split('/');
  return {
    tab:  TAB_IDS.includes(t)        ? t : null,
    snap: (s && SNAPSHOTS[s])        ? s : null,
  };
}

function urlWrite() {
  const h = currentTab + '/' + activeDate;
  if (GAS && google.script.history) {
    google.script.history.push(null, null, h);
  } else if (location.hash !== '#'+h) {
    history.replaceState(null, '', '#'+h);
  }
}

function applyHash(rawHash) {
  const { tab, snap } = parseHash(rawHash);
  if (snap && snap !== activeDate) loadDate(snap, true);
  if (tab) switchTabById(tab, true);
}

window.addEventListener('DOMContentLoaded', () => {
  if (GAS) {
    google.script.url.getLocation(loc => applyHash((loc && loc.hash) || ''));
  } else {
    applyHash(location.hash || '');
  }
});

if (typeof google !== 'undefined' && google.script && google.script.history) {
  google.script.history.setChangeHandler(e => {
    applyHash((e && e.location && e.location.hash) || '');
  });
} else {
  window.addEventListener('hashchange', () => applyHash(location.hash || ''));
}

// ── Date modal ────────────────────────────────────────────────────────────────
function fmtDate(s){return s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8)}

let activeDate    = CURRENT_DATE;   // currently loaded snapshot
let selectedDate  = CURRENT_DATE;   // selection inside the modal (not yet committed)

function updateSnapDisplay() {
  document.getElementById('snapDisplay').textContent = fmtDate(activeDate);
}
updateSnapDisplay();

function openDateModal() {
  selectedDate = activeDate;        // pre-select the current snapshot
  const body   = document.getElementById('dateModalBody');
  const footer = document.getElementById('dateModalFooter');

  if (DATES.length === 1) {
    body.innerHTML = `
      <div class="snap-notice">
        Only one snapshot is available.<br>
        <b>${fmtDate(DATES[0])}</b> — currently loaded.
      </div>`;
    footer.innerHTML = `
      <button class="btn btn-ghost" onclick="closeDateModal()">Close</button>`;
  } else {
    body.innerHTML = `<div class="date-list" id="dateList">` +
      DATES.map((d, i) => {
        const tags = [
          i === 0            ? `<span class="dtag dtag-latest">Latest</span>` : '',
          d === activeDate   ? `<span class="dtag dtag-current">Current</span>` : '',
        ].join('');
        return `<div class="date-list-item${d===selectedDate?' selected':''}"
                     data-date="${d}" onclick="selectModalDate('${d}')">
                  <span class="date-list-date">${fmtDate(d)}</span>
                  <span class="date-list-tags">${tags}</span>
                </div>`;
      }).join('') + `</div>`;

    footer.innerHTML = `
      <button class="btn btn-ghost" onclick="closeDateModal()">Cancel</button>
      <button class="btn btn-primary" id="loadSnapBtn"
              onclick="confirmLoadDate()"
              ${selectedDate === activeDate ? 'disabled' : ''}>
        Load Snapshot
      </button>`;
  }

  document.getElementById('dateModal').classList.add('open');
  document.addEventListener('keydown', handleModalKeydown);
}

function selectModalDate(date) {
  selectedDate = date;
  document.querySelectorAll('#dateList .date-list-item').forEach(el => {
    el.classList.toggle('selected', el.dataset.date === date);
  });
  const btn = document.getElementById('loadSnapBtn');
  if (btn) btn.disabled = (date === activeDate);
}

function confirmLoadDate() {
  if (!selectedDate || selectedDate === activeDate) return;
  loadDate(selectedDate);
  closeDateModal();
}

function closeDateModal() {
  document.getElementById('dateModal').classList.remove('open');
  document.removeEventListener('keydown', handleModalKeydown);
}

function handleOverlayClick(e) {
  if (e.target === document.getElementById('dateModal')) closeDateModal();
}

function handleModalKeydown(e) {
  if (e.key === 'Escape') closeDateModal();
}

function loadDate(date, skipUrl) {
  D          = SNAPSHOTS[date];
  activeDate = date;
  updateSnapDisplay();
  renderAll();
  if (!skipUrl) urlWrite();
}

// ── Main render — always-visible content only (banners, KPIs, exec summary) ──
// Detail-tab content (zones, convergence table, all charts) is deferred to
// renderDetail() to avoid the hidden-canvas issue.
function renderAll() {
  const insp = D.inspector, gh = D.github, corr = D.correlation;
  const rawTotal = insp.critical + insp.high + insp.medium;

  // -- Banners
  document.getElementById('secretsBanner').innerHTML = gh.secrets_total > 0
    ? `<div class="banner-p0"><div class="icon">⚠</div><div>
         <div class="title">P0 — ${gh.secrets_total} open secret scanning alerts</div>
         <div class="sub">Exposed credentials committed to source code. Triage and rotate before all other work.</div>
       </div></div>`
    : '';

  // -- What Changed strip
  renderWhatChanged();

  // -- KPIs
  const ghTotal = (typeof gh.security_total === 'number')
    ? gh.security_total
    : (gh.vuln_total + gh.code_total + gh.secrets_total);
  const baseline = pickBaseline(activeDate, 30);
  const ghTotalSub = baseline
    ? `Matches GitHub Security Overview · ${deltaSub(ghTotal, baseline.base.gh_total, baseline.ageDays)}`
    : 'Matches GitHub Security Overview · no baseline yet';

  document.getElementById('kpiRow').innerHTML = [
    ['Inspector Raw',     fmt(rawTotal),          'c',  `${fmtN(insp.unique_cves)} unique CVEs · ~${insp.fanout}× fan-out`],
    ['GH Security Total', fmtN(ghTotal),          'b',  ghTotalSub],
    ['Dependabot Alerts', fmtN(gh.vuln_total),    'h',  `${fmtN(gh.vuln_critical)} CRIT · ${fmtN(gh.vuln_high)} HIGH`],
    ['Code Scanning',     fmtN(gh.code_total),    'b',  `${fmtN(gh.code_errors)} errors · ${gh.code_total-gh.code_errors} warnings`],
    ['Secret Scanning',   fmtN(gh.secrets_total), 'p0', 'Credential exposures — P0'],
    ['Zone A Overlap',    fmtN(corr.zone_a_pkgs), 'g',  `${fmtN(corr.zone_a_cves)} CVEs confirmed in both sources`],
  ].map(([l,v,c,s])=>
    `<div class="card"><div class="kpi-label">${l}</div>
     <div class="kpi-val ${c}">${v}</div>
     <div class="kpi-sub">${s}</div></div>`
  ).join('');

  // -- Executive summary (visible by default — render now)
  renderExec(insp, gh, corr, rawTotal);

  // -- Breakdown tab content: render only when visible (or eagerly on initial
  //    load since Breakdown is now the default tab).
  if (breakdownRendered) {
    // Breakdown was previously opened; refresh its content for the new D.
    renderDetail();
  } else if (document.getElementById('tab-breakdown').classList.contains('active')) {
    renderDetail();
    breakdownRendered = true;
  }
}

// ── What Changed strip — snapshot-to-snapshot deltas ─────────────────────────
// Compares the currently loaded snapshot to the immediately preceding one
// (DATES is sorted desc — DATES[idx+1] is the older one). Hides cleanly when
// no previous snapshot exists. Five pinned metrics: GH Security Total,
// Critical (GH cross-source), Inspector C+H, Dependabot Alerts, Secret Scanning.
function renderWhatChanged() {
  const container = document.getElementById('whatChangedRow');
  const idx       = DATES.indexOf(activeDate);
  const prevDate  = (idx >= 0 && idx + 1 < DATES.length) ? DATES[idx + 1] : null;
  if (!prevDate || !SNAPSHOTS[prevDate]) { container.innerHTML = ''; return; }

  const prev    = SNAPSHOTS[prevDate];
  const ageDays = Math.round((slugToDate(activeDate) - slugToDate(prevDate)) / 86400e3);

  // Resolve fields with fallbacks for legacy snapshots that pre-date the schema additions.
  const ghTotal = s => (typeof s.github.security_total === 'number')
    ? s.github.security_total
    : (s.github.vuln_total + s.github.code_total + s.github.secrets_total);
  const ghCrit  = s => (typeof s.github.sev_critical === 'number')
    ? s.github.sev_critical
    : (s.github.vuln_critical + s.github.secrets_total);

  const metrics = [
    {label: 'GH Security Total', cur: ghTotal(D),                  prv: ghTotal(prev)},
    {label: 'Critical (GH)',     cur: ghCrit(D),                   prv: ghCrit(prev)},
    {label: 'Inspector C+H',     cur: D.inspector.critical + D.inspector.high,
                                  prv: prev.inspector.critical + prev.inspector.high},
    {label: 'Dependabot Alerts', cur: D.github.vuln_total,          prv: prev.github.vuln_total},
    {label: 'Secret Scanning',   cur: D.github.secrets_total,       prv: prev.github.secrets_total},
  ];

  const cards = metrics.map(m => {
    const d   = m.cur - m.prv;
    const pct = m.prv > 0 ? (Math.abs(d) / m.prv * 100).toFixed(1) : '0.0';
    let cls, arrow, txt, prefix;
    if (d < 0)      { cls = 'win';  arrow = '↓'; txt = 'wc-win';  prefix = '-'; }
    else if (d > 0) { cls = 'lose'; arrow = '↑'; txt = 'wc-lose'; prefix = '+'; }
    else            { cls = 'flat'; arrow = '•'; txt = 'wc-flat'; prefix = '';  }
    const hero = d === 0 ? 'no change' : (prefix + fmtN(Math.abs(d)));
    const sub  = d === 0 ? ('held at ' + fmtN(m.cur)) : (prefix + pct + '% · now ' + fmtN(m.cur));
    return `<div class="wc-card ${cls}">
              <div class="wc-label">${m.label}</div>
              <div class="wc-main">
                <span class="wc-arrow ${txt}">${arrow}</span>
                <span class="wc-value ${txt}">${hero}</span>
              </div>
              <div class="wc-sub">${sub}</div>
            </div>`;
  }).join('');

  container.innerHTML =
    '<div class="card" style="margin-bottom:20px">' +
      '<div class="wc-header">' +
        '<span class="wc-title">What Changed</span>' +
        '<span class="wc-since">since ' + fmtDate(prevDate) + ' · ' + ageDays + 'd ago</span>' +
      '</div>' +
      '<div class="wc-row">' + cards + '</div>' +
    '</div>';
}

// ── Detail tab — zones, convergence table, all charts ─────────────────────────
// Called when the detail tab first becomes visible (or on date change if it was
// already initialised). All canvas-using charts MUST be created here, never in
// renderAll(), to avoid the 0×0-canvas-in-hidden-tab issue.
function renderDetail() {
  const insp = D.inspector, gh = D.github, corr = D.correlation;

  // -- Zones
  document.getElementById('zoneRow').innerHTML = [
    ['Zone A',corr.zone_a_cves,'#22c55e','CVEs in BOTH sources',     'Confirmed end-to-end. One fix closes findings in both scanners.'],
    ['Zone B',corr.zone_b,     '#146bfa','Inspector only',            'In image, not source. Base image upgrade closes most.'],
    ['Zone C',corr.zone_c,     '#f97316','GitHub only',               'In source, not Inspector. Image may be newer, or repo has no ECR scan.'],
  ].map(([l,v,c,s,d])=>
    `<div class="card zone-card">
       <div class="zone-lbl">${l}</div>
       <div class="zone-val" style="color:${c}">${fmtN(v)}</div>
       <div style="font-size:12px;font-weight:600;color:var(--text)">${s}</div>
       <div class="zone-desc">${d}</div>
     </div>`
  ).join('');

  // -- Convergence table
  const SB = {
    Inspector: '<span class="signal-badge s-insp">Inspector</span>',
    Dependabot:'<span class="signal-badge s-dep">Dependabot</span>',
    CodeScan:  '<span class="signal-badge s-cs">CodeScan</span>',
    Secrets:   '<span class="signal-badge s-sec">Secrets</span>',
  };
  document.getElementById('convergenceTbody').innerHTML = (corr.convergence||[]).map(r=>{
    const badges = (r.signals||[]).map(s=>SB[s]||esc(s)).join('');
    // GAS parser bug: a template literal containing }/${ (close-interp, slash, open-interp)
    // is misread as the start of a regex, mangling the rest of the script and producing
    // "Unexpected token '<'" in the served page. Use string concatenation for any URL or
    // path built from multiple variables. Plain template literals without ${...}/${...}
    // (e.g., outer HTML strings with </td>) are fine.
    const url    = 'https://github.com/' + encodeURIComponent(ORG) + '/' + encodeURIComponent(r.repo) + '/security/dependabot';
    return `<tr>
      <td><a class="repo-link" href="${esc(url)}" target="_blank">${esc(r.repo)}</a></td>
      <td>${badges}</td>
      <td>${fmtN(r.insp_crit+r.insp_high)}</td>
      <td>${fmtN(r.gh_crit+r.gh_high)}</td>
      <td>${fmtN(r.code_scanning)}</td>
      <td>${r.secrets>0?`<b style="color:var(--crit)">${fmtN(r.secrets)}</b>`:'0'}</td>
      <td style="color:var(--muted);font-size:11px">${fmtN(r.combined_score)}</td>
    </tr>`;
  }).join('');

  // -- Repo ranking chart
  const rr = corr.repo_ranking;
  hBar('repoRankChart', rr.map(r=>r.repo), [
    {label:'Inspector C+H',data:rr.map(r=>r.insp_crit+r.insp_high), backgroundColor:'#146bfa88',borderColor:'#146bfa',borderWidth:1,stack:'s'},
    {label:'GH Dependabot', data:rr.map(r=>r.gh_crit+r.gh_high),   backgroundColor:'#22c55e88',borderColor:'#22c55e',borderWidth:1,stack:'s'},
    {label:'Code Scan ×5',  data:rr.map(r=>r.code_scanning*5),      backgroundColor:'#eab30888',borderColor:'#eab308',borderWidth:1,stack:'s'},
    {label:'Secrets ×100',  data:rr.map(r=>r.secrets*100),          backgroundColor:'#ef444488',borderColor:'#ef4444',borderWidth:1,stack:'s'},
  ]);

  // -- Secret types doughnut
  {
    const items = gh.secrets_by_type.slice(0,10);
    mkChart('secretTypeChart', {
      type:'doughnut',
      data:{
        labels: items.map(x=>x.type.replace(/_/g,' ').replace('aws ','AWS ').replace('google ','Google ').replace('github ','GitHub ')),
        datasets:[{
          data: items.map(x=>x.count),
          backgroundColor:['#ef4444cc','#f97316cc','#eab308cc','#22c55ecc','#3b82f6cc','#a855f7cc','#ec4899cc','#14b8a6cc','#6366f1cc','#f43f5ecc'],
          borderWidth:1, hoverOffset:4,
        }]
      },
      options:{responsive:true,maintainAspectRatio:false,cutout:'55%',
        plugins:{legend:{position:'right',labels:{color:'#94a3b8',font:{size:9},boxWidth:8,padding:5}},
                 tooltip:{...DARK,callbacks:{label:i=>` ${i.label}: ${i.raw}`}}}}
    });
  }

  // -- Code scanning bar
  {
    const items = gh.cs_by_repo.slice(0,10);
    hBar('csRepoChart', items.map(x=>x.repo),
      [{label:'Alerts',data:items.map(x=>x.count),backgroundColor:'#eab30888',borderColor:'#eab308',borderWidth:1,borderRadius:3}]
    );
  }

  // -- Package quick-win scatter
  {
    const ELABELS = {1:'Trivial',2:'Bounded',3:'Phantom',4:'Structural'};
    const ECOLOR  = {1:'#22c55e',2:'#3b82f6',3:'#64748b',4:'#a855f7'};
    const grouped = {1:[],2:[],3:[],4:[]};
    (corr.pkg_quickwin||[]).forEach(p=>(grouped[p.effort]||grouped[4]).push(p));
    mkChart('qwChart', {
      type:'bubble',
      data:{datasets:Object.entries(grouped).filter(([,pts])=>pts.length).map(([e,pts])=>({
        label:ELABELS[e],
        data:pts.map(p=>({x:p.x+(Math.random()*.3-.15),y:p.y||10,r:p.r,_p:p})),
        backgroundColor:ECOLOR[e]+'bb',borderColor:ECOLOR[e],borderWidth:1.5,
      }))},
      options:{responsive:true,maintainAspectRatio:false,
        scales:{
          x:{min:.5,max:4.5,title:{display:true,text:'Effort',color:'#94a3b8',font:{size:11}},
             ticks:{color:'#94a3b8',font:{size:10},stepSize:1,callback:v=>({1:'Trivial',2:'Bounded',3:'Phantom',4:'Structural'})[Math.round(v)]||''},
             grid:{color:'#334155'}},
          y:{type:'logarithmic',min:10,max:1500000,
             title:{display:true,text:'Combined C+H (log)',color:'#94a3b8',font:{size:11}},
             ticks:{color:'#94a3b8',font:{size:10},callback:v=>v>=1e6?(v/1e6)+'M':v>=1e3?(v/1e3)+'K':v},
             grid:{color:'#334155'}},
        },
        plugins:{
          legend:{labels:{color:'#94a3b8',font:{size:11},boxWidth:10,padding:12}},
          tooltip:{...DARK,callbacks:{
            title:items=>items[0].raw._p.pkg,
            label:i=>{const p=i.raw._p;return[`Effort: ${p.label}`,`Insp C+H: ${fmtN(p.insp_ch)}  GH C+H: ${fmtN(p.gh_ch)}`,`Repos: ${p.repos}  Fix: ${p.fix?'✓':'✗'}`,`QW Score: ${fmtN(p.score)}`];}
          }}
        }
      }
    });
  }

  // -- Inspector repo/pkg charts
  hBar('inspRepoChart', insp.top_repos.map(r=>r.name), [
    {label:'Critical',data:insp.top_repos.map(r=>r.c),backgroundColor:'#ef444488',borderColor:'#ef4444',borderWidth:1,stack:'s'},
    {label:'High',    data:insp.top_repos.map(r=>r.h),backgroundColor:'#f9731688',borderColor:'#f97316',borderWidth:1,stack:'s'},
    {label:'Medium',  data:insp.top_repos.map(r=>r.m),backgroundColor:'#eab30888',borderColor:'#eab308',borderWidth:1,stack:'s'},
  ]);
  hBar('inspPkgChart', insp.top_pkgs.map(p=>p.name), [
    {label:'Critical',data:insp.top_pkgs.map(p=>p.c),backgroundColor:'#ef444488',borderColor:'#ef4444',borderWidth:1,stack:'s'},
    {label:'High',    data:insp.top_pkgs.map(p=>p.h),backgroundColor:'#f9731688',borderColor:'#f97316',borderWidth:1,stack:'s'},
  ]);

  // -- GitHub repo/pkg charts
  const gr = gh.top_repos.slice(0,12);
  hBar('ghRepoChart', gr.map(r=>r.repo), [
    {label:'Critical', data:gr.map(r=>r.CRITICAL||0), backgroundColor:'#ef444488',borderColor:'#ef4444',borderWidth:1,stack:'s'},
    {label:'High',     data:gr.map(r=>r.HIGH||0),     backgroundColor:'#f9731688',borderColor:'#f97316',borderWidth:1,stack:'s'},
    {label:'Moderate', data:gr.map(r=>r.MODERATE||0), backgroundColor:'#eab30888',borderColor:'#eab308',borderWidth:1,stack:'s'},
  ]);
  const gp = gh.top_pkgs.slice(0,15);
  hBar('ghPkgChart', gp.map(p=>p.package), [
    {label:'Critical', data:gp.map(p=>p.critical), backgroundColor:'#ef444488',borderColor:'#ef4444',borderWidth:1,stack:'s'},
    {label:'High',     data:gp.map(p=>p.high),     backgroundColor:'#f9731688',borderColor:'#f97316',borderWidth:1,stack:'s'},
    {label:'Moderate', data:gp.map(p=>p.moderate), backgroundColor:'#eab30888',borderColor:'#eab308',borderWidth:1,stack:'s'},
  ]);

}

// ── Trend tab ─────────────────────────────────────────────────────────────────
// Reads TREND_SERIES (all snapshots compiled at build time) and ANNOTATIONS
// (static event markers). Independent of the selected snapshot — always shows
// the full history.
function renderTrend() {
  if (!TREND_SERIES || TREND_SERIES.length === 0) {
    document.getElementById('trendKpiRow').innerHTML =
      '<div class="card" style="grid-column:1/-1;text-align:center">' +
      '<div class="kpi-label">No snapshots available</div></div>';
    return;
  }

  const base    = TREND_SERIES[0];
  const current = TREND_SERIES[TREND_SERIES.length - 1];
  const labels  = TREND_SERIES.map(s => fmtDate(s.date));
  const nSnaps  = TREND_SERIES.length;

  document.getElementById('trendMeta').textContent =
    'Baseline: ' + fmtDate(base.date) + '  ·  ' + nSnaps + ' snapshot' + (nSnaps > 1 ? 's' : '') + '  ·  All metrics: lower = better';

  // Stat cards — delta from first snapshot to latest; lower is always better
  document.getElementById('trendKpiRow').innerHTML = [
    ['Inspector Critical', current.insp_crit,   base.insp_crit,   'c'],
    ['Inspector High',     current.insp_high,   base.insp_high,   'h'],
    ['Unique CVEs',        current.unique_cves, base.unique_cves, 'b'],
    ['GH Security Total',  current.gh_total,    base.gh_total,    'b'],
    ['Dependabot',         current.gh_vuln,     base.gh_vuln,     'h'],
    ['Zone A CVEs',        current.zone_a_cves, base.zone_a_cves, 'g'],
  ].map(([lbl, cur, bas, cls]) => {
    const d   = cur - bas;
    const pct = bas > 0 ? (Math.abs(d) / bas * 100).toFixed(1) : '0.0';
    const dir = d > 0 ? '↑' : d < 0 ? '↓' : '→';
    const dc  = d > 0 ? 'var(--crit)' : d < 0 ? 'var(--low)' : 'var(--muted)';
    return `<div class="card">
      <div class="kpi-label">${lbl}</div>
      <div class="kpi-val ${cls}">${fmtN(cur)}</div>
      <div class="kpi-sub" style="color:${dc}">${dir} ${fmtN(Math.abs(d))} (${pct}%) from baseline</div>
    </div>`;
  }).join('');

  // Annotation vertical lines — shared across both charts
  const annots = {};
  (ANNOTATIONS || []).forEach(a => {
    const lbl = fmtDate(a.date);
    if (!labels.includes(lbl)) return;
    annots['a' + a.date] = {
      type: 'line', xMin: lbl, xMax: lbl,
      borderColor: '#94a3b866', borderWidth: 1, borderDash: [4, 4],
      label: {
        display: true, content: a.label,
        color: '#94a3b8', backgroundColor: '#1e293b',
        font: { size: 9 }, position: 'start',
      },
    };
  });

  // Inspector chart: stacked bars (C + H) with Unique CVEs line on right axis
  CHARTS['trendInsp']?.destroy();
  CHARTS['trendInsp'] = new Chart(document.getElementById('trendInspChart'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          type: 'bar', label: 'Critical',
          data: TREND_SERIES.map(s => s.insp_crit),
          backgroundColor: '#ef444488', borderColor: '#ef4444', borderWidth: 1,
          stack: 's', yAxisID: 'yL',
        },
        {
          type: 'bar', label: 'High',
          data: TREND_SERIES.map(s => s.insp_high),
          backgroundColor: '#f9731688', borderColor: '#f97316', borderWidth: 1,
          stack: 's', yAxisID: 'yL',
        },
        {
          type: 'line', label: 'Unique CVEs',
          data: TREND_SERIES.map(s => s.unique_cves),
          borderColor: '#146bfa', backgroundColor: '#146bfa22',
          borderWidth: 2, pointRadius: 5, pointBackgroundColor: '#146bfa',
          tension: 0, yAxisID: 'yR',
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x:  { grid: { color: '#334155' }, ticks: { color: '#e2e8f0', font: { size: 11 } } },
        yL: {
          type: 'linear', position: 'left', stacked: true,
          grid: { color: '#334155' },
          ticks: { color: '#94a3b8', font: { size: 10 },
                   callback: v => v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1e3 ? (v/1e3).toFixed(0)+'K' : v },
          title: { display: true, text: 'Findings (C+H)', color: '#94a3b8', font: { size: 11 } },
        },
        yR: {
          type: 'linear', position: 'right',
          grid: { display: false },
          ticks: { color: '#146bfa', font: { size: 10 },
                   callback: v => v >= 1e3 ? (v/1e3).toFixed(0)+'K' : v },
          title: { display: true, text: 'Unique CVEs', color: '#146bfa', font: { size: 11 } },
        },
      },
      plugins: {
        legend:     { labels: { color: '#94a3b8', font: { size: 11 }, boxWidth: 12, padding: 10 } },
        tooltip:    { ...DARK, callbacks: { label: i => ' ' + i.dataset.label + ': ' + fmtN(i.raw) } },
        annotation: { annotations: annots },
      },
    },
  });

  // GitHub Source chart: Total + three source breakdowns on a single log Y axis.
  // Log scale handles the 145 (Secrets) vs ~2,700 (Dependabot) range without a dual axis.
  const ghTotalSeries = TREND_SERIES.map(s =>
    (typeof s.gh_total === 'number') ? s.gh_total : (s.gh_vuln + s.gh_code + s.gh_secrets)
  );
  CHARTS['trendGh']?.destroy();
  CHARTS['trendGh'] = new Chart(document.getElementById('trendGhChart'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Total (GitHub Overview)', data: ghTotalSeries,
          borderColor: '#146bfa', backgroundColor: '#146bfa22',
          borderWidth: 3, pointRadius: 5, tension: 0 },
        { label: 'Dependabot Vulns', data: TREND_SERIES.map(s => s.gh_vuln),
          borderColor: '#f97316', backgroundColor: '#f9731622',
          borderWidth: 2, pointRadius: 4, tension: 0 },
        { label: 'Code Scanning',    data: TREND_SERIES.map(s => s.gh_code),
          borderColor: '#eab308', backgroundColor: '#eab30822',
          borderWidth: 2, pointRadius: 4, tension: 0 },
        { label: 'Secret Scanning',  data: TREND_SERIES.map(s => s.gh_secrets),
          borderColor: '#ef4444', backgroundColor: '#ef444422',
          borderWidth: 2, pointRadius: 4, tension: 0 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: { grid: { color: '#334155' }, ticks: { color: '#e2e8f0', font: { size: 11 } } },
        y: {
          // Linear, not logarithmic: these series are expected to reach 0
          // (that's the success state) and Chart.js log axes cannot plot 0.
          type: 'linear',
          beginAtZero: true,
          grid: { color: '#334155' },
          ticks: { color: '#94a3b8', font: { size: 10 },
                   callback: v => v >= 1e3 ? (v/1e3).toFixed(0)+'K' : v },
          title: { display: true, text: 'Open Alerts', color: '#94a3b8', font: { size: 11 } },
        },
      },
      plugins: {
        legend:     { labels: { color: '#94a3b8', font: { size: 11 }, boxWidth: 12, padding: 10 } },
        tooltip:    { ...DARK, callbacks: { label: i => ' ' + i.dataset.label + ': ' + fmtN(i.raw) } },
        annotation: { annotations: annots },
      },
    },
  });

  // GitHub Severity chart: mirrors GitHub Security Overview "Open alerts over time".
  // Total + Critical/High/Medium/Low computed across all three sources.
  renderGhSeverityChart(labels, annots);
}

// Render the GitHub Severity trend chart. Severity counts are computed across
// all three sources (Dependabot + Code Scanning + Secrets) on a single log axis.
function renderGhSeverityChart(labels, annots) {
  const totalSeries = TREND_SERIES.map(s =>
    (typeof s.gh_total === 'number') ? s.gh_total : (s.gh_vuln + s.gh_code + s.gh_secrets)
  );
  const critSeries = TREND_SERIES.map(s => s.gh_sev_critical);
  const highSeries = TREND_SERIES.map(s => s.gh_sev_high);
  const medSeries  = TREND_SERIES.map(s => s.gh_sev_medium);
  const lowSeries  = TREND_SERIES.map(s => s.gh_sev_low);

  CHARTS['trendGhSev']?.destroy();
  CHARTS['trendGhSev'] = new Chart(document.getElementById('trendGhSevChart'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Total (GitHub Overview)', data: totalSeries,
          borderColor: '#146bfa', backgroundColor: '#146bfa22',
          borderWidth: 3, pointRadius: 5, tension: 0 },
        { label: 'Critical', data: critSeries,
          borderColor: '#ec4899', backgroundColor: '#ec489922',
          borderWidth: 2, pointRadius: 4, tension: 0 },
        { label: 'High',     data: highSeries,
          borderColor: '#f97316', backgroundColor: '#f9731622',
          borderWidth: 2, pointRadius: 4, tension: 0 },
        { label: 'Medium',   data: medSeries,
          borderColor: '#eab308', backgroundColor: '#eab30822',
          borderWidth: 2, pointRadius: 4, tension: 0 },
        { label: 'Low',      data: lowSeries,
          borderColor: '#94a3b8', backgroundColor: '#94a3b822',
          borderWidth: 2, pointRadius: 4, tension: 0 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: { grid: { color: '#334155' }, ticks: { color: '#e2e8f0', font: { size: 11 } } },
        y: {
          // Linear, not logarithmic: these series are expected to reach 0
          // (that's the success state) and Chart.js log axes cannot plot 0.
          type: 'linear',
          beginAtZero: true,
          grid: { color: '#334155' },
          ticks: { color: '#94a3b8', font: { size: 10 },
                   callback: v => v >= 1e3 ? (v/1e3).toFixed(0)+'K' : v },
          title: { display: true, text: 'Open Alerts', color: '#94a3b8', font: { size: 11 } },
        },
      },
      plugins: {
        legend:     { labels: { color: '#94a3b8', font: { size: 11 }, boxWidth: 12, padding: 10 } },
        tooltip:    { ...DARK, callbacks: { label: i => ' ' + i.dataset.label + ': ' + fmtN(i.raw) } },
        annotation: { annotations: annots },
      },
    },
  });
}

// ── Executive summary (separate fn to keep renderAll readable) ────────────────
function renderExec(insp, gh, corr, rawTotal) {
  const top1Qw    = (corr.pkg_quickwin||[])[0];
  const top2Qw    = (corr.pkg_quickwin||[])[1];
  const allSignals = (corr.convergence||[]).filter(r=>r.signal_count>=4);
  const paradoxRepos = (corr.repo_ranking||[]).filter(r=>
    (r.insp_crit+r.insp_high)>8000 && (r.gh_crit+r.gh_high)<=10
  );

  // P0 exec banner
  if (gh.secrets_total > 0) {
    const aws = gh.secrets_by_type.find(x=>x.type==='aws_access_key_id');
    const db  = gh.secrets_by_type.find(x=>x.type==='mongodb_atlas_db_uri_with_credentials');
    document.getElementById('execBanner').innerHTML =
      `<div class="banner-p0" style="margin-bottom:24px"><div class="icon">⚠</div><div>
         <div class="title">P0 — ${gh.secrets_total} credentials exposed in source code</div>
         <div class="sub">${aws?fmtN(aws.count)+' AWS key pairs':''}${db?' · '+fmtN(db.count)+' production database URIs':''} — rotate before any other remediation work.</div>
       </div></div>`;
  } else {
    document.getElementById('execBanner').innerHTML = '';
  }

  const findings = [
    gh.secrets_total>0 ? {
      title:`${gh.secrets_total} credentials exposed in source code`,
      body:`AWS keys, DB URIs, and API tokens across ${gh.secrets_by_repo.length} repos. ${(gh.secrets_by_repo[0]||{}).repo||''} carries the highest concentration. Live exposures until rotated — not a vulnerability backlog item.`,
      tag:'tag-p0', tagLabel:'P0 · Secret Scanning',
    } : null,
    paradoxRepos.length>0 ? (()=>{
      const named=paradoxRepos.slice(0,2).map(r=>r.repo);
      const rest=paradoxRepos.length-named.length;
      const s=named.join(', ')+(rest>0?` and ${rest} other${rest>1?'s':''}`:'');
      const top=paradoxRepos[0];
      return {
        title:`${s} rank high by score but are Zone B — image only`,
        body:`${s} appear near the top of the combined ranking, yet their source code is almost clean on Dependabot (${top.repo}: ${fmtN(top.insp_crit+top.insp_high)} Inspector C+H vs ${fmtN(top.gh_crit+top.gh_high)} GitHub C+H). Every finding is in the deployed image, not application code. The same base image upgrade that covers 24 repos resolves all of ${paradoxRepos.length===1?'it':'them'}. The ranking reflects fan-out inflation, not a signal that these services need dedicated attention beyond the base image work.`,
        tag:'tag-insp', tagLabel:'Inspector · Zone B only',
      };
    })() : null,
    {title:`Raw findings (${fmt(rawTotal)}) reduce to ~${fmtN(insp.unique_cves)} unique CVEs`,
     body:`Average fan-out is ${insp.fanout}×. Shared base-image layers typically dominate the raw count — see the Dominant Base Layers table in the posture report; one FROM change closes every finding tied to that layer across all repos that inherit it.`,
     tag:'tag-insp', tagLabel:'Inspector V2'},
    {title:`${fmtN(corr.zone_a_pkgs)} packages vulnerable in both deployed images and source code`,
     body:`Zone A packages are confirmed end-to-end. A fix closes findings in Inspector and Dependabot simultaneously. ${fmtN(gh.vuln_total)} Dependabot alerts open.`,
     tag:'tag-both', tagLabel:'Both Sources'},
    allSignals.length>0 ? {
      title:`${allSignals.map(r=>r.repo).join(', ')} flagged by all four security signals`,
      body:`Inspector, Dependabot, Code Scanning, and Secret Scanning independently flag the same repo${allSignals.length>1?'s':''}. Highest-confidence indicator of systemic technical debt — not explainable by a shared base image.`,
      tag:'tag-both', tagLabel:'Cross-source',
    } : null,
    {title:`${gh.code_total} SAST findings, ${gh.code_errors} errors`,
     body:`Code scanning (CodeQL) active org-wide. ${(gh.cs_by_repo[0]||{}).repo||''} leads with ${(gh.cs_by_repo[0]||{}).count||0} alerts. SAST surfaces logic bugs that package scanners cannot detect.`,
     tag:'tag-gh', tagLabel:'Code Scanning'},
  ].filter(Boolean).slice(0,5);

  const priorities = [
    gh.secrets_total>0 ? {
      title:'Rotate exposed credentials immediately',
      body:`${gh.secrets_total} open alerts. Start with ${(gh.secrets_by_repo[0]||{}).repo||'the highest-concentration repo'} (${(gh.secrets_by_repo[0]||{}).count||0} alerts)${(gh.secrets_by_type[0]||{}).type?', dominated by '+(gh.secrets_by_type[0].type.replace(/_/g,' ')):''}. Independent of vulnerability sprint.`,
      tag:'tag-p0', tagLabel:'P0 · Immediate',
    } : null,
    {title:'Upgrade the shared base image',
     body:'Inspector findings concentrate in shared base layers — a base image upgrade (newer slim/distroless variant) closes them across every repo inheriting the layer. The Dominant Base Layers table in the posture report maps layers to repos.',
     tag:'tag-insp', tagLabel:'Inspector · Sprint'},
    top1Qw ? {
      title:`Update ${top1Qw.pkg} across ${top1Qw.repos} repos (QW score ${fmtN(top1Qw.score)})`,
      body:`Highest quick-win in Zone A. Closes ${fmtN(top1Qw.insp_ch)} Inspector C+H + ${fmtN(top1Qw.gh_ch)} GitHub C+H simultaneously. Fix available.`,
      tag:'tag-both', tagLabel:`${top1Qw.label} · Days`,
    } : null,
    top2Qw ? {
      title:`Update ${top2Qw.pkg} across ${top2Qw.repos} repos`,
      body:`Second-highest quick-win. ${fmtN(top2Qw.insp_ch+top2Qw.gh_ch)} combined C+H. Can be batched with the ${top1Qw?top1Qw.pkg:''} sweep in a single dependency sprint.`,
      tag:'tag-both', tagLabel:`${top2Qw.label} · Days`,
    } : null,
    (()=>{
      const st=(corr.pkg_quickwin||[]).find(p=>p.label==='Structural');
      return st ? {
        title:`Migrate off ${st.pkg} (abandoned package)`,
        body:`${st.pkg} is abandoned — no upstream fix will ever ship. ${fmtN(st.insp_ch+st.gh_ch)} combined C+H findings are permanent until it is replaced. Requires engineering design.`,
        tag:'tag-insp', tagLabel:'Structural · Sprint+',
      } : null;
    })(),
  ].filter(Boolean).slice(0,5);

  const rows=(items,nc)=>items.map((it,i)=>`
    <div class="exec-item">
      <div class="exec-num ${nc}">${i+1}</div>
      <div>
        <div class="exec-title">${esc(it.title)}</div>
        <div class="exec-body">${esc(it.body)}</div>
        <span class="exec-tag ${it.tag}">${esc(it.tagLabel)}</span>
      </div>
    </div>`).join('');

  document.getElementById('execFindings').innerHTML   = rows(findings,   'exec-num-f');
  document.getElementById('execPriorities').innerHTML = rows(priorities, 'exec-num-p');
}

// ── Boot ──────────────────────────────────────────────────────────────────────
renderAll();
</script>
</body>
</html>"""


# ── Build ──────────────────────────────────────────────────────────────────────

def build(corr_path: Path, reports_dir: Path) -> str:
    slug    = date_slug(corr_path)
    data    = extract(corr_path, reports_dir)

    saved   = save_snapshot(slug, data, reports_dir)
    print(f"   snapshot saved → {saved.name}", flush=True)

    all_snaps = load_all_snapshots(reports_dir)
    dates     = sorted(all_snaps.keys(), reverse=True)
    print(f"   {len(dates)} snapshot(s) embedded: {', '.join(dates)}", flush=True)

    trend_series = build_trend_series(all_snaps)

    # Account/region come from the snapshot data (posture_snapshot.py derives the
    # account via STS at collection time). Legacy snapshots pre-dating that field
    # fall back to the org name alone.
    acct   = data.get("account", "")
    region = data.get("region",  "")
    header = " · ".join(x for x in (acct, region, ORG) if x) or ORG
    subs = {
        "__SNAPSHOTS__":    js_literal(all_snaps),
        "__DATES__":        js_literal(dates),
        "__CURRENT_DATE__": js_literal(slug),
        "__TREND_SERIES__": js_literal(trend_series),
        "__ANNOTATIONS__":  js_literal(ANNOTATIONS),
        "'__ORG__'":        js_literal(ORG),
        "__TITLE__":        html_escape(TITLE),
        "__ORG_ACCOUNT__":  html_escape(header),
    }
    return fill_placeholders(HTML, subs)


def js_literal(obj):
    """JSON for a <script> block. Escaping <, > and & as \\u sequences keeps a data
    string such as `</script>` from ending the block; JSON reads them back unchanged."""
    return (json.dumps(obj, default=str)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def fill_placeholders(template, subs):
    """Substitute every placeholder in one pass, so text inserted from the data is
    never scanned for placeholders itself."""
    pattern = re.compile("|".join(re.escape(k) for k in sorted(subs, key=len, reverse=True)))
    return pattern.sub(lambda m: subs[m.group(0)], template)


def main():
    parser = argparse.ArgumentParser(description="Build security dashboard from correlation JSON")
    parser.add_argument("correlation_file", nargs="?",
                        help="Correlation JSON path relative to reports_dir, e.g. '20260525/correlation.json' (default: latest)")
    parser.add_argument("--reports-dir", help="Directory for snapshot read/write (overrides $SECURITY_SNAPSHOT_REPORTS_DIR)")
    args = parser.parse_args()

    reports_dir = _resolve_reports_dir(args)

    if args.correlation_file:
        corr_path = reports_dir / args.correlation_file
    else:
        corr_path = latest_file("correlation.json", reports_dir)

    if not corr_path or not corr_path.exists():
        sys.exit("No correlation found. Run: python3 correlation.py --raw --reports-dir <dir>")

    print(f"→ Loading {corr_path.name} ...", flush=True)
    html = build(corr_path, reports_dir)

    out = reports_dir / "security-dashboard.html"
    out.write_text(html)
    print(f"✓ Dashboard → {out}", flush=True)
    print(f"  Open:  open {out}", flush=True)


if __name__ == "__main__":
    main()
