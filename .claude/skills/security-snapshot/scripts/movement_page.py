"""What moved, for the dashboard page.

For each snapshot the page embeds, compute the same comparisons emit_movement.py
writes to movement.md (against the previous snapshot and against the 30-day
basis) and shape them for the page's What moved tab.

Two layers. The fixed panels are built from the data and look the same every
snapshot: the verdict with its warnings, the waterfall by fixing action, the repo
movers and the remediation levers. The "Why it moved" section is the note the
agent writes below the marker in the movement file: markdown with typed blocks
(stat, bar, line, callout) that the agent chooses per snapshot, following
dashboard/STYLEGUIDE.md. This module validates the blocks and escapes everything;
the page draws them. Rebuilding never calls the agent.

The newest snapshot's comparisons carry every panel. Older ones carry the
verdict, the waterfall and the note; the rest stays in their movement files.
"""
from __future__ import annotations

import html
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import emit_movement as em  # noqa: E402
from movement import security_movement  # noqa: E402
from movement_markdown import WHY_STUB, preserved_from  # noqa: E402

NOTE_HEADING = "Why it moved"
# Tones a block may take; the page gives each a colour (STYLEGUIDE.md).
TONES = ("fix", "inventory", "gap", "risk", "unknown", "info")
BLOCK_TYPES = ("stat", "bar", "line", "callout")
LEVER_ITEMS = 12
# Limits on what a block may carry, so a malformed note cannot flood the page.
MAX_TEXT, MAX_ROWS, MAX_POINTS, MAX_SERIES = 200, 20, 60, 4


# ── Links ─────────────────────────────────────────────────────────────────────

def link_policy(org, region=""):
    """The links a note may carry: the org's GitHub, GitHub advisories and pull
    request search, and the AWS console. The note quotes third-party text, so an
    open allowlist would let an advisory plant a link of its choosing."""
    org_l = (org or "").lower()

    def allowed(url):
        try:
            u = urlsplit(url)
            if u.scheme != "https" or u.username or u.password or u.port is not None:  # .port raises on a bad port; :0 is a port
                return False
        except ValueError:
            return False
        host, path = (u.hostname or "").lower(), u.path.lower()
        if host == "github.com":
            # The browser resolves . and .. (%2e too) before it opens a link, so a
            # path that climbs out of the org could reach any github.com page.
            segments = unquote(path).split("/")
            if "\\" in unquote(path) or any(s in (".", "..") for s in segments):
                return False
            return bool(org_l) and (path.startswith((f"/{org_l}/", f"/orgs/{org_l}/")) or path in (f"/{org_l}", f"/orgs/{org_l}")
                                    or path == "/advisories" or path.startswith("/advisories/") or path == "/pulls")
        return host == "console.aws.amazon.com" or (host.endswith(".console.aws.amazon.com") and host.count(".") == 4)
    return allowed


# ── Markdown to HTML: the subset movement_markdown.py writes, plus notes ──────
# Everything is escaped first; the only tags in the output are the ones added here.

LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")


def _inline(text, allow=None):
    parts = text.split("`")
    out = []
    for i, part in enumerate(parts):
        if i % 2 and i < len(parts) - 1:
            out.append(f"<code>{html.escape(part, quote=True)}</code>")
            continue
        links = []

        def keep(m):
            label, url = m.group(1), m.group(2)
            if allow and allow(url):
                links.append(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
                             f'{html.escape(label, quote=True)}</a>')
            else:  # a link outside the allowlist keeps its words and loses its target
                links.append(html.escape(label, quote=True))
            return f"\x00{len(links) - 1}\x00"
        t = html.escape(LINK_RE.sub(keep, part.replace("\x00", "")), quote=True)
        if i % 2:  # an unmatched backtick stays literal
            t = "`" + t
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<![\w*])_(?!\s)(.+?)(?<!\s)_(?![\w])", r"<em>\1</em>", t)
        out.append(re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], t))
    return "".join(out)


def _cells(row):
    """Split a table row on unescaped pipes, undoing movement_markdown._cell's escapes."""
    cells, buf, i, s = [], [], 0, row.strip()
    if s.startswith("|"):
        s = s[1:]
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            buf.append(s[i + 1])
            i += 2
            continue
        if c == "|":
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
        i += 1
    if "".join(buf).strip():
        cells.append("".join(buf).strip())
    return [c.replace("&lt;!--", "<!--") for c in cells]


