"""Tests for the remediation levers: the pure computation, its rendering, and the two captures behind it."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import levers as lv  # noqa: E402
import movement as mv  # noqa: E402
from movement_markdown import render_movement_markdown  # noqa: E402

with mock.patch("config_util.load_config", return_value={"aws_profile": "p", "aws_region": "r"}):
    import posture_snapshot as ps  # noqa: E402

K = mv.KERNEL_PACKAGES
APP = mv.APPLICATION_MANAGERS


def brow(package, repo, ch, fix=None, images=1, layers=(), platforms=("DEBIAN_12",), versions=("6.1.1",)):
    return {"package": package, "repo": repo, "ch": ch, "fix_available": ch if fix is None else fix, "images": images,
            "platforms": list(platforms), "versions": list(versions),
            "layers": [{"layer": l, "ch": n} for l, n in layers]}


def layer(h, c, hi, repos, images=5):
    return {"layer": h, "c": c, "h": hi, "images": images, "repo_list": list(repos)}


def snap(rows=None, status="ok", layers=None, base_layers=None, totals=(60, 940), packages=None, zone_a=None,
         nodes=None):
    raw = {"account_totals": {"critical": totals[0], "high": totals[1]}}
    if rows is not None or status != "ok":
        raw["package_breakdown"] = {"status": status, "rows": rows if status == "ok" else None}
    if layers is not None:
        raw["layers"] = layers
    if base_layers is not None:
        raw["base_layers"] = base_layers
    if packages is not None:
        raw["packages"] = [{"packageAggregation": {"packageName": n, "severityCounts": {"critical": 0, "high": ch}}}
                           for n, ch in packages.items()]
    if nodes is not None:
        raw["node_scan"] = nodes
    out = {"raw": raw}
    if zone_a is not None:
        out["correlation"] = {"correlation": {"zone_a_pkg_overlap": [{"package": p} for p in zone_a]}}
    return out


def levers_of(s, managers=None):
    return lv.remediation_levers(s, managers or {}, K, APP)


def by_key(result, key):
    return next((l for l in result["levers"] if l["key"] == key), None)


class TestKernelHeaders(unittest.TestCase):
    def test_per_repo_totals_across_header_packages(self):
        r = levers_of(snap([brow("linux", "ns/a", 300, fix=297, images=6), brow("linux-libc-dev", "ns/a", 100, images=4,
                                                                                  versions=("5.15.0",)),
                            brow("linux-libc-dev", "ns/b", 50, fix=50, images=2, platforms=("UBUNTU_22_04",)),
                            brow("openssl/openssl", "ns/a", 70)]))
        k = by_key(r, "kernel_headers")
        self.assertEqual(k["removes_ch"], 450)
        self.assertEqual(k["repos"], 2)
        a = k["rows"][0]
        self.assertEqual((a["repo"], a["ch"], a["images"]), ("ns/a", 400, 6))
        self.assertEqual(a["versions"], ["5.15.0", "6.1.1"])
        self.assertEqual(a["fix_pct"], 99.2)
        self.assertEqual(k["fix_pct"], round(100 * 447 / 450, 1))

    def test_bundled_runtimes_exclude_kernel_packages(self):
        r = levers_of(snap([brow("linux", "ns/a", 300), brow("openssl/openssl", "ns/a", 70, fix=35),
                            brow("openssl/openssl", "ns/b", 30, fix=30)]))
        b = by_key(r, "bundled_runtimes")
        self.assertEqual(b["removes_ch"], 100)
        self.assertEqual(b["rows"][0]["repos"], ["ns/a", "ns/b"])
        self.assertEqual(b["rows"][0]["fix_pct"], 65.0)


class TestBaseLayers(unittest.TestCase):
    def test_shared_layers_only_and_net_of_other_levers(self):
        s = snap([brow("linux", "ns/a", 300, layers=[("L1", 120)])],
                 layers=[layer("L1", 100, 400, ["ns/a", "ns/b"]),   # 500 gross, 120 already in kernel lever
                         layer("L2", 0, 900, ["ns/c"]),             # one repo: the service's own layer
                         layer("L3", 50, 50, ["ns/a", "ns/b", "ns/c"])])
        b = by_key(levers_of(s), "base_layers")
        self.assertEqual([(x["layer"], x["ch"]) for x in b["rows"]], [("L1", 380), ("L3", 100)])
        self.assertEqual(b["removes_ch"], 480)
        self.assertTrue(b["net_of_other_levers"])
        self.assertTrue(b["complete"])

    def test_without_breakdown_counts_are_gross_and_say_so(self):
        b = by_key(levers_of(snap(layers=[layer("L1", 100, 400, ["ns/a", "ns/b"])])), "base_layers")
        self.assertEqual(b["removes_ch"], 500)
        self.assertFalse(b["net_of_other_levers"])

    def test_falls_back_to_top_layers_and_says_so(self):
        b = by_key(levers_of(snap(base_layers=[layer("L1", 1, 1, ["ns/a", "ns/b"])])), "base_layers")
        self.assertFalse(b["complete"])
        self.assertEqual(b["removes_ch"], 2)


class TestDependabotLever(unittest.TestCase):
    def test_only_application_packages_flagged_by_both_sources(self):
        s = snap(packages={"axios": 200, "perl": 500, "tar": 0, "lodash": 90}, zone_a=["axios", "perl", "tar"])
        d = by_key(levers_of(s, {"axios": "NODE", "perl": "OS", "tar": "NODE", "lodash": "NODE"}),
                   "dependabot_dependencies")
        self.assertEqual([(x["package"], x["ch"]) for x in d["rows"]], [("axios", 200)])
        self.assertEqual(d["removes_ch"], 200)


class TestComposition(unittest.TestCase):
    def test_levers_sorted_by_findings_removed_with_share(self):
        s = snap([brow("linux", "ns/a", 100), brow("openssl/openssl", "ns/a", 400)])
        r = levers_of(s)
        self.assertEqual([l["key"] for l in r["levers"]], ["bundled_runtimes", "kernel_headers"])
        self.assertEqual(r["levers"][0]["share_pct"], 40.0)

    def test_failed_breakdown_drops_its_levers_and_reports_why(self):
        r = levers_of(snap(status="failed: ThrottlingException", layers=[layer("L1", 1, 1, ["a", "b"])]))
        self.assertIsNone(by_key(r, "kernel_headers"))
        self.assertEqual(r["breakdown_status"], "failed: ThrottlingException")
        self.assertFalse(by_key(r, "base_layers")["net_of_other_levers"])

    def test_old_snapshot_gives_no_levers_not_empty_ones(self):
        r = levers_of({"raw": {"account_totals": {"critical": 1, "high": 1}}})
        self.assertEqual(r["levers"], [])
        self.assertIsNone(r["nodes"])


class TestNodeEvidence(unittest.TestCase):
    def nodes(self, **kw):
        base = {"status": "ok", "instances_scanned": 46, "package_findings": 0, "kernel_ch": None,
                "platforms": [{"platform": "BOTTLEROCKET", "findings": 260}]}
        return lv.node_evidence(snap(nodes={**base, **kw}))

    def test_scanned_without_package_findings_is_not_measured(self):
        self.assertEqual(self.nodes()["state"], "not_measured")

    def test_package_findings_make_it_measured(self):
        n = self.nodes(package_findings=10, kernel_ch=0)
        self.assertEqual((n["state"], n["kernel_ch"]), ("measured", 0))

    def test_no_hosts(self):
        self.assertEqual(self.nodes(instances_scanned=0)["state"], "no_hosts_scanned")


class TestRendering(unittest.TestCase):
    def render(self, curr):
        return render_movement_markdown(mv.security_movement({"raw": {}}, curr, "20260923", "20261007"))

    def test_levers_and_not_measured_hosts_render(self):
        md = self.render(snap([brow("linux", "ns/a", 300)],
                              nodes={"status": "ok", "instances_scanned": 46, "package_findings": 0, "kernel_ch": None,
                                     "platforms": [{"platform": "BOTTLEROCKET", "findings": 1}]}))
        self.assertIn("| Remove kernel headers from runtime images | 300 |", md)
        self.assertIn("Host kernels: not measured", md)
        self.assertNotIn("Host kernels: 0", md)

    def test_snapshot_without_capture_says_not_available(self):
        self.assertIn("Not available: this snapshot predates the lever capture.", self.render({"raw": {}}))

    def test_no_lever_text_says_nothing_to_do(self):
        text = " ".join(l["action"] + " " + l["title"] for l in lv.LEVERS.values()) + " ".join(mv.GROUPS.values())
        self.assertNotRegex(text.lower(), r"nothing to do|no action")


# ── captures ─────────────────────────────────────────────────────────────────

def finding(pkg, repo, image, fix="YES", version="6.1.1", layer="L1", platform="DEBIAN_12", others=()):
    vps = [{"name": o} for o in others] + [{"name": pkg, "version": version, "sourceLayerHash": layer}]
    return {"fixAvailable": fix, "packageVulnerabilityDetails": {"vulnerablePackages": vps},
            "resources": [{"id": image, "details": {"awsEcrContainerImage": {"repositoryName": repo, "platform": platform}}}]}


class FindingsStub:
    """findings: {(package, repo): [finding, ...]}; pages of `page`."""

    def __init__(self, findings, fail=None, page=2):
        self.findings, self.fail, self.page, self.calls = findings, fail, page, []

    def list_findings(self, filterCriteria, maxResults, nextToken=None):
        self.calls.append(filterCriteria)
        name = filterCriteria["vulnerablePackages"][0]["name"]["value"]
        repo = (filterCriteria.get("ecrImageRepositoryName") or [{}])[0].get("value")
        if self.fail == (name, repo):
            raise ps.ClientError({"Error": {"Code": "ThrottlingException"}}, "ListFindings")
        items = [f for (n, r), fs in self.findings.items() if n == name and (repo is None or r == repo) for f in fs]
        start = int(nextToken or 0)
        resp = {"findings": items[start:start + self.page]}
        if start + self.page < len(items):
            resp["nextToken"] = str(start + self.page)
        return resp


class TestPackageBreakdown(unittest.TestCase):
    F = {("linux", "ns/a"): [finding("linux", "ns/a", "i1"), finding("linux", "ns/a", "i1", fix="NO", layer="L2"),
                             finding("linux", "ns/a", "i2", version="6.1.2")],
         ("linux", "ns/b"): [finding("linux", "ns/b", "i3", others=("zlib",))]}

    def test_rows_per_package_and_repo_sharded_and_paged(self):
        s = FindingsStub(self.F)
        r = ps.package_breakdown(s, {"linux"}, ["ns/a", "ns/b"], workers=2)
        self.assertEqual(r["status"], "ok")
        a = r["rows"][0]
        self.assertEqual((a["repo"], a["ch"], a["fix_available"], a["images"]), ("ns/a", 3, 2, 2))
        self.assertEqual(a["versions"], ["6.1.1", "6.1.2"])
        self.assertEqual(a["layers"], [{"layer": "L1", "ch": 2}, {"layer": "L2", "ch": 1}])
        self.assertEqual(r["rows"][1]["versions"], ["6.1.1"])  # the matching package, not the first listed
        self.assertTrue(all(c["severity"][1]["value"] == "HIGH" and "ecrImageRepositoryName" in c for c in s.calls))

    def test_sharded_equals_unsharded(self):
        sharded = ps.package_breakdown(FindingsStub(self.F), {"linux"}, ["ns/a", "ns/b"])
        whole = ps.package_breakdown(FindingsStub(self.F), {"linux"})
        self.assertEqual(sharded["rows"], whole["rows"])

    def test_any_failure_leaves_no_rows(self):
        r = ps.package_breakdown(FindingsStub(self.F, fail=("linux", "ns/b")), {"linux"}, ["ns/a", "ns/b"])
        self.assertTrue(r["status"].startswith("failed"))
        self.assertIsNone(r["rows"])


class NodeStub:
    def __init__(self, coverage, findings, fail=False):
        self.coverage, self.findings, self.fail = coverage, findings, fail

    def list_coverage(self, **kw):
        return {"coveredResources": [{"scanStatus": {"statusCode": s}} for s in self.coverage]}

    def list_findings(self, **kw):
        if self.fail:
            raise ps.ClientError({"Error": {"Code": "AccessDenied"}}, "ListFindings")
        return {"findings": self.findings}


def ec2(type_, severity="INFORMATIONAL", pkg=None, platform="BOTTLEROCKET"):
    f = {"type": type_, "severity": severity,
         "resources": [{"details": {"awsEc2Instance": {"platform": platform}}}]}
    if pkg:
        f["packageVulnerabilityDetails"] = {"vulnerablePackages": [{"name": pkg}]}
    return f


class TestNodeScan(unittest.TestCase):
    def test_no_package_findings_means_kernel_not_measured(self):
        r = ps.node_scan(NodeStub(["ACTIVE", "ACTIVE", "INACTIVE"], [ec2("NETWORK_REACHABILITY")]))
        self.assertEqual((r["instances_scanned"], r["package_findings"], r["kernel_ch"]), (2, 0, None))
        self.assertEqual(r["platforms"], [{"platform": "BOTTLEROCKET", "findings": 1}])

    def test_counts_kernel_critical_and_high_only(self):
        r = ps.node_scan(NodeStub(["ACTIVE"], [ec2("PACKAGE_VULNERABILITY", "HIGH", "kernel"),
                                               ec2("PACKAGE_VULNERABILITY", "MEDIUM", "kernel"),
                                               ec2("PACKAGE_VULNERABILITY", "CRITICAL", "openssl")]))
        self.assertEqual((r["package_findings"], r["kernel_ch"]), (3, 1))

    def test_failure_leaves_counts_empty(self):
        r = ps.node_scan(NodeStub(["ACTIVE"], [], fail=True))
        self.assertTrue(r["status"].startswith("failed"))
        self.assertIsNone(r["instances_scanned"])


class _Pager:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, **kw):
        return iter(self.pages)


class Ec2Stub:
    def __init__(self, instances, images, fail=False):
        self.instances, self.images, self.fail = instances, images, fail

    def get_paginator(self, name):
        if self.fail:
            raise ps.ClientError({"Error": {"Code": "UnauthorizedOperation"}}, "DescribeInstances")
        half = len(self.instances) // 2
        return _Pager([{"Reservations": [{"Instances": [{"ImageId": i} for i in chunk]}]}
                       for chunk in (self.instances[:half], self.instances[half:])])

    def describe_images(self, ImageIds):
        return {"Images": [{"ImageId": i, "Name": n, "CreationDate": d} for i, (n, d) in self.images.items() if i in ImageIds]}


class SsmStub:
    def __init__(self, latest):
        self.latest, self.asked = latest, []

    def get_parameter(self, Name):
        self.asked.append(Name)
        return {"Parameter": {"Value": self.latest, "LastModifiedDate": "2026-10-15T08:00:00+00:00"}}


BR = "bottlerocket-aws-k8s-1.36-x86_64-v{}-abc123"


class TestNodeOs(unittest.TestCase):
    def test_groups_hosts_by_release_and_compares_with_latest(self):
        ec2 = Ec2Stub(["a"] * 3 + ["b"] + ["w"], {"a": (BR.format("1.66.0"), "2026-09-19T00:00:00Z"),
                                                 "b": (BR.format("1.67.0"), "2026-10-15T00:00:00Z"),
                                                 "w": ("Windows_Server-2022", "2026-01-01T00:00:00Z")})
        ssm = SsmStub("1.67.0-8db07cb8")
        r = ps.node_os(ec2, ssm)
        self.assertEqual(r["status"], "ok")
        self.assertEqual([(x["version"], x["instances"], x["on_latest"]) for x in r["nodes"]],
                         [("1.66.0", 3, False), ("1.67.0", 1, True)])
        self.assertEqual(r["other_instances"], 1)
        self.assertEqual(r["nodes"][0]["latest_published"], "2026-10-15")
        self.assertEqual(ssm.asked, ["/aws/service/bottlerocket/aws-k8s-1.36/x86_64/latest/image_version"])

    def test_versions_compare_numerically_not_as_text(self):
        r = ps.node_os(Ec2Stub(["a"], {"a": (BR.format("1.9.0"), "")}), SsmStub("1.10.0-x"))
        self.assertFalse(r["nodes"][0]["on_latest"])

    def test_failure_leaves_no_nodes(self):
        r = ps.node_os(Ec2Stub(["a"], {}, fail=True), SsmStub("1.67.0"))
        self.assertTrue(r["status"].startswith("failed"))
        self.assertIsNone(r["nodes"])

    def test_release_renders_and_counts_hosts_behind(self):
        curr = snap(nodes={"status": "ok", "instances_scanned": 4, "package_findings": 0, "kernel_ch": None,
                           "platforms": [{"platform": "BOTTLEROCKET", "findings": 1}]})
        curr["raw"]["node_os"] = {"status": "ok", "other_instances": 1, "nodes": [
            {"os": "BOTTLEROCKET", "k8s": "1.36", "arch": "x86_64", "version": "1.66.0", "instances": 3,
             "image_created": "2026-09-19", "latest": "1.67.0", "latest_published": "2026-10-15", "on_latest": False}]}
        self.assertEqual(lv.node_evidence(curr)["release"]["behind"], 3)
        md = render_movement_markdown(mv.security_movement({"raw": {}}, curr, "a", "b"))
        self.assertIn("| BOTTLEROCKET | 1.36 | 1.66.0 | 3 | 1.67.0 | 2026-10-15 | **no** |", md)
        self.assertIn("1 running instance(s) are on another image", md)


if __name__ == "__main__":
    unittest.main()
