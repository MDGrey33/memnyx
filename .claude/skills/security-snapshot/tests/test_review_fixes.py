"""Tests for the fixes from the review of the audit-fix commits, and the dashboard
hardening: optional aggregations, missing layer data, capture flags, escaping,
version parsing, fixture trimming."""
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixture_mask as fm  # noqa: E402
import levers as lv  # noqa: E402
import movement as mv  # noqa: E402
import movement_markdown as md  # noqa: E402

with mock.patch("config_util.load_config", return_value={"aws_profile": "p", "aws_region": "r", "github_org": "o"}):
    import posture_snapshot as ps  # noqa: E402
    import build_dashboard as bd  # noqa: E402

from test_audit_fixes import Raises  # noqa: E402


class TestOptionalAggregations(unittest.TestCase):
    def test_optional_section_degrades_on_a_transport_error(self):
        self.assertEqual(ps.paginate_aggregations(Raises(), "AMI", {}, required=False), [])

    def test_required_section_still_stops_the_run(self):
        with self.assertRaises(SystemExit):
            ps.paginate_aggregations(Raises(), "ACCOUNT", {})


class TestMissingLayerData(unittest.TestCase):
    def test_failed_layer_capture_gives_no_lever(self):
        self.assertIsNone(lv.base_layers({"raw": {"layers": None, "base_layers": []}}, None))
        old = {"raw": {"base_layers": [{"layer": "L1", "c": 1, "h": 1, "images": 2, "repo_list": ["a", "b"]}]}}
        self.assertEqual(lv.base_layers(old, None)["removes_ch"], 2)


class TestCaptureFlags(unittest.TestCase):
    def test_every_failed_capture_is_flagged(self):
        raw = {n: {"status": "failed: AccessDenied"} for n in ("node_scan", "node_os", "package_breakdown")}
        raw["package_managers_stats"] = {"failed": 3}
        keys = [f["key"] for f in mv.data_quality({}, {"raw": raw}, []) if f["kind"] == "capture_status"]
        self.assertEqual(keys, ["package_breakdown", "node_scan", "node_os", "package_managers"])
        self.assertEqual(mv.data_quality({}, {"raw": {"package_managers_stats": {"failed": 0}}}, []), [])


class TestCellEscaping(unittest.TestCase):
    def test_a_backslash_before_a_pipe_cannot_reopen_the_cell(self):
        cell = md._cell("a \\| b")
        # every pipe must be preceded by an odd number of backslashes to stay escaped
        for m in re.finditer(r"(\\*)\|", cell):
            self.assertEqual(len(m.group(1)) % 2, 1, cell)


