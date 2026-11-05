"""Tests for the package-manager lookup and layer helpers in posture_snapshot.py."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
import unittest.mock as mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
with mock.patch("config_util.load_config", return_value={"aws_profile": "p", "aws_region": "r"}):
    import posture_snapshot as ps  # noqa: E402


class Stub:
    def __init__(self, managers, fail=()):
        self.managers, self.fail, self.calls = managers, set(fail), []

    def list_findings(self, maxResults, filterCriteria):
        name = filterCriteria["vulnerablePackages"][0]["name"]["value"]
        self.calls.append(name)
        if name in self.fail:
            raise ps.ClientError({"Error": {"Code": "ThrottlingException"}}, "ListFindings")
        if name not in self.managers:
            return {"findings": []}
        return {"findings": [{"packageVulnerabilityDetails": {"vulnerablePackages": [
            {"name": "other-pkg", "packageManager": "WRONG"}, {"name": name, "packageManager": self.managers[name]}]}}]}


class TestPackageManagers(unittest.TestCase):
    def test_looks_up_only_unknown_names_and_reads_the_matching_package(self):
        c = Stub({"axios": "NODE", "perl": "OS"})
        rows, st = ps.package_managers(c, ["axios", "perl", "cached"], {"cached": "PYTHON"})
        self.assertEqual(sorted(c.calls), ["axios", "perl"])
        self.assertEqual({r["package"]: r["manager"] for r in rows}, {"axios": "NODE", "perl": "OS", "cached": "PYTHON"})
        self.assertEqual((st["queried"], st["reused"], st["unknown"]), (2, 1, 0))

    def test_failure_or_no_finding_is_none_not_a_guess(self):
        rows, st = ps.package_managers(Stub({}, fail={"x"}), ["x", "y"], {})
        self.assertEqual({r["package"]: r["manager"] for r in rows}, {"x": None, "y": None})
        self.assertEqual((st["failed"], st["unknown"]), (1, 2))

    def test_departed_packages_stay_in_the_map(self):
        rows, _ = ps.package_managers(Stub({}), [], {"gone": "NODE"})
        self.assertEqual(rows, [{"package": "gone", "manager": "NODE"}])

    def test_previous_map_read_from_basis(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "20260923").mkdir()
            (Path(d) / "20260923" / "raw.json").write_text(json.dumps(
                {"package_managers": [{"package": "a", "manager": "OS"}, {"package": "b", "manager": None}]}))
            self.assertEqual(ps.previous_package_managers(d, "20260923"), {"a": "OS"})
            self.assertEqual(ps.previous_package_managers(d, "20260101"), {})
            self.assertEqual(ps.previous_package_managers(None, None), {})


class TestLayers(unittest.TestCase):
    def test_compact_list_keeps_every_layer_with_critical_or_high(self):
        layers = [{"layer": f"L{i}", "c": 0, "h": h, "m": 5, "repos": 1, "repo_list": ["r"], "images": 1}
                  for i, h in enumerate([30, 0, 1] + [2] * 30)]
        out = ps.all_layers_compact(layers)
        self.assertEqual(len(out), 32)  # beyond the top 20, minus the one with none
        self.assertNotIn("L1", [x["layer"] for x in out])
        self.assertEqual(set(out[0]), {"layer", "c", "h", "images", "repo_list"})



class TestPipelineOrder(unittest.TestCase):
    def test_movement_runs_after_the_dashboard_writes_snapshot_json(self):
        # emit_movement reads <date>/snapshot.json for the GitHub and correlation counts;
        # run before build_dashboard, every one of those reads as not comparable.
        sh = (Path(__file__).resolve().parent.parent / "scripts" / "run_analysis.sh").read_text()
        self.assertLess(sh.index('"$SCRIPT_DIR/build_dashboard.py"'), sh.index('"$SCRIPT_DIR/emit_movement.py"'))


if __name__ == "__main__":
    unittest.main()
