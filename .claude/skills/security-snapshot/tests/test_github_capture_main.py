"""github_security_snapshot.main() runs end to end with --save --raw, as
run_analysis.sh calls it. The gh calls are replaced with a fixture's alerts;
one repo's fetch fails, under the 10% the capture tolerates."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
import unittest.mock as mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
with mock.patch("config_util.load_config", return_value={"github_org": "example-org"}):
    import github_security_snapshot as gs  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "pair-a" / "20261007" / "github-raw.json"


class TestGithubCaptureMain(unittest.TestCase):
    def run_main(self, reports_dir):
        raw = json.loads(FIXTURE.read_text())
        by_repo = {}
        for a in raw["vuln_alerts_detail"]:
            by_repo.setdefault(a["repo"], []).append(a)
        quiet = [f"svc-q{i}" for i in range(10)]  # alerts counted, none returned
        repos = [{"name": r, "vuln_total": len(v)} for r, v in by_repo.items()] + \
                [{"name": r, "vuln_total": 1} for r in quiet] + [{"name": "svc-broken", "vuln_total": 3}]

        def details(org, repo):
            if repo == "svc-broken":
                raise RuntimeError("timeout")
            return list(by_repo.get(repo, []))

        argv = ["github_security_snapshot.py", "--save", "--raw", "--reports-dir", str(reports_dir)]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(gs, "list_all_repos", lambda org: repos), \
             mock.patch.object(gs, "get_vuln_details", details), \
             mock.patch.object(gs, "get_code_scanning", lambda org, r: (raw["code_scanning_status"], raw["code_scanning"])), \
             mock.patch.object(gs, "get_secret_scanning", lambda org, r: (raw["secret_scanning_status"], raw["secret_scanning"])), \
             mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            gs.main()
        return raw, by_repo

    def test_writes_the_report_and_raw_json(self):
        with tempfile.TemporaryDirectory() as d:
            raw, by_repo = self.run_main(d)
            (folder,) = Path(d).iterdir()
            self.assertTrue((folder / "github.md").read_text().strip())
            out = json.loads((folder / "github-raw.json").read_text())
            self.assertEqual(out["vuln_fetch_failures"], ["svc-broken"])
            self.assertEqual(len(out["vuln_alerts_detail"]), sum(len(v) for v in by_repo.values()))
            self.assertEqual(len(out["code_scanning"]), len(raw["code_scanning"]))
            self.assertEqual(out["repos_total"], len(by_repo) + 11)


if __name__ == "__main__":
    unittest.main()
