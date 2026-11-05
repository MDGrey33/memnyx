"""posture_snapshot.main() runs end to end. The aggregations and coverage, which
the capture requires, come from a fixture; every other AWS call is refused, so each optional capture takes its degraded
path and main() still writes raw.json."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
import unittest.mock as mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
with mock.patch("config_util.load_config", return_value={"aws_profile": "p", "aws_region": "r"}):
    import posture_snapshot as ps  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "pair-a" / "20261007" / "raw.json"
AGG_KEYS = {"ACCOUNT": None, "TITLE": None, "IMAGE_LAYER": None, "PACKAGE": "packages",
            "REPOSITORY": "repositories", "AMI": "amis"}


class Refused:
    """An AWS client that refuses every call, as an expired session would."""

    def __getattr__(self, name):
        def call(*a, **k):
            raise ps.ClientError({"Error": {"Code": "AccessDeniedException"}}, name)
        return call

    def get_paginator(self, name):
        raise ps.ClientError({"Error": {"Code": "AccessDeniedException"}}, name)

    def get_caller_identity(self):
        return {"Account": "000000000000"}


class Session:
    def __init__(self, **k):
        pass

    def client(self, name, **k):
        return Refused()


class TestCaptureMain(unittest.TestCase):
    def run_main(self, reports_dir):
        raw = json.loads(FIXTURE.read_text())

        def aggregations(c, agg_type, req, max_results=100, required=True):
            if agg_type == "ACCOUNT":
                return [{"accountAggregation": {"severityCounts": raw["account_totals"]}}]
            key = AGG_KEYS[agg_type]
            return list(raw[key]) if key else []

        breakdown = mock.Mock(wraps=ps.package_breakdown)
        argv = ["posture_snapshot.py", "--save", "--raw", "--reports-dir", str(reports_dir)]  # as run_analysis.sh calls it
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(ps, "inspector_client", Refused), \
             mock.patch.object(ps, "ecr_client", Refused), \
             mock.patch.object(ps.boto3, "Session", Session), \
             mock.patch.object(ps, "paginate_aggregations", aggregations), \
             mock.patch.object(ps, "get_coverage_counts", lambda c: raw["coverage"]), \
             mock.patch.object(ps, "package_breakdown", breakdown), \
             mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            ps.main()
        written = sorted(Path(reports_dir).glob("*/raw.json"))
        return breakdown, written

    def test_writes_raw_json_with_no_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            _, written = self.run_main(d)
            self.assertEqual(len(written), 1)
            out = json.loads(written[0].read_text())
            self.assertEqual(out["first_seen"]["status"], "no_previous_snapshot")
            self.assertEqual(out["account_totals"], json.loads(FIXTURE.read_text())["account_totals"])
            self.assertTrue((written[0].parent / "posture.md").read_text().strip())

    def test_runs_the_since_branch_against_a_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            prev = Path(d) / "20000101"
            prev.mkdir()
            (prev / "raw.json").write_text(json.dumps({"generated_at": "2000-01-01 00:00 UTC"}))
            _, written = self.run_main(d)
            out = json.loads(written[-1].read_text())
            self.assertEqual(out["first_seen"]["basis_snapshot"], "20000101")
            self.assertTrue(str(out["first_seen"]["status"]).startswith("failed"))

    def test_kernel_packages_reach_the_per_repo_breakdown(self):
        names = {p["packageAggregation"]["packageName"] for p in json.loads(FIXTURE.read_text())["packages"]}
        kernel = names & ps.KERNEL_PACKAGES
        self.assertTrue(kernel, "fixture holds no kernel package, so this test cannot fail")
        with tempfile.TemporaryDirectory() as d:
            breakdown, _ = self.run_main(d)
            self.assertLessEqual(kernel, set(breakdown.call_args.args[1]))


if __name__ == "__main__":
    unittest.main()
