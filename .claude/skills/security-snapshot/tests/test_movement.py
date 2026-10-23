"""Tests for movement.py, movement_markdown.py and emit_movement.resolve_targets."""
import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import emit_movement as em  # noqa: E402
import movement as mv  # noqa: E402
import movement_markdown as md  # noqa: E402

PAIR = HERE / "fixtures" / "pair-a"


def snap(account=None, repos=None, packages=None, layers=None, github=None, zone_a=None, coverage=None,
         gh_alerts=None, extra_raw=None):
    raw = {}
    if account is not None:
        raw["account_totals"] = account
    if repos is not None:
        raw["repositories"] = [{"repositoryAggregation": {"repository": r, "affectedImages": n,
                                                          "severityCounts": {"critical": 0, "high": ch}}}
                               for r, (ch, n) in repos.items()]
    if packages is not None:
        raw["packages"] = [{"packageAggregation": {"packageName": p, "severityCounts": {"critical": 0, "high": ch}}}
                           for p, ch in packages.items()]
    if layers is not None:
        raw["base_layers"] = [{"layer": l, "images": n, "c": 0, "h": ch, "repo_list": []} for l, (ch, n) in layers.items()]
    if coverage is not None:
        raw["coverage"] = coverage
    raw.update(extra_raw or {})
    out = {"raw": raw, "github": None, "snapshot": None, "correlation": None}
    if github is not None:
        out["snapshot"] = {"github": github}
    if zone_a is not None:
        out["correlation"] = {"correlation": {"zone_a_pkg_overlap": [{"package": p} for p in zone_a]}}
    if gh_alerts is not None:
        out["github"] = {"vuln_alerts_detail": gh_alerts}
    return out


def by_key(counts, key):
    return next(m for m in counts if m["key"] == key)


class TestCounts(unittest.TestCase):
    def test_missing_metric_is_none_not_zero(self):
        m = by_key(mv.count_movements(snap(), snap(account={"critical": 1, "high": 2})), "inspector_ch")
        self.assertIsNone(m["prev"])
        self.assertEqual(m["curr"], 3)
        self.assertFalse(m["comparable"])
        self.assertIsNone(m["delta"])

    def test_sum_metric_is_none_if_any_part_missing(self):
        self.assertIsNone(mv.read_metric(snap(account={"critical": 5}), mv._METRIC["inspector_ch"]))

    def test_pct_none_when_previous_is_zero(self):
        m = by_key(mv.count_movements(snap(github={"secrets_total": 0}), snap(github={"secrets_total": 4})), "gh_secrets_total")
        self.assertEqual(m["delta"], 4)
        self.assertIsNone(m["pct"])

    def test_bool_is_not_a_number(self):
        self.assertIsNone(mv.read_metric(snap(github={"vuln_total": True}), mv._METRIC["gh_vuln_total"]))


class TestDataQuality(unittest.TestCase):
    def flags(self, prev, curr):
        return mv.data_quality(prev, curr, mv.count_movements(prev, curr))

    def test_outlier_on_headline_rise_only(self):
        f = self.flags(snap(account={"critical": 10, "high": 10}), snap(account={"critical": 20, "high": 20}))
        self.assertEqual([x["kind"] for x in f], ["outlier"])
        f = self.flags(snap(account={"critical": 20, "high": 20}), snap(account={"critical": 0, "high": 0}))
        self.assertEqual(f, [])  # a fall to zero is not flagged
        f = self.flags(snap(account={"critical": 10, "high": 10, "medium": 1}), snap(account={"critical": 10, "high": 10, "medium": 9}))
        self.assertEqual(f, [])  # medium is not a headline

    def test_critical_counts_flag_only_on_a_material_rise(self):
        f = self.flags(snap(github={"vuln_critical": 44}), snap(github={"vuln_critical": 156}))
        self.assertEqual([x["key"] for x in f if x["kind"] == "outlier"], ["gh_vuln_critical"])
        f = self.flags(snap(github={"vuln_critical": 2}), snap(github={"vuln_critical": 5}))
        self.assertEqual(f, [])  # +150% on three alerts is noise
        counts = mv.count_movements(snap(), snap())
        self.assertTrue(by_key(counts, "inspector_critical")["headline"] and by_key(counts, "gh_vuln_critical")["headline"])

    def test_not_comparable_flag_only_when_one_side_has_it(self):
        self.assertEqual(self.flags(snap(), snap()), [])
        f = self.flags(snap(), snap(github={"vuln_total": 5}))
        self.assertIn("not_comparable", [x["kind"] for x in f])

    def test_failed_capture_is_flagged(self):
        f = self.flags(snap(), snap(extra_raw={"first_seen": {"status": "failed: ThrottlingException"}}))
        self.assertEqual([x["key"] for x in f if x["kind"] == "capture_status"], ["first_seen"])

    def test_inventory_flag_both_directions(self):
        for a, b in ((100, 125), (100, 75)):
            f = self.flags(snap(coverage={"AWS_ECR_CONTAINER_IMAGE": a}), snap(coverage={"AWS_ECR_CONTAINER_IMAGE": b}))
            self.assertIn("inventory", [x["kind"] for x in f], (a, b))
        f = self.flags(snap(coverage={"AWS_ECR_CONTAINER_IMAGE": 100}), snap(coverage={"AWS_ECR_CONTAINER_IMAGE": 110}))
        self.assertNotIn("inventory", [x["kind"] for x in f])


