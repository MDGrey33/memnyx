"""movement_markdown.py — render a security_movement() result as markdown.

Takes the file's prior content as an argument rather than reading it, so the
"never clobber written prose" contract is testable without touching disk.
"""
from __future__ import annotations

GENERATED_MARKER = ("<!-- generated above this line — /security-snapshot rewrites it. "
                    "Written notes below survive. -->")

WHY_STUB = """## Why it moved

_Not yet written._ Read the sections above, then the raw snapshot files they
summarise, and state the driver behind each material movement. Where the
evidence supports more than one story, say so and name what would settle it."""


def preserved_from(prior):
    """Everything a rebuild must not destroy: what follows the marker, or the
    whole file when the marker is absent (it was not written by this tool)."""
    if not isinstance(prior, str) or not prior.strip():
        return ""
    i = prior.find(GENERATED_MARKER)
    return prior.strip() if i == -1 else prior[i + len(GENERATED_MARKER):].strip()


def _n(v, signed=False):
    if v is None:
        return "–"
    if isinstance(v, float) and not v.is_integer():
        return f"{v:+,.1f}" if signed else f"{v:,.1f}"
    return f"{int(v):+,d}" if signed else f"{int(v):,d}"


def _pct(v):
    return "–" if v is None else f"{v:+.1f}%"


def _cell(v):
    """One table cell. Cells can carry third-party text (advisory summaries):
    a pipe or newline would break the table, and an HTML comment opener could
    forge the generated marker and make the next rebuild keep generated text
    as written notes."""
    return (str(v).replace("\\", "\\\\").replace("\r", " ").replace("\n", " ")
            .replace("|", "\\|").replace("<!--", "&lt;!--"))


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _counts(mv):
    rows = [[("**" + m["label"] + "**") if m["headline"] else m["label"], _n(m["prev"]), _n(m["curr"]),
             _n(m["delta"], True), _pct(m["pct"])] for m in mv["counts"]]
    return "## Headline counts\n\n" + _table(["Metric", "Previous", "Current", "Change", "%"], rows)


def _inspector(mv):
    d = mv["inspector"]
    lines = ["## Inspector: images × critical + high per image", ""]
    if d is None:
        return "\n".join(lines + ["Not available: repository aggregation missing from a snapshot."])
    p, c = d["prev"], d["curr"]
    lines.append("ECR critical + high is images with findings × critical + high per image. It moves when "
                 "inventory changes as much as when risk does, so read the factors before the total.\n")
    x = lambda r: "–" if r is None else f"×{r:.3f}"  # noqa: E731
    lines.append(_table(["", "Previous", "Current", "Ratio"], [
        ["Images with findings", _n(p["images"]), _n(c["images"]), x(d["images_ratio"])],
        ["Critical + high per image", _n(p["per_image"]), _n(c["per_image"]), x(d["per_image_ratio"])],
        ["ECR critical + high", _n(p["ecr_ch"]), _n(c["ecr_ch"]), x(d["ecr_ch_ratio"])],
        ["Outside ECR (EC2, Lambda)", _n(p["non_ecr_ch"]), _n(c["non_ecr_ch"]), ""],
    ]))
    return "\n".join(lines)


def _controls(mv):
    lines = ["## Unchanged inventory", ""]
    h = mv["held_layers"]
    if h is None:
        lines.append("Base layers: not available.")
    elif not h["layers"]:
        lines.append(f"Base layers: none of the {h['captured_curr']} captured layers held the same image count.")
    else:
        scope = (f"{len(h['layers'])} of {h['captured_curr']} layers with findings" if h.get("complete")
                 else f"{len(h['layers'])} of the top {h['captured_curr']} layers only; older snapshots hold no full list")
        lines.append(f"**Base layers with an unchanged image count** ({scope}): critical + high {_n(h['prev_ch'])} → {_n(h['curr_ch'])} ({_pct(h['pct'])}). Same digest "
                     f"means same layer content, so this is new detection against unchanged software.\n")
        lines.append(_table(["Layer", "Images", "Previous", "Current", "Repos"],
                            [[f"`{x['layer'][7:19]}`", x["images"], _n(x["prev_ch"]), _n(x["curr_ch"]),
                              ", ".join(x["repos"][:3]) + (" …" if len(x["repos"]) > 3 else "")]
                             for x in h["layers"][:8]]))
    if h is not None and h.get("left_layers"):
        lines.append(f"\n{h['left_layers']} layer(s) from the previous snapshot are no longer listed (previous critical + high "
                     f"{_n(h['left_prev_ch'])}). Their findings fell to zero or their images left; this control cannot tell "
                     f"which, so they are in neither total above.")
    s = mv["repo_image_stability"]
    if s is not None:
        lines.append(f"\nContext only: {s['repos']} repos kept the same image count ({s['images']} images); their "
                     f"critical + high moved {_n(s['prev_ch'])} → {_n(s['curr_ch'])} ({_pct(s['pct'])}). The same count is "
                     f"not the same images, because retention swaps rebuilt images in, so this is not a control.")
    return "\n".join(lines)


