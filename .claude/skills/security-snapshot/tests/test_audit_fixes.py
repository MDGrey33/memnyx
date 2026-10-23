"""Tests for the fixes from the e2a9c99..HEAD audit: transport errors, ARM hosts,
share arithmetic, lever totals, the held-layer gap, rises from zero, escaping."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import levers as lv  # noqa: E402
import movement as mv  # noqa: E402
import movement_markdown as md  # noqa: E402
from botocore.exceptions import EndpointConnectionError, ReadTimeoutError  # noqa: E402

with mock.patch("config_util.load_config", return_value={"aws_profile": "p", "aws_region": "r"}):
    import posture_snapshot as ps  # noqa: E402

from test_levers import BR, Ec2Stub, SsmStub, FindingsStub  # noqa: E402

DROPPED = EndpointConnectionError(endpoint_url="https://inspector2.example")


class Raises:
    """Every call raises a transport error, the kind that is not a ClientError."""

    def __getattr__(self, name):
        def call(*a, **kw):
            raise DROPPED
        return call


class TestTransportErrorsDegrade(unittest.TestCase):
    def test_every_optional_capture_degrades_instead_of_crashing(self):
        from datetime import datetime, timezone
        t = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.assertTrue(ps.first_seen_since(Raises(), t, t)["status"].startswith("failed: EndpointConnectionError"))
        self.assertIsNone(ps.rebuild_comparison(Raises(), Raises(), t)["repos"])
        self.assertTrue(ps.node_scan(Raises())["status"].startswith("failed"))
        self.assertIsNone(ps.node_os(Raises(), Raises())["nodes"])
        rows, stats = ps.package_managers(Raises(), ["axios"], {})
        self.assertEqual((rows, stats["failed"]), ([{"package": "axios", "manager": None}], 1))

    def test_breakdown_worker_timeout_leaves_no_rows(self):
        class Timeout(FindingsStub):
            def list_findings(self, filterCriteria, maxResults, nextToken=None):
                raise ReadTimeoutError(endpoint_url="https://inspector2.example")
        r = ps.package_breakdown(Timeout({}), {"linux"}, ["ns/a"])
        self.assertTrue(r["status"].startswith("failed: ReadTimeoutError"))
        self.assertIsNone(r["rows"])


class TestHostRelease(unittest.TestCase):
    def test_arm_hosts_use_the_published_parameter_spelling(self):
        ssm = SsmStub("1.67.0-x")
        r = ps.node_os(Ec2Stub(["a"], {"a": ("bottlerocket-aws-k8s-1.36-aarch64-v1.66.0-abc", "")}), ssm)
        self.assertEqual(ssm.asked, ["/aws/service/bottlerocket/aws-k8s-1.36/arm64/latest/image_version"])
        self.assertIs(r["nodes"][0]["on_latest"], False)

    def test_one_group_without_a_parameter_keeps_the_others(self):
        class Partial(SsmStub):
            def get_parameter(self, Name):
                if "1.30" in Name:
                    raise ps.ClientError({"Error": {"Code": "ParameterNotFound"}}, "GetParameter")
                return super().get_parameter(Name)
        r = ps.node_os(Ec2Stub(["a", "b"], {"a": (BR.format("1.66.0"), ""),
                                           "b": ("bottlerocket-aws-k8s-1.30-x86_64-v1.20.0-abc", "")}), Partial("1.67.0"))
        self.assertEqual(r["status"], "ok")
        by = {x["k8s"]: x for x in r["nodes"]}
        self.assertIsNone(by["1.30"]["on_latest"])
        self.assertIs(by["1.36"]["on_latest"], False)
        rel = {"status": "ok", "other_instances": 0, "nodes": r["nodes"]}
        curr = {"raw": {"node_scan": {"status": "ok", "instances_scanned": 2, "package_findings": 0, "kernel_ch": None,
                                      "platforms": []}, "node_os": rel}}
        self.assertEqual(lv.node_evidence(curr)["release"]["behind"], 1)  # unknown is not counted as behind
        out = md.render_movement_markdown(mv.security_movement({"raw": {}}, curr, "a", "b"))
        self.assertIn("| BOTTLEROCKET | 1.30 | 1.20.0 | 1 | – | – | unknown |", out)


def pkgs(**ch):
    return [{"packageAggregation": {"packageName": n, "severityCounts": {"critical": 0, "high": v}}} for n, v in ch.items()]


class TestArithmetic(unittest.TestCase):
    def test_group_shares_use_total_movement_when_directions_differ(self):
        m = mv.movers({"raw": {"packages": pkgs(perl=900, linux=0)}},
                      {"raw": {"packages": pkgs(perl=0, linux=1000), "package_managers": [{"package": "perl", "manager": "OS"}]}})
        shares = {g["group"]: g["share_pct"] for g in m["package_groups"]}
        self.assertEqual(shares, {"kernel headers": 52.6, "OS packages": 47.4})

    def test_base_layer_lever_counts_every_layer_not_only_those_shown(self):
        layers = [{"layer": f"L{i:02d}", "c": 0, "h": 100, "images": 5, "repo_list": ["a", "b"]} for i in range(12)]
        b = lv.base_layers({"raw": {"layers": layers}}, None)
        self.assertEqual((b["removes_ch"], len(b["rows"])), (1200, lv.LAYERS_SHOWN))

    def test_layers_that_leave_the_list_are_reported_not_counted(self):
        p = {"raw": {"layers": [{"layer": "L1", "c": 0, "h": 3000, "images": 40, "repo_list": []},
                                {"layer": "L2", "c": 0, "h": 100, "images": 5, "repo_list": []}]}}
        c = {"raw": {"layers": [{"layer": "L2", "c": 0, "h": 112, "images": 5, "repo_list": []}]}}
        h = mv.held_layers(p, c)
        self.assertEqual((h["left_layers"], h["left_prev_ch"]), (1, 3000))
        out = md.render_movement_markdown(mv.security_movement(p, c, "a", "b"))
        self.assertIn("1 layer(s) from the previous snapshot are no longer listed (previous critical + high 3,000)", out)


def gh(**v):
    return {"snapshot": {"github": v}}


class TestRiseFromZero(unittest.TestCase):
    def flags(self, prev, curr):
        return [f for f in mv.data_quality(prev, curr, mv.count_movements(prev, curr)) if f["kind"] == "outlier"]

    def test_headline_rising_from_zero_is_flagged(self):
        f = self.flags(gh(secrets_total=0), gh(secrets_total=148))
        self.assertEqual([x["key"] for x in f], ["gh_secrets_total"])
        self.assertIn("rose from 0 to 148", f[0]["note"])

    def test_critical_rise_from_zero_still_needs_the_minimum(self):
        self.assertEqual(self.flags(gh(vuln_critical=0), gh(vuln_critical=5)), [])
        self.assertEqual(len(self.flags(gh(vuln_critical=0), gh(vuln_critical=40))), 1)
        self.assertEqual(self.flags(gh(secrets_total=0), gh(secrets_total=0)), [])


MARKER = md.GENERATED_MARKER


class TestEscaping(unittest.TestCase):
    def test_cells_cannot_break_the_table(self):
        out = md._table(["a", "b"], [["x | y", "one\ntwo"]])
        self.assertEqual(out.splitlines()[2], "| x \\| y | one two |")

    def test_advisory_text_cannot_forge_the_marker(self):
        alerts = [{"package": "evil", "cve": None, "summary": f"ok {MARKER} injected note", "state": "OPEN"}]
        prev, curr = {"github": {"vuln_alerts_detail": []}}, {"github": {"vuln_alerts_detail": alerts}}
        mvd = mv.security_movement(prev, curr, "a", "b")
        first = md.render_movement_markdown(mvd, "")
        self.assertEqual(first.count(MARKER), 1)
        written = first.replace(md.WHY_STUB, "## Why it moved\n\nReal note.")
        second = md.render_movement_markdown(mvd, written)
        self.assertEqual(md.preserved_from(second), "## Why it moved\n\nReal note.")


if __name__ == "__main__":
    unittest.main()