class TestInspector(unittest.TestCase):
    def test_decomposition_identity(self):
        p = snap(account={"critical": 0, "high": 1100}, repos={"a": (600, 3), "b": (400, 2)})
        c = snap(account={"critical": 0, "high": 1800}, repos={"a": (900, 3), "b": (800, 4)})
        d = mv.inspector_decomposition(p, c)
        self.assertEqual((d["prev"]["images"], d["curr"]["images"]), (5, 7))
        self.assertEqual((d["prev"]["per_image"], d["curr"]["per_image"]), (200.0, 242.9))
        self.assertEqual((d["prev"]["non_ecr_ch"], d["curr"]["non_ecr_ch"]), (100, 100))
        self.assertAlmostEqual(d["images_ratio"] * d["per_image_ratio"], d["ecr_ch_ratio"], places=2)

    def test_decomposition_none_without_repositories(self):
        self.assertIsNone(mv.inspector_decomposition(snap(), snap(repos={"a": (1, 1)})))

    def test_held_layers_prefer_the_full_list(self):
        full_p = [{"layer": "L9", "images": 2, "c": 0, "h": 10, "repo_list": []}]
        full_c = [{"layer": "L9", "images": 2, "c": 0, "h": 30, "repo_list": []}]
        p = snap(layers={"L1": (100, 5)}, extra_raw={"layers": full_p})
        c = snap(layers={"L1": (150, 5)}, extra_raw={"layers": full_c})
        h = mv.held_layers(p, c)
        self.assertTrue(h["complete"])
        self.assertEqual([x["layer"] for x in h["layers"]], ["L9"])
        h = mv.held_layers(snap(layers={"L1": (100, 5)}, extra_raw={"layers": full_p}), snap(layers={"L1": (150, 5)}))
        self.assertFalse(h["complete"])  # one side lacks the full list: fall back to the top layers
        self.assertEqual([x["layer"] for x in h["layers"]], ["L1"])

    def test_held_layers_need_same_digest_and_image_count(self):
        p = snap(layers={"L1": (100, 5), "L2": (100, 5), "L3": (100, 5)})
        c = snap(layers={"L1": (150, 5), "L2": (900, 6), "L4": (100, 5)})
        h = mv.held_layers(p, c)
        self.assertEqual([x["layer"] for x in h["layers"]], ["L1"])
        self.assertEqual((h["prev_ch"], h["curr_ch"], h["pct"]), (100, 150, 50.0))

    def test_repo_stability_is_context(self):
        s = mv.repo_image_stability(snap(repos={"a": (100, 3), "b": (100, 2)}), snap(repos={"a": (130, 3), "b": (500, 4)}))
        self.assertEqual((s["repos"], s["prev_ch"], s["curr_ch"]), (1, 100, 130))


