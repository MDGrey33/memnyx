"""correlation.md: the cross-source report keeps its facts and gives no second ranking."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"


class TestCorrelationReport(unittest.TestCase):
    def report(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(HERE / "fixtures" / "pair-a" / "20261007", Path(tmp) / "20261007")
            r = subprocess.run([sys.executable, "correlation.py", "--reports-dir", tmp], cwd=SCRIPTS,
                               capture_output=True, text=True, env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": ""})
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        return r.stdout

    def test_no_quick_win_ranking_or_effort_labels(self):
        out = self.report()
        self.assertNotRegex(out, r"(?i)quick-win|effort categor|phantom|trivial|structural|suppress")
        for section in ("## Summary", "## Zone A — Package Overlap", "## Zone B", "## Zone C"):
            self.assertIn(section, out)

    def test_zones_say_what_they_count_and_nothing_claims_priority(self):
        out = self.report()
        self.assertIn("Zone A — CVE in BOTH sources (of the Inspector top 50)", out)
        self.assertIn("Zone B — Inspector only (of the Inspector top 50)", out)
        self.assertNotRegex(out, r"(?i)highest priority|highest-confidence|transitive|build-only|"
                                 r"may have been updated|simultaneously")
        sys.path.insert(0, str(SCRIPTS))
        import correlation as c
        self.assertIn(f"top {c.CONVERGENCE_TOP_N} of 2 or more", out)
        self.assertIn(f"Score = Inspector(C×{c.W_INSP_CRIT} + H×{c.W_INSP_HIGH})", out)

    def test_zero_secrets_is_not_an_alarm(self):
        out = self.report()
        row = next(l for l in out.splitlines() if l.startswith("| Secret scanning alerts"))
        self.assertTrue(row.endswith("| 0 |"), row)

    def test_no_hardcoded_package_verdicts_in_the_code(self):
        src = (SCRIPTS / "correlation.py").read_text()
        for name in ("STRUCTURAL_PKGS", "NO_FIX_PKGS", "build_package_quickwin", "EFFORT_DEFINITIONS"):
            self.assertNotIn(name, src)


if __name__ == "__main__":
    unittest.main()