class TestVersionParsing(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(ps._version("v1.67.0"), (1, 67, 0))
        self.assertIsNone(ps._version("1.67.0-beta"))
        self.assertIsNone(ps._version(""))
        self.assertIs(ps._on_latest("1.66.0", "v1.67.0"), False)
        self.assertIsNone(ps._on_latest("1.66.0", "latest"))


class TestTrimGuards(unittest.TestCase):
    def test_bad_counts_and_missing_detail_are_refused(self):
        s = {"20260101": {"github-raw.json": {"vuln_alerts_detail": [{"repo": "a"}, {"repo": None}]}}}
        for n in (0, -2):
            with self.assertRaises(ValueError):
                fm.trim_alert_detail(s, n)
        with self.assertRaises(ValueError):
            fm.trim_alert_detail({"20260101": {"raw.json": {}}}, 3)
        out = fm.trim_alert_detail(s, 5)
        self.assertEqual(out["20260101"]["github-raw.json"]["vuln_alerts_detail"], [{"repo": "a"}])


class TestRegionMasking(unittest.TestCase):
    def test_region_is_masked_and_leak_checked(self):
        s = {"20260101": {"raw.json": {"region": "eu-west-9", "account": "999988887777"}}}
        masked, aliases = fm.mask_set(s)
        self.assertEqual(masked["20260101"]["raw.json"]["region"], fm.FAKE_REGION)
        leaky = {"20260101": {"raw.json": {"region": fm.FAKE_REGION, "packages": [], "generated_at": "eu-west-9"}}}
        self.assertTrue(fm.find_leaks(leaky, aliases))


class TestDashboardEmbedding(unittest.TestCase):
    def test_script_data_cannot_close_the_script_block(self):
        out = bd.js_literal({"pkg": "</script><img src=x onerror=alert(1)>", "amp": "a&b"})
        self.assertNotIn("<", out)
        self.assertEqual(json.loads(out), {"pkg": "</script><img src=x onerror=alert(1)>", "amp": "a&b"})

    def test_inserted_data_is_not_scanned_for_placeholders(self):
        out = bd.fill_placeholders("A=__A__ B=__B__", {"__A__": "has __B__ inside", "__B__": "b"})
        self.assertEqual(out, "A=has __B__ inside B=b")

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_page_escapes_names_before_innerhtml(self):
        js = bd.page_js()
        esc_src = "\n".join(l for l in js.splitlines() if l.startswith(("const ESC", "const esc")))
        probe = esc_src + "\nprocess.stdout.write(esc('<img src=x onerror=\"alert(1)\">&\\''))"
        out = subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout
        self.assertEqual(out, "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;&#39;")
        for sink in ("${esc(r.repo)}", "${esc(l.title)}", "${esc(it.name)}", "${esc(b.value)}"):
            self.assertIn(sink, js)
        self.assertNotIn("${r.repo}", js)
        self.assertNotIn("${l.title}", js)


class Partial:
    """A paginated aggregation that fails on its second page."""

    def __init__(self):
        self.n = 0

    def list_finding_aggregations(self, **kw):
        self.n += 1
        if self.n > 1:
            raise ps.ClientError({"Error": {"Code": "ThrottlingException"}}, "ListFindingAggregations")
        return {"responses": [{"x": 1}], "nextToken": "t"}


class TestSecondReview(unittest.TestCase):
    def test_optional_aggregation_never_returns_a_partial_list(self):
        self.assertEqual(ps.paginate_aggregations(Partial(), "IMAGE_LAYER", {}, required=False), [])

    def test_versions_of_different_length_compare_as_releases(self):
        self.assertIs(ps._on_latest("1.51", "1.51.0"), True)
        self.assertIs(ps._on_latest("1.51.0", "1.51.1"), False)

    def test_first_run_is_not_a_capture_problem(self):
        raw = {"first_seen": {"status": "no_previous_snapshot"}, "rebuild_comparison": {"status": "no_previous_snapshot"}}
        self.assertEqual(mv.data_quality({}, {"raw": raw}, []), [])

    def test_failed_captures_are_not_described_as_an_old_snapshot(self):
        curr = {"raw": {"package_breakdown": {"status": "failed: AccessDenied", "rows": None}}}
        out = md.render_movement_markdown(mv.security_movement({"raw": {}}, curr, "a", "b"))
        self.assertIn("Not available: the captures behind them failed", out)
        self.assertNotIn("predates the lever capture", out)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pair-a"


class TestBuiltPage(unittest.TestCase):
    def test_page_builds_from_fixtures_with_every_placeholder_filled(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(FIXTURES, root, dirs_exist_ok=True)
            (root / "not-a-date").mkdir()
            (root / "not-a-date" / "snapshot.json").write_text("{}")
            with mock.patch("sys.stdout"):
                page = bd.build(root / "20261007" / "correlation.json", root)
        self.assertEqual(re.findall(r"__[A-Z_]+__", page), [])
        self.assertNotIn("not-a-date", page)
        script = page.split("<script>")[-1].split("</script>")[0]
        data = re.search(r"const SNAPSHOTS\s*=\s*(.*?);\nconst DATES", script, re.S).group(1)
        self.assertNotIn("<", data)
        if shutil.which("node"):
            subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0,'utf8'))"],
                           input=script, text=True, check=True)


if __name__ == "__main__":
    unittest.main()
