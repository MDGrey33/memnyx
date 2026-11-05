"""posture.md and github.md: computed facts, no fixed advice that goes stale."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
with mock.patch("config_util.load_config", return_value={"aws_profile": "p", "aws_region": "r", "github_org": "o"}):
    import posture_snapshot as ps  # noqa: E402
import github_security_snapshot as gs  # noqa: E402

FIX = HERE / "fixtures" / "pair-a" / "20261007"


def raw(name):
    return json.loads((FIX / name).read_text())


class TestPostureReport(unittest.TestCase):
    def test_no_addressable_estimate_and_one_package_count(self):
        md = ps.build_report(raw("raw.json"))
        self.assertNotIn("Addressable", md)
        self.assertNotIn("Unique packages affected", md)
        self.assertRegex(md, r"> \d+ packages total\.")

    def test_base_layers_lists_only_shared_layers_and_makes_no_promise(self):
        r = raw("raw.json")
        md = ps.build_report(r)
        section = md.split("## Shared Base Layers")[1].split("\n## ")[0]
        self.assertNotIn("closes all findings", section)
        repos = [int(row.split("|")[2].strip()) for row in section.splitlines()
                 if row.startswith("| ") and not row.startswith("| Layer")]
        self.assertTrue(repos)
        self.assertTrue(all(n >= 2 for n in repos), repos)
        shared = sum(1 for l in r["base_layers"] if l.get("repos", 0) >= 2)
        self.assertIn(f"({shared} of {len(r['base_layers'])} captured)", section)


class TestGithubReport(unittest.TestCase):
    def test_dependabot_status_follows_failed_fetches(self):
        r = raw("github-raw.json")
        self.assertIn("| Vulnerability alerts (Dependabot) | ✓ active |", gs.build_report(r))
        r["vuln_fetch_failures"] = ["svc-1", "svc-2"]
        self.assertIn("| Vulnerability alerts (Dependabot) | ⚠ 2 repo(s) failed |", gs.build_report(r))

    def test_no_fix_table_says_how_many_it_shows_and_gives_no_advice(self):
        r = raw("github-raw.json")
        r["vuln_agg"]["no_fix_critical_high_total"] = 33
        md = gs.build_report(r)
        self.assertIn(f"Showing {len(r['vuln_agg']['no_fix_critical_high'])} of 33.", md)
        self.assertNotRegex(md, r"(?i)suppression|cannot be patched")

    def test_the_row_cap_is_counted_not_assumed(self):
        alerts = [{"repo": "r", "package": f"p{i}", "severity": "HIGH", "cve": None, "summary": "",
                   "fix_available": False} for i in range(40)]
        agg = gs.aggregate_vuln(alerts)
        self.assertEqual((len(agg["no_fix_critical_high"]), agg["no_fix_critical_high_total"]), (gs.NO_FIX_ROWS, 40))

if __name__ == "__main__":
    unittest.main()
