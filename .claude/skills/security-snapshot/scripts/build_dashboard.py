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
from movement_page import build_moved
from correlation import (CONVERGENCE_TOP_N, W_CODE_SCAN, W_GH_CRIT, W_GH_HIGH, W_INSP_CRIT,
                         W_INSP_HIGH, W_SECRET)

# The combined repo ranking's weights, as correlation.py scores it; the chart labels read these.
RANK_WEIGHTS = {"insp_crit": W_INSP_CRIT, "insp_high": W_INSP_HIGH, "gh_crit": W_GH_CRIT,
                "gh_high": W_GH_HIGH, "code_scan": W_CODE_SCAN, "secret": W_SECRET}

_CFG  = _load_config()
ORG   = _require(_CFG, "github_org")
TITLE = (_CFG.get("dashboard_title") or "").strip() or "Security Dashboard"

# Event annotations rendered as vertical markers on the Trend tab.
# Maintained in config.json ("annotations") — add an entry whenever a
# significant remediation action or disclosure lands.
ANNOTATIONS = _CFG.get("annotations") or []
REGION      = (_CFG.get("aws_region") or "").strip()
# First snapshot the What moved trend line shows (YYYYMMDD); empty shows all.
TREND_START = (_CFG.get("trend_start") or "").strip()


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
            "insp_ch":         insp.get("critical", 0) + insp.get("high", 0),
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
<link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&family=Roboto+Mono:wght@500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f172a;--surface:#1e293b;--surface2:#253047;--border:#334155;
  --text:#e2e8f0;--muted:#94a3b8;--primary:#146bfa;
  --crit:#ef4444;--high:#f97316;--med:#eab308;--low:#22c55e;
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
/* Tabs */
.tab-nav{display:flex;gap:0;border-bottom:1px solid var(--border);margin-bottom:20px}
.tab-btn{padding:10px 22px;cursor:pointer;color:var(--muted);border:none;background:transparent;font-family:inherit;font-size:13px;font-weight:500;border-bottom:2px solid transparent;transition:color .15s,border-color .15s}
.tab-btn:hover{color:var(--text)}
.tab-btn.active{color:var(--primary);border-bottom-color:var(--primary)}
.tab-pane{display:none}.tab-pane.active{display:block}
/* Cards & grids */
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px}
.card-title{font-size:14px;font-weight:600;color:var(--primary);margin-bottom:12px}
.grid-6{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:20px}
.grid-2{display:grid;gap:16px;margin-bottom:20px}
.grid-2-6{grid-template-columns:2fr 1fr}
.grid-2-eq{grid-template-columns:1fr 1fr}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:20px}
@media(max-width:1300px){.grid-6{grid-template-columns:repeat(3,1fr)}}
@media(max-width:1100px){.grid-2-6,.grid-2-eq{grid-template-columns:1fr}.grid-3{grid-template-columns:1fr 1fr}}
@media(max-width:640px){.grid-6,.grid-3{grid-template-columns:1fr}}
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
/* Repo links */
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
/* Buttons */
.btn{padding:7px 18px;border-radius:5px;font-family:inherit;font-size:12px;font-weight:500;cursor:pointer;border:1px solid var(--border);transition:all .15s}
.btn-primary{background:var(--primary);border-color:var(--primary);color:#fff}
.btn-primary:hover{background:#0d4fb8}
.btn-primary:disabled{opacity:.4;cursor:not-allowed}
.btn-ghost{background:transparent;color:var(--muted)}
.btn-ghost:hover{color:var(--text);border-color:var(--muted)}
/* What moved */
.mv-bases{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:16px}
.mv-basis{padding:6px 14px;border:1px solid var(--border);border-radius:999px;background:transparent;color:var(--muted);cursor:pointer;font-family:inherit;font-size:12px}
.mv-basis.active{color:var(--text);border-color:var(--primary);background:#146bfa1f}
.mv-meta{color:var(--muted);font-size:11.5px}
.mv-good{color:var(--low)}.mv-bad{color:var(--crit)}
.mv-k,.mv-eyebrow{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.mv-eyebrow{text-transform:none;letter-spacing:0;font-size:12px}
.mv-hero{display:grid;grid-template-columns:auto 1fr 300px;gap:28px;align-items:center;border-left:4px solid var(--border)}
.mv-hero.mv-good{border-left-color:var(--low)}.mv-hero.mv-bad{border-left-color:var(--crit)}
.mv-hero.mv-good .mv-from,.mv-hero.mv-bad .mv-from{color:var(--muted)}
.mv-big{font-size:50px;font-weight:700;line-height:1;letter-spacing:-.02em}
.mv-from{color:var(--muted);font-size:14px;margin-top:8px}.mv-from b{color:var(--text)}
.mv-factors{display:flex;flex-direction:column;gap:12px}
.mv-v{font-size:18px;font-weight:600;color:var(--text)}
.mv-v small{font-size:12px;color:var(--muted);font-weight:400;margin-left:6px}
.mv-hint{font-size:12px;color:var(--muted)}
.mv-spark-cap{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-top:4px}
.mv-spark-cap b{color:var(--text);font-weight:500}
.mv-warns{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}
.mv-warn{display:flex;gap:10px;border:1px solid #f59e0b59;background:#f59e0b12;padding:10px 14px;border-radius:10px}
.mv-warn-i{color:#f59e0b;font-weight:700}
.mv-warn b{display:block;font-size:13px;color:#fcd34d}
.mv-warn span{color:var(--muted);font-size:12px}
.mv-sec{margin-top:44px;padding-top:26px;border-top:1px solid #2a3649}
.mv-sec h2{font-size:22px;font-weight:700;letter-spacing:-.01em;margin-bottom:6px}
.mv-sec-lede{color:var(--muted);font-size:13px;max-width:760px;margin-bottom:18px}
.mv-lead{font-size:17px;font-weight:500;line-height:1.45;max-width:880px}
.mv-gap-top{margin-top:14px}
.mv-md p,.mv-md ul{margin:0 0 8px;color:#cbd5e1}
.mv-md ul{padding-left:20px}.mv-md li{margin-bottom:4px}
.mv-md p:last-child,.mv-md ul:last-child{margin-bottom:0}
.mv-md code,.mv-item code{background:var(--surface2);padding:1px 4px;border-radius:3px;font-size:12px}
.mv-md table{margin:10px 0 4px;max-width:560px}
#movedPanel a:not(.mv-lk){color:#7fb0ff;text-decoration:none}
#movedPanel a:not(.mv-lk):hover{text-decoration:underline}
.mv-levers{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.mv-lever{display:flex;flex-direction:column;gap:12px}
.mv-lever-head{display:grid;grid-template-columns:auto 1fr;gap:14px;align-items:start}
.mv-rank{font-family:'Roboto Mono',ui-monospace,monospace;font-size:34px;line-height:.9;color:var(--primary)}
.mv-owner{display:inline-block;margin-top:6px;font-size:11px;color:#93c5fd;background:#146bfa24;padding:1px 9px;border-radius:999px}
.mv-impact{display:flex;align-items:center;gap:12px}
.mv-bar{flex:1;height:8px;background:var(--surface2);border-radius:4px;overflow:hidden}
.mv-bar i{display:block;height:100%;background:var(--primary);border-radius:4px}
.mv-pct{font-size:20px;font-weight:700;min-width:58px;text-align:right}
.mv-abs{font-size:12px;color:var(--muted);min-width:110px}
.mv-how{font-size:12.5px;color:#cbd5e1}
.mv-list{border-top:1px solid #2a3649}.mv-list-more{border-top:none}
.mv-item{display:grid;grid-template-columns:1fr auto auto;gap:14px;align-items:center;padding:8px 0;border-bottom:1px solid #2a3649}
.mv-item-n{font-weight:500}.mv-item-d{color:var(--muted);font-size:11.5px}
.mv-num{text-align:right;font-variant-numeric:tabular-nums}
.mv-acts{display:flex;gap:6px;justify-content:flex-end}
.mv-lk{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;padding:3px 8px;border:1px solid var(--border);border-radius:6px;color:#7fb0ff;background:transparent;cursor:pointer;font-family:inherit;line-height:1.3;text-decoration:none}
.mv-lk:hover{border-color:#7fb0ff}
.mv-icon{width:26px;justify-content:center;padding:3px 0}.mv-icon svg{width:13px;height:13px}
.mv-icon.done{color:var(--low);border-color:var(--low)}
.mv-lever details summary{cursor:pointer;color:#7fb0ff;font-size:12px;padding-top:8px;list-style:none}
.mv-lever details summary::before{content:'+ '}.mv-lever details[open] summary::before{content:'− '}
.mv-sub{font-size:12px;color:var(--muted);margin-bottom:14px}
.dtag-basis{background:#f59e0b22;color:#fbbf24;border:1px solid #f59e0b55}
.dtag-note{background:#a78bfa22;color:#c4b5fd;border:1px solid #a78bfa55}
.mv-lever h3{font-size:15px;font-weight:600;line-height:1.35}
/* What moved: the agent's blocks (STYLEGUIDE.md) */
.mv-tone-fix{--tone:var(--low)}.mv-tone-inventory{--tone:#94a3b8}.mv-tone-gap{--tone:#f59e0b}.mv-tone-risk{--tone:var(--crit)}.mv-tone-unknown{--tone:#a78bfa}.mv-tone-info{--tone:#38bdf8}.mv-tone-none{--tone:var(--text)}
.mv-note{display:flex;flex-direction:column;gap:14px;margin-top:16px}
.mv-note>.mv-md{max-width:920px}
.mv-md h3{font-size:17px;font-weight:600;color:var(--text);margin:18px 0 4px}
.mv-md h4{font-size:14px;font-weight:600;color:var(--text);margin:12px 0 4px}
.mv-md h5{font-size:13px;color:var(--text);margin:12px 0 6px}
.mv-stats-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.mv-stat-block{background:var(--surface);border:1px solid var(--border);border-left:4px solid var(--tone);border-radius:10px;padding:14px 16px}
.mv-stat-v{font-size:30px;font-weight:700;line-height:1.05;color:var(--tone);font-variant-numeric:tabular-nums;white-space:nowrap}
.mv-stat-wide .mv-stat-v{font-size:23px}
.mv-stat-l{font-size:12.5px;color:var(--text);margin-top:6px}.mv-stat-s{font-size:11.5px;color:var(--muted);margin-top:2px}
button.mv-stat-block{font-family:inherit;text-align:left;cursor:pointer;width:100%}
.mv-stat-link{display:grid;grid-template-columns:auto 1fr;align-items:stretch;padding-left:0}
.mv-stat-idx{display:flex;align-items:center;justify-content:center;min-width:52px;padding:0 12px;margin:-14px 14px -14px 0;
  border-right:1px solid var(--border);background:linear-gradient(180deg,transparent,#ffffff06);
  font-family:'Roboto Mono',ui-monospace,monospace;font-size:38px;font-weight:500;line-height:1;color:var(--tone);opacity:.7}
.mv-stat-link:hover .mv-stat-idx{opacity:1}
.mv-md h3[data-index]{display:flex;align-items:center;gap:10px}
.mv-md h3[data-index]::before{content:attr(data-index);flex:none;display:inline-flex;align-items:center;justify-content:center;
  width:28px;height:28px;border-radius:50%;border:1.5px solid var(--tone);color:var(--tone);
  font-family:'Roboto Mono',ui-monospace,monospace;font-size:14px;font-weight:500}
.mv-stat-link{transition:border-color .15s,transform .15s}.mv-stat-link:hover{border-color:var(--tone);transform:translateY(-1px)}
.mv-stat-go{font-size:11px;color:#7fb0ff;margin-top:8px}
.mv-md h3{scroll-margin-top:16px;border-radius:6px;transition:background .3s,box-shadow .3s}
.mv-md h3.mv-flash{background:#146bfa26;box-shadow:0 0 0 6px #146bfa26}
.panel-link{margin-left:8px;background:none;border:none;cursor:pointer;font-size:12px;line-height:1;opacity:.45;transition:opacity .15s;padding:0;vertical-align:middle}
.panel-link:hover,.panel-link:focus-visible{opacity:1}
.panel-flash{box-shadow:0 0 0 2px var(--primary);border-radius:8px;transition:box-shadow .3s}
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--surface);border:1px solid var(--primary);color:var(--text);padding:10px 18px;border-radius:6px;font-size:12px;z-index:9999;opacity:0;transition:opacity .2s;pointer-events:none}
.toast.show{opacity:1}
.mv-chart-block h4,.mv-chart-title{font-size:14px;font-weight:600;margin-bottom:2px}
.mv-callout{border:1px solid var(--border);border-left:4px solid var(--tone);background:var(--surface);border-radius:10px;padding:12px 16px}
.mv-callout b{display:block;color:var(--tone);font-size:13.5px;margin-bottom:4px}
.mv-block-error{border:1px dashed var(--crit);color:#fca5a5;border-radius:8px;padding:10px 14px;font-size:12px}
@media (max-width:900px){.mv-hero{grid-template-columns:1fr}.mv-warns,.mv-levers{grid-template-columns:1fr}}
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
  <button class="tab-btn active" data-tab="moved"     onclick="switchTab(this,'moved')">What moved</button>
  <button class="tab-btn"         data-tab="breakdown" onclick="switchTab(this,'breakdown')">Breakdown</button>
  <button class="tab-btn"         data-tab="trend"     onclick="switchTab(this,'trend')">Trend</button>
</div>

<!-- What moved tab: the default -->
<div id="tab-moved" class="tab-pane active">
  <div id="movedPanel"></div>
</div>

<!-- Breakdown tab -->
<div id="tab-breakdown" class="tab-pane">
  <div id="secretsBanner"></div>
  <div class="grid-6" id="kpiRow"></div>
  <div class="grid-3" style="margin-bottom:20px" id="zoneRow"></div>

  <div class="card" style="margin-bottom:20px">
    <div class="card-title">Top Offenders — Repos Flagged by Multiple Signals</div>
    <p style="color:var(--muted);font-size:11px;margin-bottom:12px">
      Repos in the top __TOP_N__ of 2+ independent signal categories.
    </p>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>Repository</th><th>Signals</th><th>Insp C+H</th><th>GH C+H</th><th>Code Scan</th><th>Secrets</th><th>Score</th></tr></thead>
      <tbody id="convergenceTbody"></tbody>
    </table></div>
  </div>

  <div class="grid-2 grid-2-6" style="margin-bottom:20px">
    <div class="card">
      <div class="card-title">Combined Repo Rankings — All Four Signals</div>
      <p style="color:var(--muted);font-size:11px;margin-bottom:10px">Each bar is a repo's combined score: every source counted with the weight in its label.</p>
      <div style="height:360px"><canvas id="repoRankChart"></canvas></div>
    </div>
    <div style="display:flex;flex-direction:column;gap:16px">
      <div class="card">
        <div class="card-title">Secret Scanning — Open Alerts</div>
        <p style="color:#fca5a5;font-size:11px;margin-bottom:10px">Default (provider-pattern) secret types only; generic secret types are not collected.</p>
        <div style="height:180px"><canvas id="secretTypeChart"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">Code Scanning (SAST)</div>
        <div style="height:140px"><canvas id="csRepoChart"></canvas></div>
      </div>
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
    <p style="color:var(--muted);font-size:11px;margin-bottom:10px">Stacked bars: Critical + High raw findings (left axis). Blue line: unique CVEs (right axis) — distinct vulnerabilities, without fan-out across images.</p>
    <div style="height:340px"><canvas id="trendInspChart"></canvas></div>
  </div>
  <div class="card" style="margin-bottom:20px">
    <div class="card-title">GitHub Security Alerts — by Source</div>
    <p style="color:var(--muted);font-size:11px;margin-bottom:10px">Total open alerts and the three sources: Dependabot vulnerabilities, code scanning (SAST) and default secret alerts.</p>
    <div style="height:300px"><canvas id="trendGhChart"></canvas></div>
  </div>
  <div class="card">
    <div class="card-title">GitHub Security Alerts — by Severity</div>
    <p style="color:var(--muted);font-size:11px;margin-bottom:10px">Severity across Dependabot, code scanning (errors as High, warnings as Medium) and default secret alerts (counted as Critical; generic secret types are not collected). Code-scanning severity is approximated from error and warning levels.</p>
    <div style="height:300px"><canvas id="trendGhSevChart"></canvas></div>
  </div>
</div><!-- /tab-trend -->

</div><!-- /page -->
<div id="toast" class="toast" role="status" aria-live="polite"></div>
<script>
const SNAPSHOTS    = __SNAPSHOTS__;
const DATES        = __DATES__;
const CURRENT_DATE = __CURRENT_DATE__;
const ORG          = '__ORG__';
const TREND_SERIES = __TREND_SERIES__;
const ANNOTATIONS  = __ANNOTATIONS__;
const RANK_WEIGHTS = __RANK_WEIGHTS__;
const MOVED        = __MOVED__;
const REGION       = __REGION__;
const TREND_START  = __TREND_START__;
const PUBLISHED_URL = __PUBLISHED_URL__;
__APP_JS__
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
    moved        = build_moved(reports_dir, dates, ORG, REGION)

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
        "__RANK_WEIGHTS__": js_literal(RANK_WEIGHTS),
        "__TOP_N__":        str(CONVERGENCE_TOP_N),
        "__MOVED__":        js_literal(moved),
        "__REGION__":       js_literal(REGION),
        "__TREND_START__":  js_literal(TREND_START if re.fullmatch(r"\d{8}", TREND_START) else ""),
        "__PUBLISHED_URL__": js_literal(published_url(reports_dir)),
        "'__ORG__'":        js_literal(ORG),
        "__TITLE__":        html_escape(TITLE),
        "__ORG_ACCOUNT__":  html_escape(header),
        "__APP_JS__":       page_js(),
    }
    return fill_placeholders(panel_links(HTML), subs)


def slug_panel(title):
    """core.js slugPanel(), for the card titles written into the page itself."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]


def panel_links(template):
    """Give every card title an anchor and a share link. Runs on the template, before
    any data goes in, so only titles written here get one. Two cards with one slug
    would share a link, so that stops the build."""
    seen = set()

    def link(m):
        sid = slug_panel(m.group(1))
        if not sid or sid in seen or re.fullmatch(r"\d{8}", sid):
            raise ValueError(f"card title {m.group(1)!r} gives no unique section id ({sid!r})")
        seen.add(sid)
        return (f'<div class="card-title" data-panel="{sid}">{m.group(1)}<button type="button" class="panel-link" '
                f'title="Copy a link to this section" onclick="sharePanel(\'{sid}\')">🔗</button></div>')
    return re.sub(r'<div class="card-title">([^<]*)</div>', link, template)


def published_url(reports_dir):
    """The deployed /exec URL from clasp-projects.json, or "" (a local build, or no
    usable deploy config). Only an Apps Script URL is accepted: it becomes the base
    of every copied link."""
    try:
        url = json.loads((Path(reports_dir) / "clasp-projects.json").read_text()).get("url") or ""
    except (OSError, ValueError, AttributeError):
        return ""
    return url if isinstance(url, str) and re.fullmatch(r"https://script\.google\.com/macros/s/[\w-]+/exec", url) else ""


JS_DIR = Path(__file__).resolve().parent / "dashboard"
# Load order matters: helpers, page logic, the What moved panel, then first paint.
JS_FILES = ("core.js", "app.js", "moved.js", "boot.js")


def page_js(js_dir=JS_DIR):
    """The page's JavaScript, read from scripts/dashboard/ and inlined so the page
    stays one self-contained file. A file that could end the <script> block early
    stops the build."""
    parts = []
    for name in JS_FILES:
        src = (js_dir / name).read_text()
        if re.search(r"</script", src, re.I):
            raise ValueError(f"{name} contains '</script' and would end the page's script block")
        parts.append(src.rstrip("\n"))
    return "\n\n".join(parts)


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