SEPARATOR_RE = re.compile(r"\|?(\s*:?-+:?\s*\|)+\s*")
# A heading: one to four #s, then its text or nothing (an empty heading shows nothing).
HEADING_RE = re.compile(r"(#{1,4})(?:\s+(.*?))?(?:\s+#+)?\s*$")


def _table(rows, allow=None):
    head, body = _cells(rows[0]), [_cells(r) for r in rows[1:] if not SEPARATOR_RE.fullmatch(r.strip())]
    th = "".join(f"<th>{_inline(c, allow)}</th>" for c in head)
    trs = "".join("<tr>" + "".join(f"<td>{_inline(c, allow)}</td>" for c in r) + "</tr>" for r in body)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


def section_key(text):
    """How a stat's link names a heading: its words, case and markup ignored."""
    return " ".join(re.sub(r"[*_`]", "", text).split()).casefold()


def md_to_html(md, allow=None, shift=2, anchors=None):
    """shift moves headings down: movement.md's own sections sit below the page's
    headings (### → h5); a note's ### driver headings stay h3. With anchors (a dict
    shared across one note), each heading gets an id a stat can link to, recorded
    as {section_key: id}."""
    md = COMMENT_RE.sub("", md)
    out, para, items, table = [], [], [], []

    def flush():
        if para:
            out.append(f"<p>{_inline(' '.join(para), allow)}</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{_inline(x, allow)}</li>" for x in items) + "</ul>")
            items.clear()
        if table:
            if len(table) > 1 and SEPARATOR_RE.fullmatch(table[1]):
                out.append(_table(table, allow))
            else:  # a line that starts with | is a table only with a separator row under it
                out.append(f"<p>{_inline(' '.join(table), allow)}</p>")
            table.clear()

    for line in md.split("\n"):
        s = line.strip()
        if not s:
            flush()
        elif s.startswith("<!--"):
            flush()
        elif m := HEADING_RE.match(s):  # closing #s are not part of the heading
            flush()
            if not m.group(2):
                continue
            level = min(len(m.group(1)) + shift, 6)
            ident = ""
            if anchors is not None:
                base = "mv-s-" + (re.sub(r"[^a-z0-9]+", "-", section_key(m.group(2))).strip("-")[:60] or "section")
                hid, n = base, 2
                while hid in anchors.values():
                    hid, n = f"{base}-{n}", n + 1
                key = section_key(m.group(2))
                # A link goes to the first ### section with its text: the level the
                # page numbers. Any other heading, or a repeat, is recorded under a
                # key no link text can produce, so its id stays taken.
                linkable = level == 3 and key not in anchors
                anchors[key if linkable else f"{key}\0{hid}"] = hid
                ident = f' id="{hid}"'
            out.append(f"<h{level}{ident}>{_inline(m.group(2), allow)}</h{level}>")
        elif s.startswith("|"):
            if para or items:
                flush()
            table.append(s)
        elif s.startswith(("- ", "* ")):
            if para or table:
                flush()
            items.append(s[2:])
        elif items and line.startswith((" ", "\t")):
            items[-1] += " " + s
        else:
            if items or table:
                flush()
            para.append(s)
    flush()
    return "\n".join(out)


# ── The note: markdown with typed blocks ──────────────────────────────────────

# Any line opening with a fence marker starts a block, so a mistyped one (```Stat,
# ~~~stat, a bare ```) shows as an error instead of turning into garbled prose.
FENCE_RE = re.compile(r"^(`{3,}|~{3,})(.*)$")
# Comments are the writer's, never the reader's, including ones over several lines.
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


class BlockError(ValueError):
    pass


def _text(v, name, required=True, limit=MAX_TEXT):
    """Validated plain text. Not escaped here: the page escapes it where it
    reaches HTML, and a chart draws it as text on a canvas."""
    if v is None and not required:
        return None
    if not isinstance(v, str) or not v.strip():
        raise BlockError(f"'{name}' must be text")
    if len(v) > limit:
        raise BlockError(f"'{name}' is longer than {limit} characters")
    return v.strip()


def _tone(d):
    tone = d.get("tone")
    if tone is None:
        return None
    if tone not in TONES:
        raise BlockError(f"'tone' must be one of {', '.join(TONES)}")
    return tone


