"""The dashboard's JavaScript (scripts/dashboard/) and the What moved data behind it.

The node tests run from here so the suite and the pre-commit hook cover them.
They need node and nothing else: no npm packages.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import unittest.mock as mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
# The same stand-in config as test_review_fixes, so neither depends on config.local.json
# and the module is the same whichever test imports it first.
with mock.patch("config_util.load_config", return_value={"aws_profile": "p", "aws_region": "r", "github_org": "o"}):
    import build_dashboard as bd  # noqa: E402
import movement_page as mp  # noqa: E402
from movement_markdown import GENERATED_MARKER, WHY_STUB  # noqa: E402

FIXTURES = HERE / "fixtures" / "pair-a"
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node not installed")
class TestNodeSuite(unittest.TestCase):
    def test_node_tests_pass(self):
        files = sorted(str(p) for p in (HERE / "js").glob("*.test.mjs"))
        self.assertGreaterEqual(len(files), 3)
        r = subprocess.run([NODE, "--test", "--test-reporter=tap", *files], capture_output=True, text=True)
        passed = re.search(r"^# pass (\d+)$", r.stdout, re.M)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-1000:])
        self.assertIsNotNone(passed, r.stdout[-1000:])
        self.assertGreaterEqual(int(passed.group(1)), 23)  # the tests really ran


def build_fixture_page(extra=None):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    shutil.copytree(FIXTURES, root, dirs_exist_ok=True)
    if extra:
        extra(root)
    with mock.patch("sys.stdout"):
        page = bd.build(root / "20261007" / "correlation.json", root)
    return tmp, page


def page_script(page):
    return page.split("<script>")[-1].split("</script>")[0]


def embedded(page, name):
    m = re.search(rf"^const {name}\s*=\s*(.*?);$", page_script(page), re.M)
    return json.loads(m.group(1))


class TestBuiltPageWhatMoved(unittest.TestCase):
    def test_fixture_page_carries_the_comparison_and_its_note(self):
        def note(root):
            f = root / "20261007" / "movement.md"
            f.write_text(f"generated\n\n{GENERATED_MARKER}\n\n## Why it moved\n\nRetention <b>tightened</b>.\n\n"
                         "```stat\n{\"value\": \"−5k\", \"label\": \"slim images\", \"tone\": \"fix\"}\n```\n\n"
                         f"See [the repo](https://github.com/{bd.ORG}/svc).\n")
        tmp, page = build_fixture_page(note)
        self.addCleanup(tmp.cleanup)
        moved = embedded(page, "MOVED")
        self.assertEqual(list(moved), ["20261007"])
        (e,) = moved["20261007"]
        self.assertEqual((e["basis"], e["kind"], e["detail"], e["file"]), ("20260923", "previous", "full", "movement.md"))
        v = e["view"]
        self.assertEqual(sorted(v), ["levers", "note", "repos", "verdict", "warnings", "waterfall"])
        self.assertEqual(v["note"]["lead"], "Retention &lt;b&gt;tightened&lt;/b&gt;.")
        stat, prose = v["note"]["blocks"]
        self.assertEqual((stat["type"], stat["value"], stat["tone"]), ("stat", "−5k", "fix"))
        self.assertIn(f'href="https://github.com/{bd.ORG}/svc"', prose["html"])  # the configured org
        self.assertEqual(embedded(page, "REGION"), bd.REGION)

    def test_the_quick_win_matrix_is_gone_from_the_page_and_new_snapshots(self):
        # Older saved snapshots keep the field as history; the page's own markup and
        # code, and what extract() writes now, must not.
        self.assertNotRegex(bd.HTML + bd.page_js(), r"(?i)quick-win|qwChart|pkg_quickwin|phantom")
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(FIXTURES, tmp, dirs_exist_ok=True)
            data = bd.extract(Path(tmp) / "20261007" / "correlation.json", Path(tmp))
        self.assertNotIn("pkg_quickwin", data["correlation"])

    def test_the_page_takes_its_numbers_from_the_code_and_makes_no_stale_claims(self):
        import correlation as c
        tmp, page = build_fixture_page()
        self.addCleanup(tmp.cleanup)
        self.assertEqual(embedded(page, "RANK_WEIGHTS"),
                         {"insp_crit": c.W_INSP_CRIT, "insp_high": c.W_INSP_HIGH, "gh_crit": c.W_GH_CRIT,
                          "gh_high": c.W_GH_HIGH, "code_scan": c.W_CODE_SCAN, "secret": c.W_SECRET})
        self.assertIn(f"Repos in the top {c.CONVERGENCE_TOP_N} of 2+", page)
        markup = page.split("<script>")[0] + bd.page_js()
        self.assertNotRegex(markup, r"(?i)highest-confidence|matches github|mirrors github|log y axis|being resolved|"
                                    r"not a backlog|weighted higher|whatChanged|pickBaseline|__TOP_N__")

    def test_what_moved_is_the_default_tab_and_the_executive_summary_is_gone(self):
        tmp, page = build_fixture_page()
        self.addCleanup(tmp.cleanup)
        tabs = re.findall(r'<button class="tab-btn( active)?"\s+data-tab="(\w+)"', page)
        self.assertEqual(tabs, [(" active", "moved"), ("", "breakdown"), ("", "trend")])
        self.assertEqual(re.findall(r'<div id="tab-(\w+)" class="tab-pane active">', page), ["moved"])
        self.assertNotRegex(page, r"(?i)exec(utive)? summary|renderExec|tab-exec")

    @unittest.skipUnless(NODE, "node not installed")
    def test_page_script_runs_every_tab_and_snapshot(self):
        tmp, page = build_fixture_page()
        self.addCleanup(tmp.cleanup)
        script = Path(tmp.name) / "page.js"
        script.write_text(page_script(page))
        r = subprocess.run([NODE, str(HERE / "js" / "page-smoke.mjs"), str(script)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        seen = json.loads(r.stdout)
        self.assertEqual(seen["paint_charts"], ["mvTrend", "mvWaterfall", "mvRepos"])  # What moved is the default tab
        self.assertGreater(seen["charts_total"], seen["charts_on_paint"])  # Breakdown and Trend drew theirs on click
        self.assertEqual(seen["tabs"], {"trend": "#trend/20261007", "moved": "#moved/20261007",
                                        "breakdown": "#breakdown/20261007"})
        for section in ("Why it moved", "What to fix next", "Biggest moves by repo"):
            self.assertIn(f"<h2>{section}</h2>", seen["moved_current"])
        self.assertTrue(seen["moved_active"])
        self.assertEqual(sorted(seen["moved_charts"]), ["mvRepos", "mvTrend", "mvWaterfall"])  # redrawn on returning to the tab
        self.assertEqual(seen["dates"], ["20261007", "20260923"])
        self.assertGreater(seen["kpi"], 0)


def counts(**over):
    base = {"inspector_ch": ("Inspector critical + high", True, 97555, 24154),
            "inspector_critical": ("Inspector critical", True, 15514, 3878),
            "ecr_covered": ("ECR images covered", False, 382, 254),
            "gh_vuln_critical": ("Dependabot critical", True, 44, 156)}
    base.update(over)
    out = []
    for k, (label, headline, prev, curr) in base.items():
        comparable = prev is not None and curr is not None
        delta = curr - prev if comparable else None
        pct = round(delta / prev * 100, 1) if comparable and prev else None
        out.append({"key": k, "label": label, "headline": headline, "prev": prev, "curr": curr,
                    "comparable": comparable, "delta": delta, "pct": pct})
    return out


def mv_fixture(**over):
    mv = {
        "counts": counts(),
        "inspector": {"prev": {"ecr_ch": 1000, "images": 10, "per_image": 100.0, "non_ecr_ch": 5},
                      "curr": {"ecr_ch": 600, "images": 8, "per_image": 75.0, "non_ecr_ch": 5},
                      "images_ratio": 0.8, "per_image_ratio": 0.75, "ecr_ch_ratio": 0.6},
        "movers": {"repos": [{"repo": "ns-1/a", "delta": -300}, {"repo": "ns-1/b", "delta": 20}],
                   "package_groups": [{"group": "kernel headers", "delta": -350}, {"group": "unknown", "delta": -30}],
                   "package_totals": {"prev": 1100, "curr": 720}},
        "data_quality": [], "captures": {}, "held_layers": None,
        "levers": {"levers": [
            {"key": "kernel_headers", "title": "Remove kernel headers", "owner": "service team", "action": "Slim.",
             "removes_ch": 400, "share_pct": 66.7,
             "rows": [{"repo": "ns-1/a", "ch": 300, "platforms": ["UBUNTU_22_04"], "versions": ["5.15.0"]}]},
            {"key": "dependabot_dependencies", "title": "Merge", "owner": "service team", "action": "Merge.",
             "removes_ch": 100, "share_pct": 16.7, "rows": [{"package": "axios", "ch": 90, "manager": "NODE"}] * 14},
            {"key": "bundled_runtimes", "title": "Bump", "owner": "base image owner", "action": "Bump.",
             "removes_ch": 50, "share_pct": 8.3, "rows": [{"package": "openssl/openssl", "ch": 50, "repos": ["a", "b"]}]},
            {"key": "base_layers", "title": "Refresh", "owner": "base image owner", "action": "Rebuild.",
             "removes_ch": 40, "share_pct": 6.7, "rows": [{"layer": "sha256:" + "ab" * 32, "ch": 40, "images": 3, "repos": 2}]},
        ], "total_ch": 600},
        "github": {"prev_instances": 10, "curr_instances": 12, "prev_distinct": 5, "curr_distinct": 6,
                   "new_distinct": 2, "gone_distinct": 1,
                   "top_new": [{"package": "handlebars", "advisory": "CVE-2026-1", "instances": 2}]},
    }
    mv.update(over)
    return mv


class TestVerdictAndWaterfall(unittest.TestCase):
    def test_verdict_carries_the_headline_and_both_factors(self):
        v = mp.page_view(mv_fixture(), "headline")["verdict"]
        self.assertEqual((v["prev"], v["curr"], v["delta"], v["pct"]), (97555, 24154, -73401, -75.2))
        self.assertEqual(v["critical"], {"prev": 15514, "curr": 3878})
        self.assertEqual(v["factors"], {"images": [10, 8], "per_image": [100.0, 75.0], "images_ratio": 0.8,
                                        "per_image_ratio": 0.75, "ecr": [1000, 600]})  # ratios from movement.py, not the page

    def test_no_verdict_when_the_headline_is_missing_from_one_side(self):
        self.assertIsNone(mp.page_view(mv_fixture(counts=counts(inspector_ch=("x", True, None, 5))), "headline")["verdict"])

    def test_the_waterfall_is_in_package_counts_and_its_steps_add_up(self):
        w = mp.page_view(mv_fixture(), "headline")["waterfall"]
        self.assertEqual((w["start"], w["end"]), (1100, 720))  # package totals, not the ECR finding count (1000 → 600)
        self.assertEqual(w["steps"], [{"label": "Kernel headers", "delta": -350},
                                      {"label": "Package manager unknown", "delta": -30}])
        self.assertEqual(w["start"] + sum(s["delta"] for s in w["steps"]), w["end"])

    def test_no_waterfall_without_package_totals(self):
        mv = mv_fixture()
        del mv["movers"]["package_totals"]
        self.assertIsNone(mp.page_view(mv, "headline")["waterfall"])

    def test_no_waterfall_without_groups(self):
        mv = mv_fixture()
        mv["movers"]["package_groups"] = []
        self.assertIsNone(mp.page_view(mv, "headline")["waterfall"])

    def test_headline_detail_leaves_out_the_full_sections(self):
        self.assertEqual(sorted(mp.page_view(mv_fixture(), "headline")), ["note", "verdict", "warnings", "waterfall"])
        self.assertEqual(sorted(mp.page_view(mv_fixture(), "full")),
                         ["levers", "note", "repos", "verdict", "warnings", "waterfall"])

    def test_a_note_the_parser_cannot_read_costs_only_the_note(self):
        with mock.patch.object(mp, "note_view", side_effect=RuntimeError("parser fault")):
            v = mp.page_view(mv_fixture(), "headline", "Lead.")
        self.assertIsNotNone(v["verdict"])
        self.assertIsNotNone(v["waterfall"])
        self.assertEqual([b["type"] for b in v["note"]["blocks"]], ["error"])
        self.assertIn("RuntimeError", v["note"]["blocks"][0]["message"])


class TestLevers(unittest.TestCase):
    def levers(self):
        return {x["key"]: x for x in mp.page_view(mv_fixture(), "full")["levers"]}

    def test_each_lever_kind_becomes_rows_an_engineer_can_act_on(self):
        lv = self.levers()
        self.assertEqual(lv["kernel_headers"]["items"],
                         [{"kind": "repo", "name": "ns-1/a", "ch": 300, "detail": "Ubuntu 22.04 · headers 5.15.0"}])
        self.assertEqual(lv["kernel_headers"]["owner"], "Service team")
        self.assertEqual(lv["dependabot_dependencies"]["items"][0],
                         {"kind": "package", "name": "axios", "ch": 90, "detail": "node", "dependabot": True})
        self.assertEqual(lv["bundled_runtimes"]["items"][0]["detail"], "in 2 repos")
        self.assertFalse(lv["bundled_runtimes"]["items"][0]["dependabot"])
        self.assertEqual(lv["base_layers"]["items"][0]["name"], "ab" * 6)

    def test_dependabot_rows_say_what_github_sees(self):
        mv = mv_fixture()
        mv["levers"]["levers"][1]["rows"] = [{"package": "axios", "ch": 90, "manager": "NODE", "gh_ch": 216, "gh_repos": 22},
                                             {"package": "tar", "ch": 9, "manager": "NODE", "gh_ch": 3, "gh_repos": 1},
                                             {"package": "ip", "ch": 5, "manager": "NODE", "gh_ch": None, "gh_repos": None}]
        items = {x["key"]: x for x in mp.page_view(mv, "full")["levers"]}["dependabot_dependencies"]["items"]
        self.assertEqual([i["detail"] for i in items],
                         ["node · GitHub: 216 critical + high in 22 repos", "node · GitHub: 3 critical + high in 1 repo", "node"])

    def test_long_lists_are_cut_and_say_how_many_are_left(self):
        dep = self.levers()["dependabot_dependencies"]
        self.assertEqual((len(dep["items"]), dep["more"]), (mp.LEVER_ITEMS, 14 - mp.LEVER_ITEMS))


class TestWarnings(unittest.TestCase):
    def view(self, *flags, **counts_over):
        return mp.warnings_view(mv_fixture(counts=counts(**counts_over), data_quality=list(flags)))

    def test_each_flag_is_worded_for_the_reader(self):
        (rise,) = self.view({"kind": "outlier", "key": "gh_vuln_critical"})
        self.assertEqual(rise["title"], "Dependabot critical rose 254.5% (44 → 156)")
        (fewer,) = self.view({"kind": "inventory", "key": "ecr_covered"})
        self.assertEqual(fewer["title"], "34% fewer images scanned (382 → 254)")
        self.assertIn("without any image changing", fewer["body"])
        self.assertNotIn("Why it moved", fewer["body"])  # the note may not exist; the flag must stand alone
        (more,) = self.view({"kind": "inventory", "key": "ecr_covered"}, ecr_covered=("ECR images covered", False, 200, 300))
        self.assertTrue(more["title"].startswith("50% more images scanned"))
        self.assertEqual(more["body"], fewer["body"])  # the cause is the note's to say, either way
        (gone,) = self.view({"kind": "not_comparable", "key": "gh_vuln_critical"})
        self.assertEqual(gone["title"], "Dependabot critical is missing from one snapshot")
        (cap,) = self.view({"kind": "capture_status", "key": "node_os", "note": "node_os: failed: AccessDenied."})
        self.assertIn("node_os", cap["title"])
        self.assertIn("left out, not shown as zero", cap["body"])

    def test_a_rise_from_zero_has_no_percentage(self):
        (w,) = self.view({"kind": "outlier", "key": "gh_vuln_critical"}, gh_vuln_critical=("Dependabot critical", True, 0, 9))
        self.assertEqual(w["title"], "Dependabot critical rose from 0 (0 → 9)")


def fence(kind, body):
    return f"```{kind}\n{json.dumps(body)}\n```"


class TestNote(unittest.TestCase):
    ALLOW = staticmethod(mp.link_policy("acme-org", "eu-west-2"))

    def note(self, *parts, lead="**Fell 75%.**"):
        return mp.note_view("## Why it moved\n\n" + lead + "\n\n" + "\n\n".join(parts), self.ALLOW)

    def test_lead_then_blocks_in_the_order_written(self):
        n = self.note("### Slim images", fence("stat", {"value": "−54k", "label": "removed", "tone": "fix"}),
                      "Their final stage is slim.", fence("callout", {"title": "Gap", "tone": "gap", "body": "33 **images**."}))
        self.assertEqual(n["lead"], "<strong>Fell 75%.</strong>")
        self.assertEqual([b["type"] for b in n["blocks"]], ["html", "stat", "html", "callout"])
        self.assertEqual(n["blocks"][0]["html"], '<h3 id="mv-s-slim-images">Slim images</h3>')  # a note's ### is a section
        self.assertEqual(n["blocks"][1], {"type": "stat", "value": "−54k", "label": "removed", "sub": None, "tone": "fix", "link": None})
        self.assertEqual(n["blocks"][3]["html"], "<p>33 <strong>images</strong>.</p>")

    def test_the_lead_ends_at_a_heading_list_or_table_without_a_blank_line(self):
        for after, kind in (("### Kernel headers\nThey left.", "<h3"), ("- a bullet", "<ul>"), ("| a | b |\n|---|---|\n| 1 | 2 |", "<table")):
            with self.subTest(after=after):
                n = mp.note_view("Fell 75%.\n" + after, self.ALLOW)
                self.assertEqual(n["lead"], "Fell 75%.")
                self.assertTrue(n["blocks"][0]["html"].startswith(kind), n["blocks"][0]["html"])

    def test_a_lead_over_several_lines_is_one_sentence(self):
        self.assertEqual(mp.note_view("Fell 75%,\nmostly remediation.\n\nMore.", self.ALLOW)["lead"], "Fell 75%, mostly remediation.")

    def test_a_line_starting_with_a_hash_number_stays_in_the_lead(self):
        n = mp.note_view("Fell 40%, mostly the base image bump in\n#482 and the follow-up.", self.ALLOW)
        self.assertEqual(n["lead"], "Fell 40%, mostly the base image bump in #482 and the follow-up.")
        self.assertEqual(n["blocks"], [])

    def test_a_comment_over_several_lines_is_never_shown(self):
        n = mp.note_view("<!--\nauthor note\n-->\nFell 75%.\n\nBody.\n\n<!--\nsecret draft\n-->\n\nMore.", self.ALLOW)
        self.assertEqual(n["lead"], "Fell 75%.")
        self.assertNotIn("author", json.dumps(n))
        self.assertNotIn("secret", json.dumps(n))
        self.assertNotIn("--&gt;", json.dumps(n))
        out = mp.md_to_html("a\n<!-- secret\ndraft -->\nb")
        self.assertNotIn("draft", out)  # the comment's later lines are what leaked
        self.assertEqual(out, "<p>a</p>\n<p>b</p>")

    def test_a_note_that_is_only_a_comment_is_no_note(self):
        self.assertIsNone(mp.note_view("<!-- to do: write this -->", self.ALLOW))
        self.assertIsNone(mp.note_view("## Why it moved\n\n<!-- to do -->", self.ALLOW))
        self.assertIsNone(mp.note_view("## Why it moved\n", self.ALLOW))

    def test_a_comment_marker_inside_a_block_is_data(self):
        n = self.note(fence("stat", {"value": "1", "label": "a <!-- b"}), "Prose.",
                      fence("stat", {"value": "2", "label": "c --> d"}))
        self.assertEqual([(b["type"], b.get("label")) for b in n["blocks"]],
                         [("stat", "a <!-- b"), ("html", None), ("stat", "c --> d")])

    def test_a_comment_hides_a_block_written_inside_it(self):
        n = mp.note_view("Fell.\n\n<!--\n" + fence("stat", {"value": "1", "label": "hidden"}) + "\n-->\n\nAfter.", self.ALLOW)
        self.assertEqual(n["blocks"], [{"type": "html", "html": "<p>After.</p>"}])

    def test_an_unclosed_comment_hides_no_block(self):
        n = mp.note_view("Fell.\n\n<!-- never closed\n\n" + fence("stat", {"value": "1", "label": "kept"}), self.ALLOW)
        self.assertEqual([b.get("label") for b in n["blocks"] if b["type"] == "stat"], ["kept"])
        self.assertEqual(n["blocks"][0], {"type": "error", "message": "a comment is never closed with -->"})

    def test_the_lead_ends_where_the_markdown_starts_something_else(self):
        cases = {"Fell.\n### \nMore.": ("Fell.", "<p>More.</p>"),        # an empty heading shows nothing
                 "Fell.\n#\nMore.": ("Fell.", "<p>More.</p>"),
                 "Fell.\n| not a table\nMore.": ("Fell.", "<p>| not a table</p>\n<p>More.</p>")}
        for md, (lead, html) in cases.items():
            with self.subTest(md=md):
                n = mp.note_view(md, self.ALLOW)
                self.assertEqual((n["lead"], n["blocks"][0]["html"]), (lead, html))

    def test_a_pipe_line_is_a_table_only_with_a_separator_row(self):
        self.assertEqual(mp.md_to_html("| a | b |\n| x |", shift=0), "<p>| a | b | | x |</p>")
        self.assertIn("<table>", mp.md_to_html("| a |\n|---|\n| 1 |", shift=0))

    def test_negative_zero_is_zero(self):
        n = self.note(fence("stat", {"value": -0.0, "label": "x"}), fence("bar", {"title": "t", "series": ["a"], "rows": [["a", -0.0]]}))
        self.assertEqual(n["blocks"][0]["value"], "0.0")
        self.assertEqual(str(n["blocks"][1]["rows"][0][1]), "0.0")

    def test_a_longer_fence_line_inside_a_block_is_its_content(self):
        n = self.note("```stat\n" + json.dumps({"value": "1", "label": "x"}) + "\n~~~~\n```", "After.")
        self.assertEqual([b["type"] for b in n["blocks"]], ["error", "html"])  # one error: the JSON, not a second block
        self.assertIn("not valid JSON", n["blocks"][0]["message"])
        n = self.note("````stat\n" + json.dumps({"value": "1", "label": "x"}) + "\n```\n````", "After.")
        self.assertEqual([b["type"] for b in n["blocks"]], ["error", "html"])  # ``` does not close ````

    def test_a_comment_before_the_lead_is_not_shown_as_the_lead(self):
        n = mp.note_view("<!-- draft: check counts -->\nFell 75%.\n\nMore.", self.ALLOW)
        self.assertEqual(n["lead"], "Fell 75%.")
        self.assertNotIn("draft", json.dumps(n))

    def test_each_block_type_validates_into_its_fields(self):
        bar = {"title": "Per repo", "unit": "critical + high", "series": ["7 Oct", "21 Oct"],
               "rows": [["svc-01", 15234, 20], ["svc-02", 14280, 36.5]]}
        line = {"title": "Trend", "series": ["C"], "points": [["Sep", 1], ["Oct", 2]]}
        n = self.note(fence("bar", bar), fence("line", line), fence("stat", {"value": 1234567, "label": "n"}),
                      fence("callout", {"title": "t", "body": "b"}))
        b, l, s, c = n["blocks"]
        self.assertEqual((b["series"], b["rows"], b["unit"], b["tone"]), (bar["series"], bar["rows"], "critical + high", None))
        self.assertEqual((l["series"], l["points"], l["unit"]), (["C"], [["Sep", 1], ["Oct", 2]], None))
        self.assertEqual(s["value"], "1,234,567")  # a number is formatted for display
        self.assertEqual(c["tone"], "info")       # a callout's default tone

    def test_a_bad_block_becomes_an_error_with_its_reason_and_the_rest_survive(self):
        cases = [
            (fence("pie", {}), "unknown block type 'pie'"),
            ("```stat\n{not json\n```", "not valid JSON"),
            (fence("stat", [1]), "must be a JSON object"),
            (fence("stat", {"value": True, "label": "x"}), "'value' must be text or a number"),
            (fence("stat", {"value": "1", "label": ""}), "'label' must be text"),
            (fence("stat", {"value": "x" * 25, "label": "y"}), "'value' is longer than 24"),
            (fence("stat", {"value": "1", "label": "y", "tone": "pink"}), "'tone' must be one of"),
            (fence("bar", {"title": "t", "series": [], "rows": [["a", 1]]}), "'series' must list 1 to 4"),
            (fence("bar", {"title": "t", "series": ["a", "b"], "rows": [["a", 1]]}), "rows[0] must be [label, 2 value(s)]"),
            (fence("bar", {"title": "t", "series": ["a"], "rows": [["a", "1"]]}), "rows[0] must be a number"),
            (fence("bar", {"title": "t", "series": ["a"], "rows": [["a", True]]}), "rows[0] must be a number"),
            (fence("bar", {"title": "t", "series": ["a"], "rows": [["a", 1]] * 21}), "'rows' must have 1 to 20"),
            (fence("line", {"title": "t", "series": ["a"], "points": [["a", 1]]}), "'points' must have 2 to 60"),
            (fence("callout", {"title": "t", "body": 5}), "'body' must be text"),
            ('```stat\n{"value": NaN, "label": "x"}\n```', "value must be a number"),
            ('```stat\n{"value": 1e400, "label": "x"}\n```', "value must be a number"),
            (fence("bar", {"title": "t", "series": ["a"], "rows": [["a", 10 ** 400]]}), "rows[0] must be a number"),  # ∞ in the browser
            ('```stat\n{"value": ' + "9" * 5000 + ', "label": "x"}\n```', "a number with too many digits"),
            ("```bar\n" + "[" * 10 ** 6 + "]" * 10 ** 6 + "\n```", "nested too deeply"),
        ]
        for block, reason in cases:
            n = self.note(block, "After.")
            err, after = n["blocks"]
            self.assertEqual(err["type"], "error", block)
            self.assertIn(reason, err["message"], block)
            self.assertEqual(after["html"], "<p>After.</p>")

    def test_non_finite_numbers_are_refused(self):
        n = mp.note_view('Lead.\n\n```bar\n{"title": "t", "series": ["a"], "rows": [["a", NaN]]}\n```')
        self.assertEqual(n["blocks"][0]["type"], "error")

    def test_an_unclosed_block_is_an_error_not_a_swallowed_note(self):
        n = self.note('```stat\n{"value": "1", "label": "x"}', "More text.")
        self.assertEqual([b["type"] for b in n["blocks"]], ["error"])
        self.assertIn("never closed", n["blocks"][0]["message"])

    def test_a_mistyped_fence_is_an_error_not_prose(self):
        body = json.dumps({"value": "1", "label": "x"})
        for opener, reason in (("```Stat", "unknown block type 'Stat'"), ("```bar2", "unknown block type 'bar2'"),
                               ("```", "needs a type")):
            with self.subTest(opener=opener):
                n = self.note(f"{opener}\n{body}\n```", "After.")
                self.assertEqual([b["type"] for b in n["blocks"]], ["error", "html"])
                self.assertIn(reason, n["blocks"][0]["message"])

    def test_a_longer_closing_fence_closes_the_block(self):
        n = self.note('```stat\n{"value": "1", "label": "x"}\n````', "After.")
        self.assertEqual([b["type"] for b in n["blocks"]], ["stat", "html"])

    def test_closing_hashes_are_not_part_of_a_heading(self):
        n = self.note(fence("stat", {"value": "1", "label": "x", "link": "Slim"}), "### Slim ###", "Text.")
        self.assertEqual(n["blocks"][0].get("target"), "mv-s-slim")
        self.assertIn('<h3 id="mv-s-slim">Slim</h3>', n["blocks"][1]["html"])
        self.assertIn("<h3>C# rules</h3>", mp.md_to_html("### C# rules", shift=0))  # a # inside the text stays

    def test_a_tilde_fence_is_a_block(self):
        n = self.note('~~~stat\n{"value": "1", "label": "x"}\n~~~')
        self.assertEqual([b["type"] for b in n["blocks"]], ["stat"])

    def test_an_unclosed_block_does_not_swallow_the_next_one(self):
        n = self.note('```stat\n{"value": "1", "label": "x"}', fence("stat", {"value": "2", "label": "y"}), "After.")
        self.assertEqual([b["type"] for b in n["blocks"]], ["error", "stat", "html"])
        self.assertIn("never closed", n["blocks"][0]["message"])
        self.assertEqual(n["blocks"][1]["value"], "2")

    def test_block_text_stays_raw_for_the_page_to_escape(self):
        n = self.note(fence("stat", {"value": "<b>1</b>", "label": "<i>x</i>"}),
                      fence("bar", {"title": "<t>", "series": ["<s>"], "rows": [["<r>", 1]]}))
        s, b = n["blocks"]
        self.assertEqual((s["value"], s["label"]), ("<b>1</b>", "<i>x</i>"))  # escaped by esc() in the page
        self.assertEqual((b["title"], b["series"], b["rows"][0][0]), ("<t>", ["<s>"], "<r>"))  # canvas text

    def test_prose_and_callout_bodies_cannot_inject_markup(self):
        n = self.note("<script>x</script> [a](javascript:alert(1))",
                      fence("callout", {"title": "t", "body": "<img src=x onerror=1> [b](https://evil.example)"}),
                      lead="<b>lead</b>")
        out = n["lead"] + "".join(b.get("html", "") for b in n["blocks"])
        self.assertNotRegex(out, r"<(script|img|b)\b")
        self.assertNotIn("href", out)

    def test_an_old_note_without_blocks_still_renders(self):
        n = mp.note_view("## Why it moved\n\n**Lead.**\n\n- one\n- two\n\nMore.", self.ALLOW)
        self.assertEqual(n["lead"], "<strong>Lead.</strong>")
        self.assertEqual([b["type"] for b in n["blocks"]], ["html"])
        self.assertIn("<li>one</li>", n["blocks"][0]["html"])

    def test_a_note_that_opens_with_a_heading_or_block_has_no_lead(self):
        self.assertEqual(mp.note_view("### H\n\nText.")["lead"], "")
        self.assertEqual(mp.note_view(fence("stat", {"value": "1", "label": "x"}) + "\n\nText.")["lead"], "")

    def test_the_stub_and_an_empty_note_are_no_note(self):
        self.assertIsNone(mp.note_view(WHY_STUB))
        self.assertIsNone(mp.note_view(""))

    def test_a_stat_links_to_a_section_heading_by_its_text(self):
        n = self.note(fence("stat", {"value": "≈54k", "label": "slim", "link": "four repos went **slim**"}),
                      fence("stat", {"value": "1", "label": "x"}),
                      "### Four repos went slim", "Text.", "### Four repos went slim", "Again.",
                      "### Four repos went slim", "Third.")
        linked, plain, prose = n["blocks"]
        self.assertEqual(linked["target"], "mv-s-four-repos-went-slim")  # case and markup ignored
        self.assertNotIn("target", plain)
        self.assertIn('<h3 id="mv-s-four-repos-went-slim">Four repos went slim</h3>', prose["html"])
        ids = re.findall(r'<h3 id="([^"]+)"', prose["html"])
        self.assertEqual(ids, ["mv-s-four-repos-went-slim", "mv-s-four-repos-went-slim-2", "mv-s-four-repos-went-slim-3"])

    def test_a_link_to_no_heading_is_an_error_naming_it(self):
        n = self.note(fence("stat", {"value": "1", "label": "x", "link": "Nowhere"}), "### Somewhere", "Text.")
        self.assertEqual(n["blocks"][0], {"type": "error", "message": "stat block: 'link' names no ### section heading: Nowhere"})

    def test_a_link_to_a_heading_at_another_level_is_an_error(self):
        # The page numbers ### sections only; a stat pointing elsewhere would show a number its section lacks.
        for heading in ("## Elsewhere", "#### Elsewhere"):
            with self.subTest(heading=heading):
                n = self.note(fence("stat", {"value": "1", "label": "x", "link": "Elsewhere"}), heading, "Text.")
                self.assertEqual(n["blocks"][0]["type"], "error")
                self.assertIn("names no ### section heading", n["blocks"][0]["message"])

    def test_a_second_stat_linking_the_same_section_is_an_error(self):
        n = self.note(fence("stat", {"value": "1", "label": "x", "link": "Slim"}),
                      fence("stat", {"value": "2", "label": "y", "link": "slim"}), "### Slim", "Text.")
        first, second = n["blocks"][:2]
        self.assertEqual(first["target"], "mv-s-slim")
        self.assertEqual(second["type"], "error")
        self.assertIn("already links to this section", second["message"])

    def test_section_ids_are_safe_whatever_the_heading_says(self):
        n = self.note('### <script>"x"</script> & é', "Text.")
        hid = re.search(r'<h3 id="([^"]*)">', n["blocks"][0]["html"]).group(1)
        self.assertRegex(hid, r"^mv-s-[a-z0-9-]+$")

    def test_the_style_guide_documents_every_block_and_tone(self):
        guide = (HERE.parent / "scripts" / "dashboard" / "STYLEGUIDE.md").read_text()
        for name in mp.BLOCK_TYPES + mp.TONES:
            self.assertIn(f"`{name}`", guide)


class TestLinks(unittest.TestCase):
    allow = staticmethod(mp.link_policy("acme-org", "eu-west-2"))

    def test_allowed_links(self):
        for url in ("https://github.com/acme-org/svc", "https://github.com/acme-org/svc/pull/48",
                    "https://github.com/orgs/acme-org/security/alerts/dependabot?q=x", "https://github.com/Acme-Org/svc",
                    "https://github.com/advisories?query=handlebars", "https://github.com/advisories/GHSA-1",
                    "https://github.com/pulls?q=org:acme-org",
                    "https://eu-west-2.console.aws.amazon.com/inspector/v2/home", "https://console.aws.amazon.com/ecr"):
            self.assertTrue(self.allow(url), url)

    def test_refused_links(self):
        for url in ("http://github.com/acme-org/svc", "https://github.com/other-org/svc", "https://github.com/acme-orgx/svc",
                    "https://evil.example/github.com/acme-org", "https://github.com.evil.example/acme-org/x",
                    "https://user@github.com/acme-org/x", "https://console.aws.amazon.com.evil.example/",
                    "https://a.b.console.aws.amazon.com/", "javascript:alert(1)", "https://github.com/acme-org"[:-1]):
            self.assertFalse(self.allow(url), url)
        self.assertFalse(mp.link_policy("")("https://github.com/x/y"))
        self.assertFalse(self.allow("https://github.com:0/acme-org/x"))  # any explicit port is refused

    def test_a_path_that_climbs_out_of_the_org_is_refused(self):
        # The browser resolves . and .. (and %2e%2e) before opening the link.
        for url in ("https://github.com/acme-org/../attacker/repo", "https://github.com/acme-org/%2e%2e/attacker/repo",
                    "https://github.com/acme-org/svc/%2E%2E/%2E%2E/x", "https://github.com/acme-org/./x",
                    "https://github.com/orgs/acme-org/../../x", "https://github.com/advisories/../attacker",
                    "https://github.com/acme-org/svc/%5c..%5cx", "https://github.com/advisoriesx/y"):
            self.assertFalse(self.allow(url), url)

    def test_a_malformed_port_is_refused_not_raised(self):
        # urlsplit parses it; only reading .port raises, which once failed the whole comparison.
        self.assertFalse(self.allow("https://github.com:x/acme-org/foo"))
        view = mp.note_view("Lead.\n\nSee [here](https://github.com:x/acme-org/foo).", self.allow)
        self.assertIn("here", view["blocks"][0]["html"])
        self.assertNotIn("href", view["blocks"][0]["html"])

    def test_a_refused_link_keeps_its_words(self):
        out = mp.md_to_html("See [the repo](https://evil.example/x) and [ours](https://github.com/acme-org/svc).", self.allow)
        self.assertEqual(out, '<p>See the repo and <a href="https://github.com/acme-org/svc" target="_blank" '
                              'rel="noopener noreferrer">ours</a>.</p>')

    def test_link_text_and_target_are_escaped(self):
        out = mp.md_to_html('[<b>x</b>](https://github.com/acme-org/a"onmouseover="1)', self.allow)
        self.assertNotIn("<b>", out)
        self.assertNotIn('"onmouseover', out)

    def test_without_a_policy_no_link_is_kept(self):
        self.assertEqual(mp.md_to_html("[a](https://github.com/acme-org/x)"), "<p>a</p>")

    def test_bold_and_code_still_work_around_links(self):
        out = mp.md_to_html("**[a](https://github.com/acme-org/x)** and `[b](https://x)`", self.allow)
        self.assertIn('<strong><a href="https://github.com/acme-org/x"', out)
        self.assertIn("<code>[b](https://x)</code>", out)


class TestMarkdownToHtml(unittest.TestCase):
    def test_tables_lists_headings_and_inline(self):
        out = mp.md_to_html("## Data quality\n\n- **outlier**: x rose.\n\n### Sub\n\n| Metric | Previous |\n|---|---|\n"
                            "| **Inspector** | 1 |")
        self.assertIn("<h4>Data quality</h4>", out)
        self.assertIn("<h5>Sub</h5>", out)
        self.assertIn("<ul><li><strong>outlier</strong>: x rose.</li></ul>", out)
        self.assertIn("<thead><tr><th>Metric</th><th>Previous</th></tr></thead>", out)
        self.assertIn("<td><strong>Inspector</strong></td><td>1</td>", out)
        self.assertNotIn("---", out)

    def test_scanner_text_is_escaped_and_cell_escapes_undone(self):
        out = mp.md_to_html("| Repository | Note |\n|---|---|\n| a\\|b | `<img src=x>` &lt;!-- forged |")
        self.assertIn("<td>a|b</td>", out)
        self.assertIn("<code>&lt;img src=x&gt;</code>", out)
        self.assertIn("&lt;!-- forged", out)
        self.assertNotIn("<img", out)
        self.assertNotIn("<!--", out)

    def test_a_written_note_cannot_inject_markup(self):
        out = mp.md_to_html('<script>alert(1)</script> **<i onmouseover="x">b</i>** `a` and `b')
        self.assertNotRegex(out, r"<(script|i)\b")
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("<strong>&lt;i onmouseover=&quot;x&quot;&gt;b&lt;/i&gt;</strong>", out)
        self.assertIn("<code>a</code> and `b", out)

    def test_blocks_keep_their_order(self):
        self.assertEqual(mp.md_to_html("- a\n- b\nAfter the list."), "<ul><li>a</li><li>b</li></ul>\n<p>After the list.</p>")
        self.assertEqual(mp.md_to_html("| h |\n|---|\n| c |\nAfter."),
                         "<table><thead><tr><th>h</th></tr></thead><tbody><tr><td>c</td></tr></tbody></table>\n<p>After.</p>")
        self.assertEqual(mp.md_to_html("Before.\n## H"), "<p>Before.</p>\n<h4>H</h4>")
        self.assertEqual(mp.md_to_html("Before.\n- a"), "<p>Before.</p>\n<ul><li>a</li></ul>")

    def test_headings_and_table_headers_are_escaped(self):
        out = mp.md_to_html("## <b>x</b>\n\n| <i>h</i> |\n|---|\n| c |")
        self.assertIn("<h4>&lt;b&gt;x&lt;/b&gt;</h4>", out)
        self.assertIn("<th>&lt;i&gt;h&lt;/i&gt;</th>", out)

    def test_list_continuation_lines_join_their_item(self):
        self.assertEqual(mp.md_to_html("- one\n  more\n- two"), "<ul><li>one more</li><li>two</li></ul>")


class TestBuildMoved(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(FIXTURES, self.root, dirs_exist_ok=True)

    def test_newest_is_full_and_older_is_headline(self):
        # A third, later snapshot: 20261007 becomes "older".
        shutil.copytree(self.root / "20261007", self.root / "20261021")
        with mock.patch("sys.stdout"):
            moved = mp.build_moved(self.root, ["20261021", "20261007", "20260923"])
        self.assertEqual(sorted(moved), ["20261007", "20261021"])
        self.assertEqual([e["detail"] for e in moved["20261021"]], ["full"])
        self.assertEqual([e["detail"] for e in moved["20261007"]], ["headline"])
        self.assertNotIn("levers", moved["20261007"][0]["view"])
        self.assertIn("levers", moved["20261021"][0]["view"])

    def test_both_bases_when_a_30_day_basis_exists(self):
        # 30 Oct: previous is 21 Oct; the newest at least 30 days earlier is 23 Sep.
        for d in ("20261021", "20261030"):
            shutil.copytree(self.root / "20261007", self.root / d)
        with mock.patch("sys.stdout"):
            moved = mp.build_moved(self.root, ["20261030", "20261021", "20261007", "20260923"])
        self.assertEqual([e["on_disk"] for e in moved["20261030"]], [False, False])
        (self.root / "20261030" / "movement.md").write_text("x\n")
        with mock.patch("sys.stdout"):
            self.assertEqual([e["on_disk"] for e in mp.build_moved(self.root, ["20261030"])["20261030"]], [True, False])
        self.assertEqual([(e["basis"], e["kind"], e["file"]) for e in moved["20261030"]],
                         [("20261021", "previous", "movement.md"), ("20260923", "30-day", "movement-vs-20260923.md")])
        self.assertEqual({e["detail"] for e in moved["20261030"]}, {"full"})

    def test_the_note_comes_from_the_pairs_own_file(self):
        (self.root / "20261007" / "movement.md").write_text(f"x\n{GENERATED_MARKER}\n\n## Why it moved\n\nOwn note.\n")
        with mock.patch("sys.stdout"):
            (e,) = mp.build_moved(self.root, ["20261007"], "acme-org")["20261007"]
        self.assertEqual(e["view"]["note"]["lead"], "Own note.")

    def test_each_basis_reads_its_own_note(self):
        # Both pairs at once: a page that read movement.md for every pair would pass the test above.
        for d in ("20261021", "20261030"):
            shutil.copytree(self.root / "20261007", self.root / d)
        for fname, text in (("movement.md", "Previous note."), ("movement-vs-20260923.md", "Thirty-day note.")):
            (self.root / "20261030" / fname).write_text(f"x\n{GENERATED_MARKER}\n\n## Why it moved\n\n{text}\n")
        with mock.patch("sys.stdout"):
            prev, month = mp.build_moved(self.root, ["20261030"], "acme-org")["20261030"]
        self.assertEqual((prev["kind"], prev["view"]["note"]["lead"]), ("previous", "Previous note."))
        self.assertEqual((month["kind"], month["view"]["note"]["lead"]), ("30-day", "Thirty-day note."))

    def test_one_failed_pair_does_not_cost_the_others(self):
        shutil.copytree(self.root / "20261007", self.root / "20261021")
        real = mp.security_movement

        def flaky(prev, curr, prev_date, curr_date):
            if curr_date == "20261007":
                raise KeyError("layers")
            return real(prev, curr, prev_date, curr_date)
        with mock.patch.object(mp, "security_movement", flaky), mock.patch("sys.stdout"):
            moved = mp.build_moved(self.root, ["20261021", "20261007", "20260923"])
        self.assertEqual(moved["20261007"][0]["error"], "KeyError")
        self.assertNotIn("view", moved["20261007"][0])
        self.assertIn("view", moved["20261021"][0])

    def test_dates_not_on_the_page_are_skipped(self):
        with mock.patch("sys.stdout"):
            self.assertEqual(mp.build_moved(self.root, ["20260923"]), {})


class TestTrendSeries(unittest.TestCase):
    def test_each_point_carries_inspector_critical_plus_high(self):
        # The What moved trend reads insp_ch; the page adds nothing itself.
        (pt,) = bd.build_trend_series({"20261021": {"inspector": {"critical": 7, "high": 30}}})
        self.assertEqual((pt["insp_crit"], pt["insp_high"], pt["insp_ch"]), (7, 30, 37))


def template_hazards(js):
    """Places inside a template literal (outside ${...}) where Apps Script's parser goes wrong."""
    out, i, stack, n = [], 0, [], len(js)  # stack: "`" in a template, "{" in code or ${...}
    while i < n:
        c, top = js[i], (stack[-1] if stack else None)
        if top == "`":
            if c == "\\":
                i += 2
                continue
            if c == "`":
                stack.pop()
            elif js.startswith("${", i):
                stack.append("{")
                i += 1
            elif js.startswith("//", i):
                out.append(js[max(0, i - 20):i + 20])
            i += 1
            continue
        if js.startswith("//", i) or js.startswith("/*", i):
            end = js.find("\n" if js[i + 1] == "/" else "*/", i + 2)
            i = n if end < 0 else end + (1 if js[i + 1] == "/" else 2)
            continue
        if c in "'\"":
            j = i + 1
            while j < n and js[j] != c and js[j] != "\n":
                j += 2 if js[j] == "\\" else 1
            i = j + 1
            continue
        if c == "`":
            stack.append("`")
        elif c == "{":
            stack.append("{")
        elif c == "}" and stack:
            stack.pop()
            if stack and stack[-1] == "`" and js.startswith("/", i + 1):
                out.append(js[max(0, i - 20):i + 20])
        i += 1
    return out


