"""Running but not scanned: the capture (scan_coverage), the lapse date, the
derived gaps (movement.scan_gaps), the page rows and the fixture mask. All
inputs are synthesised here; nothing asserts on production data."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest.mock as mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
with mock.patch("config_util.load_config", return_value={"aws_profile": "p", "aws_region": "r", "github_org": "o"}):
    import posture_snapshot as ps  # noqa: E402
import fixture_mask as fm  # noqa: E402
import movement as mv  # noqa: E402
import movement_page as mp  # noqa: E402

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
W30 = {"push": "DAYS_30", "use": "DAYS_30", "mode": "LAST_IN_USE_AT"}
D = {n: "sha256:" + c * 64 for n, c in (("a", "a"), ("b", "b"), ("idx", "c"), ("amd", "d"), ("arm", "e"), ("att", "f"))}


def denied(op):
    return ps.ClientError({"Error": {"Code": "AccessDeniedException"}}, op)


class TestLapseAt(unittest.TestCase):
    def test_push_date_alone_sets_it_for_an_image_never_seen_running(self):
        self.assertEqual(ps.lapse_at(W30, T0, None, T0 + timedelta(days=60)), T0 + timedelta(days=30))

    def test_the_later_of_push_and_last_use_wins(self):
        self.assertEqual(ps.lapse_at(W30, T0, T0 + timedelta(days=10), None), T0 + timedelta(days=40))
        self.assertEqual(ps.lapse_at(W30, T0 + timedelta(days=10), T0, None), T0 + timedelta(days=40))

    def test_each_window_is_its_own(self):
        w = {"push": "DAYS_14", "use": "DAYS_90", "mode": "LAST_IN_USE_AT"}
        self.assertEqual(ps.lapse_at(w, T0, T0, None), T0 + timedelta(days=90))
        self.assertEqual(ps.lapse_at(w, T0, None, None), T0 + timedelta(days=14))

    def test_pull_mode_reads_the_pull_date_not_in_use(self):
        w = {**W30, "mode": "LAST_PULL_DATE"}
        self.assertEqual(ps.lapse_at(w, T0, T0 + timedelta(days=50), T0 + timedelta(days=5)), T0 + timedelta(days=35))

    def test_lifetime_never_lapses(self):
        self.assertIsNone(ps.lapse_at({**W30, "push": "LIFETIME"}, T0, T0, None))

    def test_unknown_window_raises_rather_than_guess(self):
        with self.assertRaises(ValueError):
            ps.lapse_at({**W30, "use": "WEEKS_2"}, T0, T0, None)

    def test_no_dates_no_lapse(self):
        self.assertIsNone(ps.lapse_at(W30, None, None, None))


def cov(repo, digest, status="ACTIVE", reason="SUCCESSFUL", in_use=None, last_in_use=None):
    img = {}
    if in_use is not None:
        img["inUseCount"] = in_use
    if last_in_use is not None:
        img["lastInUseAt"] = last_in_use
    return {"resourceId": f"arn:aws:ecr:r:0:repository/{repo}/{digest}",
            "resourceMetadata": {"ecrRepository": {"name": repo}, "ecrImage": img},
            "scanStatus": {"statusCode": status, "reason": reason}, "lastScannedAt": T0}


class Inspector:
    def __init__(self, pages, windows=("DAYS_30", "DAYS_30", "LAST_IN_USE_AT"), fail=None):
        self.pages, self.windows, self.fail = pages, windows, fail

    def get_configuration(self):
        if self.fail == "config":
            raise denied("GetConfiguration")
        p, u, m = self.windows
        return {"ecrConfiguration": {"rescanDurationState": {"rescanDuration": p, "pullDateRescanDuration": u,
                                                             "pullDateRescanMode": m}}}

    def list_coverage(self, nextToken=None, **kw):
        if self.fail == "coverage":
            raise denied("ListCoverage")
        i = int(nextToken or 0)
        out = {"coveredResources": self.pages[i]}
        if i + 1 < len(self.pages):
            out["nextToken"] = str(i + 1)
        return out


class Ecr:
    def __init__(self, details, manifests=None, fail=None):
        self.details, self.manifests, self.fail = details, manifests or {}, fail

    def describe_images(self, repositoryName, **kw):
        if self.fail == "describe":
            raise denied("DescribeImages")
        return {"imageDetails": [d for d in self.details if d["_repo"] == repositoryName]}

    def batch_get_image(self, repositoryName, imageIds, acceptedMediaTypes):
        if self.fail == "manifest":
            raise denied("BatchGetImage")
        m = self.manifests.get(imageIds[0]["imageDigest"])
        return {"images": [{"imageManifest": json.dumps(m)}] if m else []}


def detail(repo, digest, pushed=T0, pulled=None, media="application/vnd.oci.image.manifest.v1+json"):
    return {"_repo": repo, "imageDigest": digest, "imagePushedAt": pushed, "lastRecordedPullTime": pulled,
            "imageManifestMediaType": media}


class Lambda:
    """fns: (name, package type, $LATEST image uri). aliases: {name: [(alias, version)]};
    versions: {(name, version): image uri}. deny: names (or "name:version") GetFunction refuses."""
    def __init__(self, fns, fail=None, aliases=None, versions=None, deny=()):
        self.fns, self.fail, self.aliases, self.versions, self.deny = fns, fail, aliases or {}, versions or {}, deny

    def get_paginator(self, op):
        if self.fail == "list":
            raise denied("ListFunctions")
        stub = self

        class P:
            def paginate(self, FunctionName=None):
                if op == "list_functions":
                    return [{"Functions": [{"FunctionName": n, "PackageType": t} for n, t, _ in stub.fns]}]
                if stub.fail == "aliases":
                    raise denied("ListAliases")
                return [{"Aliases": [{"Name": a, "FunctionVersion": v} for a, v in stub.aliases.get(FunctionName, [])]}]
        return P()

    def get_function(self, FunctionName, Qualifier=None):
        key = FunctionName if Qualifier is None else f"{FunctionName}:{Qualifier}"
        if key in self.deny:
            raise ps.ClientError({"Error": {"Code": "ResourceNotFoundException"}}, "GetFunction")
        uri = (next(u for n, _, u in self.fns if n == FunctionName) if Qualifier is None
               else self.versions[(FunctionName, Qualifier)])
        return {"Code": {"ResolvedImageUri": uri}, "Configuration": {"LastModified": "2026-10-26T11:50:25.000+0000"}}


def uri(repo, digest):
    return f"0.dkr.ecr.r.amazonaws.com/{repo}@{digest}"


INDEX = "application/vnd.docker.distribution.manifest.list.v2+json"


class TestScanCoverage(unittest.TestCase):
    def capture(self, inspector=None, ecr=None, lam=None):
        inspector = inspector or Inspector([[cov("ns/a", D["a"])], [cov("ns/b", D["b"], "INACTIVE", "SCAN_ELIGIBILITY_EXPIRED")]])
        ecr = ecr or Ecr([detail("ns/a", D["a"]), detail("ns/b", D["b"], pushed=T0 - timedelta(days=90))])
        lam = lam or Lambda([("fn-b", "Image", uri("ns/b", D["b"])), ("zip", "Zip", None)])
        with mock.patch("sys.stderr"):
            return ps.scan_coverage(inspector, ecr, lam)

    def test_records_every_image_across_pages_with_its_dates_and_lapse(self):
        r = self.capture()
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["windows"], W30)
        self.assertEqual([i["repo"] for i in r["images"]], ["ns/a", "ns/b"])
        a = r["images"][0]
        self.assertEqual(a["pushed_at"], T0.isoformat())
        self.assertEqual(a["lapse_at"], (T0 + timedelta(days=30)).isoformat())
        self.assertFalse(a["index"])

    def test_dates_are_stored_in_utc(self):
        dubai = timezone(timedelta(hours=4))
        r = self.capture(ecr=Ecr([detail("ns/a", D["a"], pushed=T0.astimezone(dubai)), detail("ns/b", D["b"])]))
        self.assertTrue(r["images"][0]["pushed_at"].endswith("+00:00"))

    def test_container_lambdas_carry_their_image_scan_status(self):
        (f,) = self.capture()["functions"]  # the zip function is not a container Lambda
        self.assertEqual((f["function"], f["repo"], f["digest"], f["status"]),
                         ("fn-b", "ns/b", D["b"], "INACTIVE"))
        self.assertEqual(f["lapse_at"], (T0 - timedelta(days=60)).isoformat())

    def test_a_lambda_image_inspector_never_saw_is_named_so(self):
        (f,) = self.capture(lam=Lambda([("fn-x", "Image", uri("ns/x", D["amd"]))]))["functions"]
        self.assertEqual(f["status"], "NOT_IN_COVERAGE")

    def test_an_alias_on_an_older_image_gets_its_own_row(self):
        lam = Lambda([("fn-b", "Image", uri("ns/a", D["a"]))],
                     aliases={"fn-b": [("live", "3"), ("same", "4"), ("dev", "$LATEST")]},
                     versions={("fn-b", "3"): uri("ns/b", D["b"]), ("fn-b", "4"): uri("ns/a", D["a"])})
        rows = self.capture(lam=lam)["functions"]
        self.assertEqual([(r["function"], r["status"]) for r in rows], [("fn-b", "ACTIVE"), ("fn-b:3", "INACTIVE")])

    def test_one_unreadable_function_costs_only_its_row(self):
        lam = Lambda([("gone", "Image", uri("ns/a", D["a"])), ("fn-b", "Image", uri("ns/b", D["b"]))], deny=("gone",))
        r = self.capture(lam=lam)
        self.assertEqual(r["status"], "ok")
        self.assertEqual([(f["function"], f["status"], f["reason"]) for f in r["functions"]],
                         [("fn-b", "INACTIVE", "SCAN_ELIGIBILITY_EXPIRED"), ("gone", "UNREAD", "ResourceNotFoundException")])

    def test_unreadable_aliases_are_a_row_not_silence(self):
        rows = self.capture(lam=Lambda([("fn-b", "Image", uri("ns/b", D["b"]))], fail="aliases"))["functions"]
        self.assertEqual([(r["function"], r["status"]) for r in rows], [("fn-b", "INACTIVE"), ("fn-b:aliases", "UNREAD")])

    def test_an_image_covered_under_another_repo_is_still_found(self):
        (f,) = self.capture(lam=Lambda([("fn-x", "Image", uri("other/repo", D["b"]))]))["functions"]
        self.assertEqual((f["status"], f["reason"]), ("INACTIVE", "SCAN_ELIGIBILITY_EXPIRED"))

    def test_a_digest_in_two_repos_takes_the_copy_still_rescanned(self):
        # The lapsed copy sits in the repo that sorts first, so "first listed" picks it.
        for order in ([cov("ns/a", D["b"], "INACTIVE", "SCAN_ELIGIBILITY_EXPIRED"), cov("ns/b", D["b"])],
                      [cov("ns/b", D["b"]), cov("ns/a", D["b"], "INACTIVE", "SCAN_ELIGIBILITY_EXPIRED")]):
            r = self.capture(inspector=Inspector([order]), ecr=Ecr([detail("ns/a", D["b"]), detail("ns/b", D["b"])]),
                             lam=Lambda([("fn-x", "Image", uri("other/repo", D["b"]))]))
            self.assertEqual(r["functions"][0]["status"], "ACTIVE")

    def test_an_absent_use_window_counts_push_only(self):
        r = self.capture(inspector=Inspector([[cov("ns/a", D["a"], in_use=1, last_in_use=T0 + timedelta(days=20))]],
                                             windows=("DAYS_30", None, None)), lam=Lambda([]))
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["images"][0]["lapse_at"], (T0 + timedelta(days=30)).isoformat())

    def test_a_failed_lambda_read_keeps_the_images(self):
        r = self.capture(lam=Lambda([], fail="list"))
        self.assertEqual(r["status"], "failed: functions: AccessDeniedException")
        self.assertEqual([i["repo"] for i in r["images"] or []], ["ns/a", "ns/b"])
        self.assertIsNone(r["functions"])

    def test_a_failed_image_read_leaves_everything_empty(self):
        for inspector, ecr, want in ((Inspector([[]], fail="config"), None, "failed: images: AccessDeniedException"),
                                     (Inspector([[]], fail="coverage"), None, "failed: images: AccessDeniedException"),
                                     (None, Ecr([], fail="describe"), "failed: images: ns/a: AccessDeniedException"),
                                     (Inspector([[]], windows=("DAYS_30", "WEEKS_2", "LAST_IN_USE_AT")), None,
                                      "failed: images: unknown rescan window 'WEEKS_2'")):
            r = self.capture(inspector=inspector, ecr=ecr)
            self.assertEqual(r["status"], want)
            self.assertIsNone(r["images"])
            self.assertIsNone(r["functions"])

    def test_an_image_index_records_its_platform_images_without_attestations(self):
        man = {"manifests": [{"digest": D["amd"], "platform": {"os": "linux", "architecture": "amd64"}},
                             {"digest": D["arm"], "platform": {"os": "linux", "architecture": "arm64", "variant": "v8"}},
                             {"digest": D["att"], "platform": {"os": "unknown", "architecture": "unknown"},
                              "annotations": {"vnd.docker.reference.type": "attestation-manifest"}}]}
        r = self.capture(inspector=Inspector([[cov("ns/i", D["idx"], "INACTIVE", "UNSUPPORTED_MEDIA_TYPE", in_use=5)]]),
                         ecr=Ecr([detail("ns/i", D["idx"], media=INDEX)], {D["idx"]: man}), lam=Lambda([]))
        (i,) = r["images"]
        self.assertTrue(i["index"])
        self.assertEqual(i["platforms"], [{"digest": D["amd"], "platform": "linux/amd64"},
                                          {"digest": D["arm"], "platform": "linux/arm64/v8"}])

    def test_a_failed_platform_read_costs_only_that_row(self):
        r = self.capture(inspector=Inspector([[cov("ns/i", D["idx"], in_use=1)]]),
                         ecr=Ecr([detail("ns/i", D["idx"], media=INDEX)], fail="manifest"), lam=Lambda([]))
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["images"][0]["index"])
        self.assertIsNone(r["images"][0]["platforms"])


def image(repo, digest, status="ACTIVE", reason="SUCCESSFUL", in_use=None, lapse=None, index=False, platforms=None):
    return {"repo": repo, "digest": digest, "status": status, "reason": reason, "in_use_count": in_use,
            "lapse_at": lapse.isoformat() if lapse else None, "index": index, "platforms": platforms}


def snap(images, functions=(), at="2026-11-06 16:00 UTC", archs=("x86_64",), node_status="ok", others=0, other_archs=()):
    return {"raw": {"generated_at": at,
                    "node_os": {"status": node_status, "nodes": [{"arch": a} for a in archs],
                                "other_instances": others, "other_archs": None if other_archs is None else list(other_archs)},
                    "scan_coverage": {"status": "ok", "windows": W30, "images": list(images),
                                      "functions": None if functions is None else list(functions)}}}


AT = datetime(2026, 11, 6, 16, 0, tzinfo=timezone.utc)


class TestScanGaps(unittest.TestCase):
    def test_absent_or_failed_capture_is_none_not_an_all_clear(self):
        self.assertIsNone(mv.scan_gaps({"raw": {"generated_at": "2026-11-06 16:00 UTC"}}))
        self.assertIsNone(mv.scan_gaps({"raw": {"generated_at": "2026-11-06 16:00 UTC",
                                                "scan_coverage": {"status": "failed: images: X", "images": None}}}))
        self.assertIsNone(mv.scan_gaps({"raw": {"scan_coverage": {"images": []}}}))  # no capture time

    def test_lists_running_workloads_that_are_not_rescanned(self):
        g = mv.scan_gaps(snap(
            [image("ns/run", D["a"], "INACTIVE", "SCAN_ELIGIBILITY_EXPIRED", in_use=2),
             image("ns/idle", D["b"], "INACTIVE", "SCAN_ELIGIBILITY_EXPIRED", in_use=0),
             image("ns/never", D["b"], "INACTIVE", "SCAN_ELIGIBILITY_EXPIRED")],
            [{"function": "fn-1", "repo": "ns/l", "digest": D["a"], "status": "INACTIVE",
              "reason": "SCAN_ELIGIBILITY_EXPIRED", "lapse_at": None}]))
        self.assertEqual([(r["kind"], r["name"]) for r in g["not_scanned"]], [("cluster", "ns/run"), ("lambda", "fn-1")])
        self.assertEqual(g["running"], 2)  # idle and never-run images are not running

    def test_lapsing_is_measured_from_the_capture_time_not_the_clock(self):
        inside = image("ns/soon", D["a"], in_use=1, lapse=AT + timedelta(days=mv.LAPSE_SOON_DAYS))
        outside = image("ns/later", D["b"], in_use=1, lapse=AT + timedelta(days=mv.LAPSE_SOON_DAYS, minutes=1))
        g = mv.scan_gaps(snap([outside, inside]))
        self.assertEqual([r["name"] for r in g["lapsing"]], ["ns/soon"])
        self.assertEqual(g["not_scanned"], [])
        self.assertEqual(g["as_of"], AT.isoformat())

    def test_a_running_index_is_judged_by_the_platform_its_nodes_run(self):
        idx = image("ns/curl", D["idx"], "INACTIVE", "UNSUPPORTED_MEDIA_TYPE", in_use=5, index=True,
                    platforms=[{"digest": D["amd"], "platform": "linux/amd64"}, {"digest": D["arm"], "platform": "linux/arm64"}])
        kids = [image("ns/curl", D["amd"], "INACTIVE", "SCAN_ELIGIBILITY_EXPIRED"), image("ns/curl", D["arm"])]
        g = mv.scan_gaps(snap([idx, *kids]))
        self.assertEqual([(r["name"], r["digest"]) for r in g["not_scanned"]], [("ns/curl (linux/amd64)", D["amd"])])
        g = mv.scan_gaps(snap([idx, *kids], archs=("aarch64",)))
        self.assertEqual(g["not_scanned"], [])  # arm64 is scanned
        g = mv.scan_gaps(snap([idx, *kids], node_status="failed: X"))  # node archs unknown: every platform checked
        self.assertEqual([r["digest"] for r in g["not_scanned"]], [D["amd"]])
        self.assertEqual(g["running"], 2)

    def test_non_bottlerocket_hosts_add_their_architecture(self):
        idx = image("ns/curl", D["idx"], in_use=5, index=True,
                    platforms=[{"digest": D["amd"], "platform": "linux/amd64"}, {"digest": D["arm"], "platform": "linux/arm64"}])
        kids = [image("ns/curl", D["amd"]), image("ns/curl", D["arm"], "INACTIVE", "SCAN_ELIGIBILITY_EXPIRED")]
        self.assertEqual(mv.scan_gaps(snap([idx, *kids]))["not_scanned"], [])  # x86 only: arm64 is not run
        g = mv.scan_gaps(snap([idx, *kids], others=1, other_archs=["arm64"]))
        self.assertEqual([r["digest"] for r in g["not_scanned"]], [D["arm"]])
        for unknown in (dict(others=1, other_archs=None), dict(others=1, other_archs=[None]), dict(others=1, other_archs=[])):
            g = mv.scan_gaps(snap([idx, *kids], **unknown))  # an unknown host architecture: check every platform
            self.assertEqual([r["digest"] for r in g["not_scanned"]], [D["arm"]], unknown)

    def test_a_running_index_with_unread_platforms_is_listed_as_unknown(self):
        g = mv.scan_gaps(snap([image("ns/i", D["idx"], "INACTIVE", "UNSUPPORTED_MEDIA_TYPE", in_use=1, index=True)]))
        self.assertEqual([r["status"] for r in g["not_scanned"]], ["PLATFORMS_UNKNOWN"])

    def test_a_platform_inspector_never_recorded_is_not_scanned(self):
        idx = image("ns/i", D["idx"], in_use=1, index=True, platforms=[{"digest": D["amd"], "platform": "linux/amd64"}])
        self.assertEqual([r["status"] for r in mv.scan_gaps(snap([idx]))["not_scanned"]], ["NOT_IN_COVERAGE"])

    def test_unread_lambdas_are_said_so(self):
        self.assertFalse(mv.scan_gaps(snap([], functions=None))["functions_measured"])
        self.assertTrue(mv.scan_gaps(snap([]))["functions_measured"])

    def test_failed_capture_is_flagged(self):
        flags = mv.data_quality({}, {"raw": {"scan_coverage": {"status": "failed: functions: AccessDenied"}}}, [])
        self.assertEqual([f["key"] for f in flags], ["scan_coverage"])


class TestPageRows(unittest.TestCase):
    def test_rows_say_what_happened_in_words(self):
        g = mv.scan_gaps(snap(
            [image("ns/i", D["idx"], in_use=1, index=True)],
            [{"function": "fn-1", "repo": "ns/l", "digest": D["a"], "status": "INACTIVE",
              "reason": "SCAN_ELIGIBILITY_EXPIRED", "lapse_at": "2026-08-01T06:44:57+00:00"},
             {"function": "fn-2", "repo": "ns/x", "digest": D["b"], "status": "NOT_IN_COVERAGE",
              "reason": None, "lapse_at": None}]))
        v = mp._scan_gaps({"scan_gaps": g})
        self.assertEqual((v["push_days"], v["use_days"], v["mode"], v["soon_days"]), (30, 30, "LAST_IN_USE_AT", 14))
        rows = {r["name"]: r for r in v["not_scanned"]}
        self.assertEqual(rows["fn-1"], {"kind": "Lambda", "name": "fn-1", "image": "ns/l@" + "a" * 12,
                                        "why": "rescanning lapsed: a Lambda, which Inspector never sees as running",
                                        "lapse": "2026-08-01"})
        self.assertEqual(rows["fn-2"]["why"], "Inspector has no record of this image")
        self.assertIn("could not be read", rows["ns/i"]["why"])
        unread = mp._scan_gaps({"scan_gaps": mv.scan_gaps(snap([], [{"function": "fn-3", "repo": None, "digest": None,
                                 "status": "UNREAD", "reason": "ResourceNotFoundException", "lapse_at": None}]))})
        self.assertEqual(unread["not_scanned"][0]["why"], "could not be read (ResourceNotFoundException)")
        self.assertEqual(unread["not_scanned"][0]["image"], "–")
        self.assertEqual(rows["ns/i"]["kind"], "Cluster")

    def test_a_lapsing_row_says_why_it_lapses_not_inspectors_status(self):
        soon = AT + timedelta(days=5)
        g = mv.scan_gaps(snap(
            [image("ns/run", D["a"], in_use=1, lapse=soon),
             image("ns/i", D["idx"], in_use=1, index=True, platforms=[{"digest": D["amd"], "platform": "linux/amd64"}]),
             image("ns/i", D["amd"], lapse=soon)],
            [{"function": "fn-1", "repo": "ns/l", "digest": D["b"], "status": "ACTIVE",
              "reason": "SUCCESSFUL", "lapse_at": soon.isoformat()}]))
        rows = {r["name"]: r["why"] for r in mp._scan_gaps({"scan_gaps": g})["lapsing"]}
        self.assertEqual(rows, {"fn-1": "a Lambda, which Inspector never sees as running",
                                "ns/i (linux/amd64)": "built for several chip types, which Inspector never sees as running",
                                "ns/run": "rescanning follows the last time Inspector saw it running"})
        self.assertNotIn("successful", json.dumps(rows))
        # Any reason other than SUCCESSFUL still says something, so it stays.
        g["lapsing"][0]["reason"] = "PENDING_INITIAL_SCAN"
        first = mp._scan_gaps({"scan_gaps": g})["lapsing"][0]
        self.assertTrue(first["why"].endswith(" (pending initial scan)"), first["why"])
        g["lapsing"][0]["reason"] = "SUCCESSFUL"
        # Rescanning by pull date credits pulls, so neither cause applies.
        g["windows"] = {**W30, "mode": "LAST_PULL_DATE"}
        pulled = {r["name"]: r["why"] for r in mp._scan_gaps({"scan_gaps": g})["lapsing"]}
        self.assertEqual(set(pulled.values()), {"rescanning follows its upload date or last pull"})

    def test_no_capture_no_panel(self):
        self.assertIsNone(mp._scan_gaps({"scan_gaps": None}))


class TestMask(unittest.TestCase):
    def test_scan_coverage_identifiers_are_masked(self):
        raw = {"account": "999988887777", "scan_coverage": {
            "status": "ok", "windows": W30,
            "images": [{"repo": "acme/billing-api", "digest": D["idx"], "status": "ACTIVE", "reason": "SUCCESSFUL",
                        "pushed_at": "2026-10-01T00:00:00+00:00", "last_in_use_at": None, "last_pulled_at": None,
                        "last_scanned_at": None, "lapse_at": "2026-10-31T00:00:00+00:00", "index": True,
                        "platforms": [{"digest": D["amd"], "platform": "linux/amd64"}]}],
            "functions": [{"function": "BillingPresignup", "repo": "acme/billing-api", "digest": D["amd"],
                           "last_modified": "2026-10-26", "status": "ACTIVE", "reason": "SUCCESSFUL", "lapse_at": None}]}}
        masked, aliases = fm.mask_set({"20260101": {"raw.json": raw}})
        out = masked["20260101"]["raw.json"]["scan_coverage"]
        self.assertRegex(out["functions"][0]["function"], fm.ALIAS_PATTERNS["FUNCTION"])
        self.assertRegex(out["images"][0]["repo"], fm.ALIAS_PATTERNS["ECR_REPO"])
        self.assertRegex(out["images"][0]["platforms"][0]["digest"], fm.ALIAS_PATTERNS["LAYER"])
        # a platform digest and the Lambda running it keep the same alias
        self.assertEqual(out["images"][0]["platforms"][0]["digest"], out["functions"][0]["digest"])
        self.assertEqual(fm.find_leaks(masked, aliases), [])
        self.assertNotIn("BillingPresignup", json.dumps(masked))

    def test_a_leaked_function_name_is_caught(self):
        raw = {"scan_coverage": {"functions": [{"function": "BillingPresignup"}], "status": "BillingPresignup"}}
        masked, aliases = fm.mask_set({"20260101": {"raw.json": raw}})
        self.assertTrue(fm.find_leaks(masked, aliases))


if __name__ == "__main__":
    unittest.main()