def _number(v, where):
    # bool is an int in Python; a chart value of true is a mistake, not a 1.
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise BlockError(f"{where} must be a number")
    try:
        finite = math.isfinite(float(v))  # a 400-digit integer overflows here, and is ∞ in the browser
    except OverflowError:
        finite = False
    if not finite:
        raise BlockError(f"{where} must be a number")
    return v + 0  # -0.0 is 0.0, which the browser would show as "-0"


def _series_rows(d, key, min_rows, max_rows):
    series = d.get("series")
    if not isinstance(series, list) or not 1 <= len(series) <= MAX_SERIES:
        raise BlockError(f"'series' must list 1 to {MAX_SERIES} names")
    names = [_text(s, "series", limit=60) for s in series]
    rows = d.get(key)
    if not isinstance(rows, list) or not min_rows <= len(rows) <= max_rows:
        raise BlockError(f"'{key}' must have {min_rows} to {max_rows} entries")
    out = []
    for i, r in enumerate(rows):
        if not isinstance(r, list) or len(r) != len(names) + 1:
            raise BlockError(f"{key}[{i}] must be [label, {len(names)} value(s)]")
        out.append([_text(r[0], f"{key}[{i}] label", limit=80)] + [_number(v, f"{key}[{i}]") for v in r[1:]])
    return names, out


def parse_block(kind, body, allow=None):
    """One fenced block as a validated dict. Raises BlockError with a reason a
    note writer can act on."""
    if kind not in BLOCK_TYPES:
        raise BlockError(f"unknown block type '{kind}'; use one of {', '.join(BLOCK_TYPES)}")
    try:
        d = json.loads(body)
    except json.JSONDecodeError as e:
        raise BlockError(f"not valid JSON ({e.msg}, line {e.lineno})") from None
    except ValueError:  # an integer past Python's digit limit
        raise BlockError("not valid JSON (a number with too many digits)") from None
    except RecursionError:
        raise BlockError("not valid JSON (nested too deeply)") from None
    if not isinstance(d, dict):
        raise BlockError("must be a JSON object")
    if kind == "stat":
        value = d.get("value")
        if isinstance(value, bool):
            raise BlockError("'value' must be text or a number")
        if isinstance(value, (int, float)):
            value = f"{_number(value, 'value'):,}"  # json.loads accepts NaN and 1e400
        return {"type": "stat", "value": _text(value, "value", limit=24), "label": _text(d.get("label"), "label", limit=80),
                "sub": _text(d.get("sub"), "sub", required=False), "tone": _tone(d),
                "link": _text(d.get("link"), "link", required=False, limit=120)}
    if kind == "bar":
        series, rows = _series_rows(d, "rows", 1, MAX_ROWS)
        return {"type": "bar", "title": _text(d.get("title"), "title"), "unit": _text(d.get("unit"), "unit", required=False, limit=40),
                "series": series, "rows": rows, "tone": _tone(d)}
    if kind == "line":
        series, points = _series_rows(d, "points", 2, MAX_POINTS)
        return {"type": "line", "title": _text(d.get("title"), "title"), "unit": _text(d.get("unit"), "unit", required=False, limit=40),
                "series": series, "points": points}
    body_md = d.get("body")
    if not isinstance(body_md, str) or len(body_md) > 4 * MAX_TEXT:
        raise BlockError(f"'body' must be text of at most {4 * MAX_TEXT} characters")
    return {"type": "callout", "title": _text(d.get("title"), "title"), "html": md_to_html(body_md, allow, shift=0),
            "tone": _tone(d) or "info"}


def _starts_block(s):
    """What md_to_html renders as a heading, list or table: a line starting "#482" is prose."""
    return bool(HEADING_RE.match(s)) or s.startswith(("- ", "* ", "|"))