class TestPageJs(unittest.TestCase):
    def test_no_template_literal_apps_script_misreads(self):
        # Apps Script's server parser reads // inside a template literal as a comment, and a /
        # straight after ${...} as a regex; the page it serves then stops running. Locally the
        # page works, so only this catches it.
        self.assertEqual(template_hazards(bd.page_js()), [])

    def test_the_hazard_scanner_tells_a_template_from_the_code_around_it(self):
        self.assertEqual(len(template_hazards("const u = `https://${h}`;")), 1)
        self.assertEqual(len(template_hazards("const u = `${a}/${b}`;")), 1)
        self.assertEqual(len(template_hazards("const u = `${a}/x`;")), 1)
        self.assertEqual(template_hazards("const t = `${a} b`;  // a comment after it"), [])
        self.assertEqual(template_hazards("// a comment that quotes `https://x`\n/* and `https://y` */ const a = 1;"), [])
        self.assertEqual(template_hazards("const u = 'https://x/' + a + '/y';  // `quoted`"), [])
        self.assertEqual(template_hazards("const h = `<p>${a}</p>`; const r = /x\\//g;"), [])

    def test_files_inline_in_build_order(self):
        js = bd.page_js()
        order = [js.index(s) for s in ("function slugToDate", "function renderAll", "function movedPanelHtml",
                                       "updateSnapDisplay();\nrenderAll();")]
        self.assertEqual(order, sorted(order))

    def test_a_file_that_closes_the_script_block_stops_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in bd.JS_FILES:
                (Path(tmp) / name).write_text("// ok\n")
            (Path(tmp) / "moved.js").write_text("const s = '</SCRIPT>';\n")
            with self.assertRaises(ValueError):
                bd.page_js(Path(tmp))


if __name__ == "__main__":
    unittest.main()
