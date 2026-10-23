"""Tests for the rebuilt-vs-older image comparison in posture_snapshot.py, against stub clients."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
with mock.patch("config_util.load_config", return_value={"aws_profile": "p", "aws_region": "r"}):
    import posture_snapshot as ps  # noqa: E402

UTC = timezone.utc
SINCE = datetime(2026, 9, 23, 8, 32, tzinfo=UTC)
OLD = datetime(2026, 9, 1, tzinfo=UTC)
NEW = datetime(2026, 10, 1, tzinfo=UTC)


def rid(repo, n):
    return f"arn:aws:ecr:r:111111111111:repository/{repo}/sha256:{n:064x}"


class Stub:
    """images: [(repo, n, pushedAt, critical+high, scan status)]"""

    def __init__(self, images, fail=None, page=2):
        self.images, self.fail, self.page = images, fail, page

    def _paged(self, items, kw):
        start = int(kw.get("nextToken", 0))
        resp = {"items": items[start:start + self.page]}
        if start + self.page < len(items):
            resp["nextToken"] = str(start + self.page)
        return resp

    def list_coverage(self, **kw):
        if self.fail == "coverage":
            raise ps.ClientError({"Error": {"Code": "AccessDenied"}}, "ListCoverage")
        items = [{"resourceId": rid(r, n), "scanStatus": {"statusCode": st},
                  "resourceMetadata": {"ecrRepository": {"name": r}}} for r, n, _, _, st in self.images]
        p = self._paged(items, kw)
        return {"coveredResources": p["items"], **({"nextToken": p["nextToken"]} if "nextToken" in p else {})}

    def list_finding_aggregations(self, **kw):
        if self.fail == "agg":
            raise ps.ClientError({"Error": {"Code": "ThrottlingException"}}, "ListFindingAggregations")
        items = [{"awsEcrContainerAggregation": {"resourceId": rid(r, n), "severityCounts": {"critical": ch // 2, "high": ch - ch // 2}}}
                 for r, n, _, ch, _ in self.images if ch]
        p = self._paged(items, kw)
        return {"responses": p["items"], **({"nextToken": p["nextToken"]} if "nextToken" in p else {})}

    def describe_images(self, repositoryName, **kw):
        if self.fail == "ecr":
            raise ps.ClientError({"Error": {"Code": "AccessDenied"}}, "DescribeImages")
        if self.fail == "gone" and repositoryName == "ns/gone":
            raise ps.ClientError({"Error": {"Code": "RepositoryNotFoundException"}}, "DescribeImages")
        items = [{"imageDigest": f"sha256:{n:064x}", "imagePushedAt": t}
                 for r, n, t, _, _ in self.images if r == repositoryName]
        p = self._paged(items, kw)
        return {"imageDetails": p["items"], **({"nextToken": p["nextToken"]} if "nextToken" in p else {})}


def run(images, **kw):
    s = Stub(images, **kw)
    return ps.rebuild_comparison(s, s, SINCE, "20260923")


class TestRebuildComparison(unittest.TestCase):
    def test_per_repo_comparison_and_flag(self):
        r = run([("ns/a", 1, OLD, 100, "ACTIVE"), ("ns/a", 2, OLD, 120, "ACTIVE"),
                 ("ns/a", 3, NEW, 400, "ACTIVE"),
                 ("ns/b", 4, OLD, 100, "ACTIVE"), ("ns/b", 5, NEW, 104, "ACTIVE")])
        self.assertEqual(r["status"], "ok")
        a = next(x for x in r["repos"] if x["repo"] == "ns/a")
        self.assertEqual((a["old_images"], a["old_ch_per_image"], a["new_images"], a["new_ch_per_image"]), (2, 110.0, 1, 400.0))
        self.assertTrue(a["flagged"])
        self.assertFalse(next(x for x in r["repos"] if x["repo"] == "ns/b")["flagged"])
        self.assertEqual(r["repos"][0]["repo"], "ns/a")  # sorted by gap, largest first

    def test_flag_needs_both_ratio_and_gap(self):
        small = run([("ns/a", 1, OLD, 10, "ACTIVE"), ("ns/a", 2, NEW, 40, "ACTIVE")])["repos"][0]
        self.assertFalse(small["flagged"])  # 4x but only +30 per image
        big = run([("ns/a", 1, OLD, 1000, "ACTIVE"), ("ns/a", 2, NEW, 1200, "ACTIVE")])["repos"][0]
        self.assertFalse(big["flagged"])  # +200 per image but only 1.2x

    def test_inactive_images_are_excluded(self):
        r = run([("ns/a", 1, OLD, 100, "ACTIVE"), ("ns/a", 2, OLD, 9999, "INACTIVE"), ("ns/a", 3, NEW, 100, "ACTIVE")])
        self.assertEqual(r["repos"][0]["old_ch_per_image"], 100.0)
        self.assertEqual(r["totals"]["inactive_images_excluded"], 1)

    def test_images_with_no_findings_count_as_zero(self):
        r = run([("ns/a", 1, OLD, 0, "ACTIVE"), ("ns/a", 2, OLD, 100, "ACTIVE"), ("ns/a", 3, NEW, 50, "ACTIVE")])
        self.assertEqual(r["repos"][0]["old_ch_per_image"], 50.0)

    def test_one_sided_repos_are_listed_not_dropped(self):
        r = run([("ns/a", 1, NEW, 100, "ACTIVE"), ("ns/b", 2, OLD, 100, "ACTIVE")])
        self.assertEqual(r["repos"], [])
        reasons = {x["repo"]: x["reason"] for x in r["not_comparable"]}
        self.assertEqual(reasons, {"ns/a": "no older live images", "ns/b": "no images pushed in window"})

    def test_follows_pagination_everywhere(self):
        imgs = [("ns/a", i, OLD if i % 2 else NEW, 10 * i, "ACTIVE") for i in range(1, 8)]
        r = run(imgs, )
        t = r["totals"]
        self.assertEqual(t["old_images"] + t["new_images"], 7)
        self.assertEqual(t["old_ch"] + t["new_ch"], sum(10 * i for i in range(1, 8)))

    def test_failures_leave_the_field_empty(self):
        imgs = [("ns/a", 1, OLD, 100, "ACTIVE"), ("ns/a", 2, NEW, 100, "ACTIVE")]
        for where in ("coverage", "agg", "ecr"):
            r = run(imgs, fail=where)
            self.assertTrue(r["status"].startswith("failed"), where)
            self.assertIsNone(r["repos"], where)
            self.assertIsNone(r["totals"], where)

    def test_deleted_repo_degrades_to_unknown_push_time(self):
        r = run([("ns/a", 1, OLD, 100, "ACTIVE"), ("ns/a", 2, NEW, 100, "ACTIVE"), ("ns/gone", 3, OLD, 5, "ACTIVE")],
                fail="gone")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["totals"]["push_time_unknown"], 1)


class TestReportSection(unittest.TestCase):
    def test_missing_field_says_not_available(self):
        raw = {"generated_at": "x", "account_totals": {}, "packages": [], "repositories": [], "amis": [],
               "coverage": {}, "title_stats": {"unique_count": 0, "pkg_count": 0, "top_by_ch": []},
               "base_layers": [], "rebuild_comparison": {"status": "failed: coverage: AccessDenied", "repos": None}}
        self.assertIn("Not available (failed: coverage: AccessDenied)", ps.build_report(raw))


if __name__ == "__main__":
    unittest.main()