def note_view(md, allow=None):
    """{lead, blocks} from a written note, or None when nothing is written.

    The opening paragraph is the verdict sentence. The rest becomes blocks in
    order: prose chunks rendered from markdown ({"type": "html"}), and fenced
    stat, bar, line and callout blocks. A block that fails validation becomes
    {"type": "error"} with the reason, so one mistake costs one block.
    """
    if not md or md.strip() == WHY_STUB.strip():
        return None
    lines = md.strip().split("\n")
    if lines and re.match(rf"##\s+{re.escape(NOTE_HEADING)}\s*$", lines[0].strip()):
        lines = lines[1:]
    blocks, prose, i, lead, anchors = [], [], 0, None, {}

    def flush():
        nonlocal lead
        text = "\n".join(prose).strip()
        prose.clear()
        if not text:
            return
        if lead is None and not blocks:
            # The lead is the opening paragraph: it ends at a blank line or at a
            # heading, list or table, none of which is a verdict sentence.
            ls = text.split("\n")
            j = 0
            while j < len(ls) and ls[j].strip() and not _starts_block(ls[j].strip()):
                j += 1
            if j:
                lead, text = _inline(" ".join(" ".join(ls[:j]).split()), allow), "\n".join(ls[j:]).strip()
        if text:
            blocks.append({"type": "html", "html": md_to_html(text, allow, shift=0, anchors=anchors)})

    while i < len(lines):
        m = FENCE_RE.match(lines[i].strip())
        if not m:
            # A comment is stripped from prose only: inside a block, "<!--" is data.
            # One that runs over several lines hides them, fences included.
            k, text = i, lines[i]
            while "<!--" in COMMENT_RE.sub("", text) and k + 1 < len(lines):
                k += 1
                text += "\n" + lines[k]
            if "<!--" in COMMENT_RE.sub("", text):  # never closed: an error; the lines after it are shown
                prose.append(COMMENT_RE.sub("", lines[i]).split("<!--")[0])
                flush()
                blocks.append({"type": "error", "message": "a comment is never closed with -->"})
                i += 1
                continue
            prose.extend(COMMENT_RE.sub("", text).split("\n"))
            i = k + 1
            continue
        marker, kind = m.group(1), m.group(2).strip()
        end = nxt = None
        for j in range(i + 1, len(lines)):
            s = lines[j].strip()
            if s and s == marker[0] * len(s) and len(s) >= len(marker):  # ```` closes ``` too, as in markdown
                end = j
                break
            n = FENCE_RE.match(s)
            if n and n.group(2).strip():  # the next block opens before this one closed
                nxt = j
                break
        flush()
        name = kind or "fenced"
        if end is None:
            blocks.append({"type": "error", "message": f"the {name} block is never closed with {marker}"})
            if nxt is None:
                break
            i = nxt
            continue
        try:
            if not kind:
                raise BlockError(f"a fenced block needs a type: {', '.join(BLOCK_TYPES)}")
            blocks.append(parse_block(kind, "\n".join(lines[i + 1:end]), allow))
        except BlockError as e:
            blocks.append({"type": "error", "message": f"{name} block: {e}"})
        i = end + 1
    flush()
    # A stat's link names a section heading anywhere in the note; resolve it once
    # every heading is known. A link to no heading is the writer's mistake to see.
    # Each section takes the number of the one stat that links to it.
    linked = set()
    for k, b in enumerate(blocks):
        if b["type"] == "stat" and b.get("link"):
            target = anchors.get(section_key(b["link"]))
            if not target:
                blocks[k] = {"type": "error", "message": f"stat block: 'link' names no ### section heading: {b['link']}"}
            elif target in linked:
                blocks[k] = {"type": "error", "message": f"stat block: an earlier stat already links to this section: {b['link']}"}
            else:
                b["target"] = target
                linked.add(target)
    if not lead and not blocks:  # a heading, a comment or white space: nothing written
        return None
    return {"lead": lead or "", "blocks": blocks}


# ── Plain-language warnings ────────────────────────────────────────

def _n(v):
    return f"{int(v):,}" if isinstance(v, (int, float)) else "–"


def warnings_view(mv):
    """One {kind, title, body} per data-quality flag, worded for the engineer reading the page."""
    counts = {c["key"]: c for c in mv.get("counts") or []}
    out = []
    for f in mv.get("data_quality") or []:
        c = counts.get(f.get("key")) or {}
        label, prev, curr, pct = c.get("label", f.get("key")), c.get("prev"), c.get("curr"), c.get("pct")
        kind = f.get("kind")
        if kind == "outlier":
            rise = f"rose {pct:g}%" if pct is not None else "rose from 0"
            out.append({"kind": kind, "title": f"{label} {rise} ({_n(prev)} → {_n(curr)})",
                        "body": "A large jump. Check that the capture is complete before reading it as new risk."})
        elif kind == "inventory":
            fewer = (pct or 0) < 0
            out.append({"kind": kind,
                        "title": f"{abs(pct or 0):.0f}% {'fewer' if fewer else 'more'} images scanned ({_n(prev)} → {_n(curr)})",
                        "body": "A change in the number of images scanned moves the total without any image changing."})
        elif kind == "not_comparable":
            out.append({"kind": kind, "title": f"{label} is missing from one snapshot",
                        "body": "No change can be shown for it."})
        else:
            out.append({"kind": "capture_status", "title": f"Part of this snapshot failed to collect: {f.get('key')}",
                        "body": "The figures that depend on it are left out, not shown as zero. " + str(f.get("note") or "")})
    return out


