"""Unit tests for fixture_mask.py, on small hand-made inputs (no real data)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fixture_mask as fm  # noqa: E402

REAL_ACCOUNT = "999988887777"
REAL_LAYER = "sha256:" + "ab" * 32


def _set():
    """Two dates, the same repo appearing as an ECR name and as a bare GitHub name."""
    raw = {
        "account": REAL_ACCOUNT,
        "region": "eu-west-1",
        "repositories": [{"repositoryAggregation": {"repository": "acme/billing-api", "accountId": REAL_ACCOUNT}}],
        "base_layers": [{"layer": REAL_LAYER, "repo_list": ["acme/billing-api", "acme-uat/curl"]}],
        "packages": [{"packageAggregation": {"packageName": "curl", "accountId": REAL_ACCOUNT}}],
    }
    gh = {
        "org": "acme-corp",
        "vuln_alerts_detail": [{"repo": "billing-api", "package": "lodash", "summary": "Prototype pollution"}],
    }
    return {"20260101": {"raw.json": raw, "github-raw.json": gh},
            "20260115": {"raw.json": raw, "github-raw.json": gh}}


class TestMasking(unittest.TestCase):
    def test_unclassified_field_stops_the_run(self):
        s = _set()
        s["20260101"]["raw.json"]["image_tag"] = "release-v1.2.3"
        with self.assertRaises(fm.UnclassifiedField) as ctx:
            fm.mask_set(s)
        self.assertIn("raw.json:.image_tag", str(ctx.exception))

    def test_ecr_and_github_names_share_an_alias_across_dates(self):
        masked, _ = fm.mask_set(_set())
        for date in masked:
            ecr = masked[date]["raw.json"]["repositories"][0]["repositoryAggregation"]["repository"]
            gh = masked[date]["github-raw.json"]["vuln_alerts_detail"][0]["repo"]
            self.assertEqual(ecr.split("/")[1], gh)
        self.assertEqual(masked["20260101"], masked["20260115"])

    def test_identifiers_take_alias_grammar_and_public_fields_survive(self):
        masked, _ = fm.mask_set(_set())
        raw = masked["20260101"]["raw.json"]
        self.assertEqual(raw["account"], fm.FAKE_ACCOUNT)
        self.assertRegex(raw["base_layers"][0]["layer"], fm.ALIAS_PATTERNS["LAYER"])
        for r in raw["base_layers"][0]["repo_list"]:
            self.assertRegex(r, fm.ALIAS_PATTERNS["ECR_REPO"])
        self.assertEqual(raw["region"], fm.FAKE_REGION)
        self.assertEqual(raw["packages"][0]["packageAggregation"]["packageName"], "curl")
        self.assertEqual(masked["20260101"]["github-raw.json"]["org"], fm.FAKE_ORG)

    def test_lever_capture_fields_are_masked(self):
        s = _set()
        s["20260101"]["raw.json"]["package_breakdown"] = {"status": "ok", "packages": ["linux"], "rows": [
            {"package": "linux", "repo": "acme/billing-api", "platforms": ["DEBIAN_12"], "versions": ["6.1.1"],
             "layers": [{"layer": REAL_LAYER, "ch": 3}]}]}
        s["20260101"]["raw.json"]["node_scan"] = {"status": "ok", "platforms": [{"platform": "BOTTLEROCKET"}]}
        masked, _ = fm.mask_set(s)
        row = masked["20260101"]["raw.json"]["package_breakdown"]["rows"][0]
        self.assertRegex(row["repo"], fm.ALIAS_PATTERNS["ECR_REPO"])
        self.assertEqual(row["layers"][0]["layer"], masked["20260101"]["raw.json"]["base_layers"][0]["layer"])
        self.assertEqual((row["package"], row["versions"]), ("linux", ["6.1.1"]))

    def test_alert_trim_keeps_the_same_repos_on_every_date(self):
        def alerts(*repos):
            return {"github-raw.json": {"vuln_alerts_detail": [{"repo": r} for r in repos]}}
        s = {"20260101": alerts("a", "b", "c", "c"), "20260115": alerts("a", "b", "b", "c", "c", "c")}
        out = fm.trim_alert_detail(s, 2)
        for date in s:
            self.assertEqual({a["repo"] for a in out[date]["github-raw.json"]["vuln_alerts_detail"]}, {"b", "c"})
        self.assertEqual(len(out["20260101"]["github-raw.json"]["vuln_alerts_detail"]), 3)

    def test_code_scanning_trim_caps_each_date_stably(self):
        s = {d: {"github-raw.json": {"code_scanning": [{"rule_id": f"r{i}"} for i in range(n)]}}
             for d, n in (("20260101", 5), ("20260115", 2))}
        out = fm.trim_code_scanning(s, 3)
        self.assertEqual([len(out[d]["github-raw.json"]["code_scanning"]) for d in s], [3, 2])
        self.assertEqual(out, fm.trim_code_scanning(s, 3))
        with self.assertRaises(ValueError):
            fm.trim_code_scanning(s, 0)

    def test_fake_values_do_not_depend_on_real_values(self):
        a, _ = fm.mask_set(_set())
        s = _set()
        for d in s.values():
            d["raw.json"]["base_layers"][0]["layer"] = "sha256:" + "cd" * 32
        b, _ = fm.mask_set(s)
        self.assertEqual(a["20260101"]["raw.json"]["base_layers"][0]["layer"],
                         b["20260101"]["raw.json"]["base_layers"][0]["layer"])

    def test_deterministic(self):
        self.assertEqual(fm.mask_set(_set())[0], fm.mask_set(_set())[0])


class TestLeakCheck(unittest.TestCase):
    def setUp(self):
        self.masked, self.aliases = fm.mask_set(_set())

    def test_clean_output_has_no_leaks(self):
        self.assertEqual(fm.find_leaks(self.masked, self.aliases), [])

    def test_catches_account_in_a_public_field(self):
        self.masked["20260101"]["raw.json"]["region"] = f"arn:aws:iam::{REAL_ACCOUNT}:root"
        self.assertTrue(fm.find_leaks(self.masked, self.aliases))

    def test_catches_hyphenated_repo_name_inside_free_text(self):
        self.masked["20260101"]["github-raw.json"]["vuln_alerts_detail"][0]["summary"] = "seen in billing-api only"
        self.assertTrue(fm.find_leaks(self.masked, self.aliases))

    def test_catches_real_name_left_at_a_repo_position(self):
        self.masked["20260101"]["github-raw.json"]["vuln_alerts_detail"][0]["repo"] = "curl"
        self.assertTrue(fm.find_leaks(self.masked, self.aliases))

    def test_catches_namespace_and_layer(self):
        self.masked["20260101"]["raw.json"]["region"] = "acme-uat/thing"
        self.assertTrue(fm.find_leaks(self.masked, self.aliases))
        self.masked, self.aliases = fm.mask_set(_set())
        self.masked["20260101"]["raw.json"]["region"] = REAL_LAYER
        self.assertTrue(fm.find_leaks(self.masked, self.aliases))

    def test_catches_extra_config_terms(self):
        self.masked["20260101"]["github-raw.json"]["vuln_alerts_detail"][0]["summary"] = "profile my-ro-profile"
        self.assertTrue(fm.find_leaks(self.masked, self.aliases, ("my-ro-profile",)))

    def test_single_word_repo_name_is_not_a_leak_in_a_package_field(self):
        # `curl` is both a repo here and a package name; the package field must survive.
        self.assertEqual(self.masked["20260101"]["raw.json"]["packages"][0]["packageAggregation"]["packageName"], "curl")
        self.assertEqual(fm.find_leaks(self.masked, self.aliases), [])


if __name__ == "__main__":
    unittest.main()
