"""Tests for the first-seen capture in posture_snapshot.py, against a stub client."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import unittest.mock as mock

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

# posture_snapshot reads config at import; give it a minimal one.
with mock.patch("config_util.load_config", return_value={"aws_profile": "p", "aws_region": "r"}):
    import posture_snapshot as ps  # noqa: E402

UTC = timezone.utc
SINCE = datetime(2026, 9, 23, 8, 32, tzinfo=UTC)
UNTIL = datetime(2026, 10, 7, 15, 5, tzinfo=UTC)


def ecr(pushed, pkg="linux-libc-dev", image="img-a", published=None):
    vuln = {"vulnerablePackages": [{"name": pkg}]}
    if published is not None:
        vuln["vendorCreatedAt"] = published
    return {"resources": [{"type": "AWS_ECR_CONTAINER_IMAGE", "id": image,
                           "details": {"awsEcrContainerImage": {"pushedAt": pushed}}}],
            "packageVulnerabilityDetails": vuln}


class StubClient:
    def __init__(self, pages, fail_on_page=None):
        self.pages, self.fail_on_page, self.calls = pages, fail_on_page, []

    def list_findings(self, **kw):
        self.calls.append(kw)
        i = len(self.calls) - 1
        if self.fail_on_page == i:
            raise ps.ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "ListFindings")
        resp = {"findings": self.pages[i]}
        if i + 1 < len(self.pages):
            resp["nextToken"] = f"t{i + 1}"
        return resp


class TestFirstSeen(unittest.TestCase):
    def test_splits_existing_and_rebuilt_images(self):
        before = datetime(2026, 9, 7, tzinfo=UTC)
        after = datetime(2026, 10, 1, tzinfo=UTC)
        c = StubClient([[ecr(before, image="old-1"), ecr(before, image="old-1"), ecr(after, image="new-1")],
                        [ecr(after.isoformat(), image="new-2", pkg="perl")]])
        r = ps.first_seen_since(c, SINCE, UNTIL, "20260923")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["total"], 4)
        self.assertEqual(r["ecr"]["existing_images"], 2)
        self.assertEqual(r["ecr"]["pushed_since"], 2)
        self.assertEqual(r["ecr"]["images_existing"], 1)
        self.assertEqual(r["ecr"]["images_pushed_since"], 2)
        libc = next(p for p in r["by_package"] if p["package"] == "linux-libc-dev")
        self.assertEqual((libc["existing_images"], libc["pushed_since"]), (2, 1))

    def test_follows_pagination_and_sends_the_window(self):
        c = StubClient([[ecr(SINCE)], [ecr(SINCE)], [ecr(SINCE)]])
        r = ps.first_seen_since(c, SINCE, UNTIL)
        self.assertEqual(r["total"], 3)
        self.assertEqual(len(c.calls), 3)
        self.assertEqual(c.calls[1]["nextToken"], "t1")
        fc = c.calls[0]["filterCriteria"]
        self.assertEqual(fc["firstObservedAt"], [{"startInclusive": SINCE, "endInclusive": UNTIL}])
        self.assertEqual({s["value"] for s in fc["severity"]}, {"CRITICAL", "HIGH"})
        self.assertEqual(fc["findingStatus"], [{"comparison": "EQUALS", "value": "ACTIVE"}])

    def test_image_pushed_exactly_at_window_start_is_existing(self):
        r = ps.first_seen_since(StubClient([[ecr(SINCE)]]), SINCE, UNTIL)
        self.assertEqual(r["ecr"]["existing_images"], 1)

    def test_failure_mid_pagination_returns_no_counts(self):
        c = StubClient([[ecr(SINCE)] * 5, [ecr(SINCE)]], fail_on_page=1)
        r = ps.first_seen_since(c, SINCE, UNTIL)
        self.assertTrue(r["status"].startswith("failed"))
        for k in ("total", "ecr", "by_package", "advisory", "by_resource_type"):
            self.assertIsNone(r[k], k)

    def test_advisory_publication_split(self):
        # Unequal counts, so swapping the two buckets cannot pass.
        c = StubClient([[ecr(SINCE, published="2026-07-01T00:00:00Z"),
                         ecr(SINCE, published="2026-08-01T00:00:00Z"),
                         ecr(SINCE, published="2026-10-01T00:00:00Z"),
                         ecr(SINCE)]])
        a = ps.first_seen_since(c, SINCE, UNTIL)["advisory"]
        self.assertEqual(a, {"published_before_window": 2, "published_in_window": 1, "date_unknown": 1})

    def test_unknown_push_time_and_non_ecr_resources(self):
        lam = {"resources": [{"type": "AWS_LAMBDA_FUNCTION"}],
               "packageVulnerabilityDetails": {"vulnerablePackages": [{"name": "urllib3"}]}}
        r = ps.first_seen_since(StubClient([[ecr(None), lam]]), SINCE, UNTIL)
        self.assertEqual(r["ecr"]["push_time_unknown"], 1)
        self.assertEqual(r["by_resource_type"], {"AWS_ECR_CONTAINER_IMAGE": 1, "AWS_LAMBDA_FUNCTION": 1})
        self.assertEqual(next(p for p in r["by_package"] if p["package"] == "urllib3")["other"], 1)


class TestPreviousCapture(unittest.TestCase):
    def _dir(self, folders):
        d = tempfile.TemporaryDirectory()
        for name, ts in folders.items():
            (Path(d.name) / name).mkdir()
            if ts is not None:
                (Path(d.name) / name / "raw.json").write_text(json.dumps({"generated_at": ts}))
        return d

    def test_newest_folder_strictly_before_today(self):
        with self._dir({"20260909": "2026-09-09 17:54 UTC", "20260923": "2026-09-23 08:32 UTC",
                        "20261007": "2026-10-07 15:05 UTC"}) as d:
            self.assertEqual(ps.previous_capture(d, "20261007"),
                             ("20260923", datetime(2026, 9, 23, 8, 32, tzinfo=UTC)))

    def test_skips_folders_without_raw_json(self):
        with self._dir({"20260909": "2026-09-09 17:54 UTC", "20260923": None}) as d:
            self.assertEqual(ps.previous_capture(d, "20261007")[0], "20260909")

    def test_none_when_no_previous(self):
        with self._dir({"20261007": "2026-10-07 15:05 UTC"}) as d:
            self.assertEqual(ps.previous_capture(d, "20261007"), (None, None))
        self.assertEqual(ps.previous_capture(None, "20261007"), (None, None))


class TestReportSection(unittest.TestCase):
    def _raw(self, first_seen):
        return {"generated_at": "x", "account_totals": {}, "packages": [], "repositories": [], "amis": [],
                "coverage": {}, "title_stats": {"unique_count": 0, "pkg_count": 0, "top_by_ch": []},
                "base_layers": [], "first_seen": first_seen}

    def test_missing_field_says_not_available(self):
        md = ps.build_report(self._raw({"status": "no_previous_snapshot", "total": None}))
        self.assertIn("Not available (no_previous_snapshot)", md)


if __name__ == "__main__":
    unittest.main()