def _captures(mv):
    lines = ["## First seen in the window, and rebuilt vs older images", ""]
    fs, rb = mv["captures"]["first_seen"], mv["captures"]["rebuild"]
    if fs is None or fs.get("total") is None:
        lines.append(f"First seen: not available ({(fs or {}).get('status', 'not captured in this snapshot')}).")
    else:
        e = fs["ecr"]
        lines.append(f"**First seen since `{fs['basis_snapshot']}`:** {_n(fs['total'])} active critical + high. "
                     f"On images that existed before the window: {_n(e['existing_images'])} ({e['images_existing']} images), "
                     f"which is new detection on unchanged images. On images pushed in the window: {_n(e['pushed_since'])} "
                     f"({e['images_pushed_since']} images), new by construction.")
    lines.append("")
    if rb is None or rb.get("repos") is None:
        lines.append(f"Rebuilt vs older: not available ({(rb or {}).get('status', 'not captured in this snapshot')}).")
    else:
        t = rb["totals"]
        per = lambda ch, n: _n(round(ch / n, 1)) if n else "–"  # noqa: E731
        flagged = [r["repo"] for r in rb["repos"] if r["flagged"]]
        lines.append(f"**Rebuilt vs older, same repo, same database:** older {per(t['old_ch'], t['old_images'])} per image "
                     f"({t['old_images']} images), pushed in window {per(t['new_ch'], t['new_images'])} ({t['new_images']} images). "
                     + (f"Flagged ({rb['flag_rule']}): {', '.join(flagged)}." if flagged
                        else f"No repo flagged ({rb['flag_rule']}) across {len(rb['repos'])} comparable."))
    return "\n".join(lines)


def _movers(mv):
    m = mv["movers"]
    lines = ["## Movers", ""]
    if m["package_groups"]:
        lines.append("Packages are grouped by the action that fixes them. Counts are per package, across every "
                     "resource type: a finding that names two packages counts in both.\n")
        if not m.get("managers_captured"):
            lines.append("_No package-manager map in either snapshot: everything outside the kernel headers shows as "
                         "unknown. Snapshots from this version on carry the map._\n")
        lines.append(_table(["Group", "Change", "Share", "Fix"],
                            [[g["group"], _n(g["delta"], True), _pct(g["share_pct"]).lstrip("+"), g["fix"]]
                             for g in m["package_groups"]]))
        lines.append("")
    if m["packages"]:
        lines.append(_table(["Package", "Group", "Previous", "Current", "Change", "Dependabot"],
                            [[p["package"], p["group"], _n(p["prev_ch"]), _n(p["curr_ch"]), _n(p["delta"], True),
                              "yes" if p.get("github") else ""] for p in m["packages"]]))
        lines.append("\n_Dependabot = also flagged by GitHub in the source; a Dependabot PR may already be open._\n")
    if m["repos"]:
        lines.append(_table(["Repository", "Previous (images)", "Current (images)", "Change"],
                            [[r["repo"], f"{_n(r['prev_ch'])} ({_n(r['prev_images'])})",
                              f"{_n(r['curr_ch'])} ({_n(r['curr_images'])})", _n(r["delta"], True)] for r in m["repos"]]))
    if len(lines) == 2:
        lines.append("Not available.")
    return "\n".join(lines)


def _github(mv):
    g, c = mv["github"], mv["correlation"]
    lines = ["## GitHub and correlation", ""]
    if g is None:
        lines.append("Dependabot instances vs distinct: not available.")
    else:
        lines.append(f"Dependabot alerts {_n(g['prev_instances'])} → {_n(g['curr_instances'])}; distinct advisories "
                     f"{_n(g['prev_distinct'])} → {_n(g['curr_distinct'])} ({g['new_distinct']} new, {g['gone_distinct']} gone). "
                     f"New advisories account for {_n(g['new_instances'])} alerts. Instances rising with distinct flat is "
                     f"fan-out; distinct rising is new advisories.\n")
        if g["top_new"]:
            lines.append(_table(["New advisory", "Package", "Alerts"],
                                [[a["advisory"], a["package"], a["instances"]] for a in g["top_new"]]))
    if c is not None:
        lines.append(f"\nPackages flagged by both sources: {c['prev']} → {c['curr']}. "
                     f"Entered: {', '.join(c['entered'][:15]) or 'none'}. Left: {', '.join(c['left'][:15]) or 'none'}.")
    return "\n".join(lines)


NODE_STATES = {
    "measured": "Host kernels: {kernel_ch} critical + high across {instances_scanned} scanned hosts ({platforms}).",
    "not_measured": ("Host kernels: not measured. Inspector covers {instances_scanned} hosts ({platforms}) but returns "
                     "no package findings for them, so their kernel exposure is not in these numbers."),
    "no_hosts_scanned": "Host kernels: no EC2 hosts are scanned.",
}