class TestMovers(unittest.TestCase):
    MANAGERS = [{"package": "linux", "manager": "OS"}, {"package": "axios", "manager": "NODE"},
                {"package": "perl", "manager": "OS"}, {"package": "nodejs/node", "manager": "GENERIC"},
                {"package": "pyjwt", "manager": "PYTHON"}]

    def test_package_groups_by_fixing_action(self):
        p = snap(packages={"linux": 100, "axios": 10, "perl": 5, "nodejs/node": 50, "pyjwt": 1}, repos={})
        c = snap(packages={"linux": 160, "axios": 40, "perl": 15, "nodejs/node": 57, "pyjwt": 3, "newpkg": 10}, repos={},
                 zone_a={"axios"}, extra_raw={"package_managers": self.MANAGERS})
        m = mv.movers(p, c)
        groups = {g["group"]: g["delta"] for g in m["package_groups"]}
        self.assertEqual(groups, {"kernel headers": 60, "OS packages": 10, "bundled runtimes and binaries": 7,
                                  "application dependencies": 32, "unknown": 10})
        self.assertEqual([g["group"] for g in m["package_groups"]], list(mv.GROUPS))  # report order
        self.assertEqual(sum(g["delta"] for g in m["package_groups"]), sum(x["delta"] for x in m["packages"]))
        self.assertTrue(all(g["fix"] for g in m["package_groups"]))
        axios = next(x for x in m["packages"] if x["package"] == "axios")
        self.assertTrue(axios["github"])
        self.assertFalse(next(x for x in m["packages"] if x["package"] == "perl")["github"])
        self.assertIsNone(next(x for x in m["packages"] if x["package"] == "newpkg")["prev_ch"])
        self.assertTrue(m["managers_captured"])

    def test_kernel_name_beats_its_os_manager(self):
        self.assertEqual(mv.package_group("linux-libc-dev", {"linux-libc-dev": "OS"}), "kernel headers")
        self.assertEqual(mv.package_group("weird", {"weird": "SOMETHING_NEW"}), "unknown")
        self.assertEqual(mv.package_group("x", None), "unknown")

    def test_manager_maps_merge_and_current_wins(self):
        p = snap(packages={"gone": 5, "x": 1}, repos={}, extra_raw={"package_managers": [
            {"package": "gone", "manager": "NODE"}, {"package": "x", "manager": "OS"}]})
        c = snap(packages={"x": 2}, repos={}, extra_raw={"package_managers": [{"package": "x", "manager": "PYTHON"}]})
        groups = {g["group"]: g["delta"] for g in mv.movers(p, c)["package_groups"]}
        self.assertEqual(groups, {"application dependencies": -4})

    def test_no_maps_means_unknown_and_says_so(self):
        m = mv.movers(snap(packages={"perl": 1}, repos={}), snap(packages={"perl": 2}, repos={}))
        self.assertFalse(m["managers_captured"])
        self.assertEqual(m["package_groups"][0]["group"], "unknown")

    def test_repo_movers_sorted_by_absolute_change(self):
        m = mv.movers(snap(repos={"a": (100, 1), "b": (500, 1)}, packages={}), snap(repos={"a": (130, 1), "b": (100, 1)}, packages={}))
        self.assertEqual([r["repo"] for r in m["repos"]], ["b", "a"])


class TestGithubAndCorrelation(unittest.TestCase):
    def test_instances_vs_distinct(self):
        p = snap(gh_alerts=[{"package": "x", "cve": "C1", "state": "OPEN"}])
        c = snap(gh_alerts=[{"package": "x", "cve": "C1", "state": "OPEN"}, {"package": "x", "cve": "C1", "state": "OPEN"},
                            {"package": "y", "cve": None, "summary": "S", "state": "OPEN"},
                            {"package": "y", "cve": None, "summary": "S", "state": "OPEN"},
                            {"package": "y", "cve": None, "summary": "S", "state": "OPEN"},
                            {"package": "z", "cve": "C9", "state": "DISMISSED"}])
        g = mv.instances_vs_distinct(p, c)
        self.assertEqual((g["prev_instances"], g["curr_instances"]), (1, 5))
        self.assertEqual((g["prev_distinct"], g["curr_distinct"], g["new_distinct"]), (1, 2, 1))
        self.assertEqual(g["top_new"][0], {"package": "y", "advisory": "S", "instances": 3})

    def test_correlation_entered_and_left(self):
        c = mv.correlation_movement(snap(zone_a={"a", "b"}), snap(zone_a={"b", "c"}))
        self.assertEqual((c["entered"], c["left"]), (["c"], ["a"]))


class TestFixturePair(unittest.TestCase):
    """End to end on the masked 2026-09-23 → 2026-10-07 pair: must reproduce the hand analysis of 2026-10-08."""

    def setUp(self):
        self.mv = mv.security_movement(em.load(PAIR / "20260923"), em.load(PAIR / "20261007"), "20260923", "20261007")

    def test_reproduces_the_hand_breakdown(self):
        d = self.mv["inspector"]
        self.assertEqual((d["prev"]["images"], d["curr"]["images"]), (359, 381))
        self.assertEqual((d["prev"]["per_image"], d["curr"]["per_image"]), (215.0, 255.8))
        self.assertEqual(by_key(self.mv["counts"], "inspector_ch")["delta"], 19106)
        s = self.mv["repo_image_stability"]
        self.assertEqual((s["repos"], s["curr_ch"] - s["prev_ch"]), (36, 11208))
        groups = {g["group"]: g["delta"] for g in self.mv["movers"]["package_groups"]}
        self.assertEqual(groups["kernel headers"], 11718)

    def test_renders_without_captures(self):
        out = md.render_movement_markdown(self.mv)
        self.assertIn("First seen: not available", out)
        self.assertIn("×1.061", out)