# ── Components ────────────────────────────────────────────────────────────────

def _verdict(mv):
    counts = {c["key"]: c for c in mv.get("counts") or []}
    ch, crit = counts.get("inspector_ch"), counts.get("inspector_critical")
    if not ch or not ch.get("comparable"):
        return None
    out = {"label": ch["label"], "prev": ch["prev"], "curr": ch["curr"], "delta": ch["delta"], "pct": ch["pct"],
           "critical": {"prev": crit["prev"], "curr": crit["curr"]} if crit and crit.get("comparable") else None,
           "factors": None}
    insp = mv.get("inspector")
    if isinstance(insp, dict):
        p, c = insp["prev"], insp["curr"]
        # The factors multiply to the ECR total, not the account total above it.
        out["factors"] = {"images": [p["images"], c["images"]], "per_image": [p["per_image"], c["per_image"]],
                          "images_ratio": insp.get("images_ratio"), "per_image_ratio": insp.get("per_image_ratio"),
                          "ecr": [p.get("ecr_ch"), c.get("ecr_ch")]}
    return out


def _waterfall(mv):
    """Critical + high by package from the basis to now, stepped by the action that
    fixes it. Start, end and steps are all package counts, so the steps add up."""
    movers = mv.get("movers") or {}
    groups, totals = movers.get("package_groups"), movers.get("package_totals")
    if not groups or not isinstance(totals, dict):
        return None
    label = {"unknown": "Package manager unknown"}
    steps = [{"label": label.get(g["group"], g["group"][:1].upper() + g["group"][1:]), "delta": g["delta"]}
             for g in groups if g.get("delta")]
    return {"start": totals["prev"], "end": totals["curr"], "steps": steps}


def _platform(p):
    m = re.fullmatch(r"([A-Z]+)_(\d+)_(\d+)", p or "")
    return f"{m.group(1).title()} {m.group(2)}.{m.group(3)}" if m else (p or "").replace("_", " ").title()


def _lever_items(lv):
    rows = lv.get("rows") or []
    key = lv.get("key")
    if key == "kernel_headers":
        return [{"kind": "repo", "name": r["repo"], "ch": r["ch"],
                 "detail": " · ".join(x for x in (", ".join(_platform(p) for p in r.get("platforms") or []),
                                                  ("headers " + ", ".join(r["versions"])) if r.get("versions") else "") if x)}
                for r in rows[:LEVER_ITEMS]]
    if key == "dependabot_dependencies":
        def github(r):
            gh, repos = r.get("gh_ch"), r.get("gh_repos")
            if gh is None:
                return ""
            where = f" in {repos} repo{'s' if repos != 1 else ''}" if isinstance(repos, int) else ""
            return f"GitHub: {gh:,} critical + high{where}"
        return [{"kind": "package", "name": r["package"], "ch": r["ch"], "dependabot": True,
                 "detail": " · ".join(x for x in ((r.get("manager") or "").lower(), github(r)) if x)}
                for r in rows[:LEVER_ITEMS]]
    if key == "base_layers":
        return [{"kind": "layer", "name": (r.get("layer") or "").removeprefix("sha256:")[:12], "ch": r["ch"],
                 "detail": f"{r.get('images', 0)} images · {r.get('repos', 0)} repos"} for r in rows[:LEVER_ITEMS]]
    return [{"kind": "package", "name": r.get("package") or r.get("repo"), "ch": r["ch"],
             "detail": f"in {len(r['repos'])} repos" if isinstance(r.get("repos"), list) else "", "dependabot": False}
            for r in rows[:LEVER_ITEMS]]


def _levers(mv):
    lv = mv.get("levers")
    if not isinstance(lv, dict) or not lv.get("levers"):
        return None
    return [{"key": x["key"], "title": x["title"], "owner": x["owner"][:1].upper() + x["owner"][1:],
             "how": x["action"], "removes": x["removes_ch"], "running": x.get("running_ch"), "share": x["share_pct"],
             "items": _lever_items(x), "more": max(len(x.get("rows") or []) - LEVER_ITEMS, 0)}
            for x in lv["levers"]]