def _levers(mv):
    lv = mv.get("levers")
    lines = ["## Remediation levers", ""]
    if not lv or not lv["levers"]:
        failed = lv and lv.get("breakdown_status") not in (None, "ok")
        why = ("the captures behind them failed; see Data quality." if failed
               else "this snapshot predates the lever capture.")
        return "\n".join(lines + [f"Not available: {why}"] + _hosts(lv))
    lines.append(f"Current stock, not movement: what each change removes from today's critical + high "
                 f"({_n(lv['total_ch'])}). Levers can overlap where a package sits in a listed layer; the "
                 f"base-layer figures already exclude the kernel-header and bundled-runtime findings. Running counts "
                 f"the findings on images in use when Inspector last checked; the rest close when their images age out "
                 f"of rescanning. A dash means not measured. A finding that names two bundled packages counts under both, in "
                 f"Removes and in Running.\n")
    if lv.get("breakdown_status") not in (None, "ok"):
        lines.append(f"_Per-repo breakdown {lv['breakdown_status']}: kernel-header and bundled-runtime levers omitted, "
                     f"and base-layer counts include their findings._\n")
    lines.append(_table(["Lever", "Removes", "Running", "Share", "Who", "How"],
                        [[l["title"], _n(l["removes_ch"]), _n(l.get("running_ch")), _pct(l["share_pct"]).lstrip("+"),
                          l["owner"], l["action"]] for l in lv["levers"]]))
    for l in lv["levers"]:
        if not l["rows"]:
            continue
        lines.append(f"\n### {l['title']}\n")
        if l["key"] == "kernel_headers":
            lines.append(_table(["Repository", "Critical + high", "Running", "Images", "OS", "Header versions",
                                 "Fixed version exists"],
                                [[r["repo"], _n(r["ch"]), _n(r.get("running_ch")), r["images"], ", ".join(r["platforms"]),
                                  ", ".join(r["versions"]), _pct(r["fix_pct"]).lstrip("+")] for r in l["rows"]]))
        elif l["key"] == "bundled_runtimes":
            lines.append(_table(["Package", "Critical + high", "Running", "Repos", "Fixed version exists"],
                                [[r["package"], _n(r["ch"]), _n(r.get("running_ch")),
                                  ", ".join(r["repos"][:5]) + (" …" if len(r["repos"]) > 5 else ""),
                                  _pct(r["fix_pct"]).lstrip("+")] for r in l["rows"]]))
        elif l["key"] == "base_layers":
            if not l["net_of_other_levers"]:
                lines.append("_Gross counts: no per-repo breakdown to net off the levers above._\n")
            if not l["complete"]:
                lines.append("_From the top layers only: this snapshot holds no full layer list._\n")
            lines.append(_table(["Layer", "Critical + high", "Images", "Repos"],
                                [[f"`{r['layer'][7:19]}`", _n(r["ch"]), _n(r["images"]),
                                  ", ".join(r["repo_list"][:4]) + (f" (+{r['repos'] - 4})" if r["repos"] > 4 else "")]
                                 for r in l["rows"]]))
        elif l["key"] == "dependabot_dependencies":
            lines.append(_table(["Package", "Critical + high", "GitHub critical + high", "GitHub repos", "Ecosystem"],
                                [[r["package"], _n(r["ch"]), _n(r.get("gh_ch")), _n(r.get("gh_repos")), r["manager"]]
                                 for r in l["rows"]]))
    return "\n".join(lines + _hosts(lv))


def _hosts(lv):
    """Host kernel evidence. Rendered with or without levers: it answers a different question."""
    lines = []
    n = (lv or {}).get("nodes")
    if n is not None:
        lines.append("\n" + NODE_STATES[n["state"]].format(
            kernel_ch=_n(n["kernel_ch"]), instances_scanned=n["instances_scanned"],
            platforms=", ".join(n["platforms"]) or "platform not reported"))
        rel = n.get("release")
        if rel and rel["nodes"]:
            lines.append("\nHost OS release (the kernel ships inside it):\n")
            lines.append(_table(["OS", "Kubernetes", "Running", "Hosts", "Latest", "Latest published", "On latest"],
                                [[x["os"], x["k8s"], x["version"], x["instances"], x["latest"] or "–", x["latest_published"] or "–",
                                  {True: "yes", False: "**no**"}.get(x["on_latest"], "unknown")] for x in rel["nodes"]]))
            if rel.get("other_instances"):
                lines.append(f"\n{rel['other_instances']} running instance(s) are on another image and are not read here.")
    return lines


def _quality(mv):
    if not mv["data_quality"]:
        return None
    return "## Data quality\n\nA flag is not a driver. Check these before explaining any movement.\n\n" + \
        "\n".join(f"- **{f['kind']}**: {f['note']}" for f in mv["data_quality"])


def render_movement_markdown(mv, prior=""):
    title = f"# Security movement: {mv.get('curr_date') or 'current'} vs {mv.get('prev_date') or 'previous'}"
    preamble = ("Everything above the marker is generated by `/security-snapshot` and rewritten on every run. "
                "It says what moved, never why.")
    sections = [title, "", preamble, ""]
    q = _quality(mv)
    if q:
        sections += [q, ""]
    sections += [_counts(mv), "", _levers(mv), "", _inspector(mv), "", _controls(mv), "", _captures(mv), "", _movers(mv), "", _github(mv)]
    sections += ["", GENERATED_MARKER, "", preserved_from(prior) or WHY_STUB, ""]
    return "\n".join(sections)