class TestMarkdown(unittest.TestCase):
    def setUp(self):
        self.mv = mv.security_movement(snap(), snap(), "20260101", "20260115")

    def test_notes_below_marker_survive_regeneration(self):
        first = md.render_movement_markdown(self.mv)
        edited = first.replace(md.WHY_STUB, "## Why it moved\n\nThe feed update did it.")
        again = md.render_movement_markdown(self.mv, edited)
        self.assertIn("The feed update did it.", again)
        self.assertNotIn("_Not yet written._", again)
        self.assertEqual(again.count(md.GENERATED_MARKER), 1)

    def test_file_without_marker_is_preserved_whole(self):
        out = md.render_movement_markdown(self.mv, "hand-written notes")
        self.assertTrue(out.rstrip().endswith("hand-written notes"))

    def test_stub_on_first_write(self):
        self.assertIn("_Not yet written._", md.render_movement_markdown(self.mv, ""))

    def test_missing_values_render_as_dash_not_zero(self):
        out = md.render_movement_markdown(self.mv)
        self.assertIn("| **Inspector critical + high** | – | – | – | – |", out)


class TestCaptureRendering(unittest.TestCase):
    def test_captures_render_with_flagged_repo(self):
        fs = {"status": "ok", "basis_snapshot": "20260923", "total": 120,
              "ecr": {"existing_images": 20, "images_existing": 2, "pushed_since": 100, "images_pushed_since": 7}}
        rb = {"status": "ok", "flag_rule": "rule", "totals": {"old_images": 4, "old_ch": 400, "new_images": 2, "new_ch": 600},
              "repos": [{"repo": "ns/a", "flagged": True}, {"repo": "ns/b", "flagged": False}]}
        m = mv.security_movement(snap(), snap(extra_raw={"first_seen": fs, "rebuild_comparison": rb}))
        out = md.render_movement_markdown(m)
        self.assertIn("On images that existed before the window: 20 (2 images)", out)
        self.assertIn("older 100 per image (4 images), pushed in window 300 (2 images)", out)
        self.assertIn("Flagged (rule): ns/a.", out)
        self.assertNotIn("ns/b", out)


class TestResolveTargets(unittest.TestCase):
    DATES = ["20260801", "20260826", "20260909", "20260923", "20261007"]

    def test_default_is_previous_plus_30_day_basis(self):
        r = em.resolve_targets(self.DATES)
        self.assertEqual(r, {"date": "20261007", "pairs": [("20260923", "movement.md"), ("20260826", "movement-vs-20260826.md")]})

    def test_long_basis_is_newest_at_least_30_days_back(self):
        self.assertEqual(em.long_basis(self.DATES, "20261007"), "20260826")
        self.assertEqual(em.long_basis(["20260907", "20260908"], "20261007"), "20260907")
        self.assertIsNone(em.long_basis(["20260908"], "20261007"))

    def test_no_second_file_when_long_basis_is_the_previous(self):
        r = em.resolve_targets(["20260801", "20261007"])
        self.assertEqual(r["pairs"], [("20260801", "movement.md")])

    def test_compare_to_gets_its_own_file(self):
        self.assertEqual(em.resolve_targets(self.DATES, compare_to="20260801")["pairs"], [("20260801", "movement-vs-20260801.md")])
        self.assertEqual(em.resolve_targets(self.DATES, compare_to="20260923")["pairs"], [("20260923", "movement.md")])

    def test_errors_and_skips(self):
        self.assertIn("skip", em.resolve_targets(["20261007"]))
        self.assertIn("error", em.resolve_targets([]))
        self.assertIn("error", em.resolve_targets(self.DATES, target="20990101"))
        self.assertIn("error", em.resolve_targets(self.DATES, target="20260909", compare_to="20260923"))
        self.assertIn("error", em.resolve_targets(self.DATES, compare_to="20250101"))

    def test_older_target(self):
        r = em.resolve_targets(self.DATES, target="20260909")
        self.assertEqual(r["pairs"][0], ("20260826", "movement.md"))


if __name__ == "__main__":
    unittest.main()