def _days(window):
    m = re.fullmatch(r"DAYS_(\d+)", window or "")
    return int(m.group(1)) if m else None


def _gap_row(r):
    return {"kind": "Lambda" if r["kind"] == "lambda" else "Cluster", "name": r["name"],
            "image": (f"{r['repo']}@{(r.get('digest') or '').removeprefix('sha256:')[:12]}" if r.get("repo") else "–"),
            "why": "Inspector has no record of this image" if r.get("status") == "NOT_IN_COVERAGE"
                   else "multi-architecture image; its platform images could not be read"
                   if r.get("status") == "PLATFORMS_UNKNOWN"
                   else f"could not be read ({r.get('reason')})" if r.get("status") == "UNREAD"
                   else "rescanning lapsed" if r.get("reason") == "SCAN_ELIGIBILITY_EXPIRED"
                   else (r.get("reason") or r.get("status") or "").replace("_", " ").lower(),
            "lapse": (r.get("lapse_at") or "")[:10] or None}


def _scan_gaps(mv):
    g = mv.get("scan_gaps")
    if not isinstance(g, dict):
        return None
    w = g.get("windows") or {}
    return {"running": g["running"], "soon_days": g["soon_days"], "functions_measured": g["functions_measured"],
            "push_days": _days(w.get("push")), "use_days": _days(w.get("use")), "mode": w.get("mode"),
            "not_scanned": [_gap_row(r) for r in g["not_scanned"]], "lapsing": [_gap_row(r) for r in g["lapsing"]]}


def page_view(mv, detail, note_md="", allow=None):
    """The page-shaped comparison. "headline" carries the verdict, warnings,
    waterfall and note; "full" adds the levers and the repo movers."""
    try:
        note = note_view(note_md, allow)
    except Exception as e:  # noqa: BLE001 — the note is written text; a parser fault costs the note, not the panels
        note = {"lead": "", "blocks": [{"type": "error", "message": f"the note could not be read ({type(e).__name__})"}]}
    view = {"verdict": _verdict(mv), "warnings": warnings_view(mv), "waterfall": _waterfall(mv), "note": note}
    if detail == "full":
        movers = mv.get("movers") or {}
        view.update({"levers": _levers(mv), "scan_gaps": _scan_gaps(mv),
                     "repos": [{"repo": r["repo"], "delta": r["delta"]} for r in movers.get("repos") or []]})
    return view


# ── Per-snapshot comparisons for the page ─────────────────────────────────────

def build_moved(reports_dir: Path, page_dates, org="", region=""):
    """{date: [entry]} for every page date that has a comparison.

    entry: basis, kind ("previous" or "30-day"), file (its movement file name),
    on_disk (that file exists; Step 6 writes it after the first build, and older
    snapshots may never have had one), detail ("full" or "headline"), view (the
    page_view() of the pair). A pair that fails to compute is listed with
    `error` instead of view, so one bad old snapshot costs its own panel and
    nothing else.
    """
    dates = sorted(p.name for p in reports_dir.iterdir()
                   if p.is_dir() and re.fullmatch(r"\d{8}", p.name) and (p / "raw.json").exists())
    targets = [d for d in dates if d in set(page_dates)]
    newest = targets[-1] if targets else None
    allow = link_policy(org, region)
    cache = {}

    def load(d):
        if d not in cache:
            cache[d] = em.load(reports_dir / d)
        return cache[d]

    moved = {}
    for d in targets:
        plan = em.resolve_targets(dates, d)
        if "pairs" not in plan:
            continue
        entries = []
        for i, (basis, fname) in enumerate(plan["pairs"]):
            entry = {"basis": basis, "kind": "previous" if i == 0 else "30-day", "file": fname,
                     "detail": "full" if d == newest else "headline"}
            try:
                f = reports_dir / d / fname
                entry["on_disk"] = f.exists()
                prior = f.read_text() if entry["on_disk"] else ""
                mv = security_movement(load(basis), load(d), basis, d)
                entry["view"] = page_view(mv, entry["detail"], preserved_from(prior), allow)
            except Exception as e:  # noqa: BLE001 — any failure degrades to this pair's panel
                print(f"   warning: movement {d} vs {basis} not computed ({type(e).__name__}: {e})", flush=True)
                entries.append({**entry, "error": f"{type(e).__name__}"})
                continue
            entries.append(entry)
        moved[d] = entries
    return moved
