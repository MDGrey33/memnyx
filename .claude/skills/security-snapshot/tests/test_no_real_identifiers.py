"""No file outside the masked fixtures names the real account, org, AWS profile,
ECR namespace or repos. Examples and tests get written from real snapshots, and
the skill ships upstream. (The fixtures have their own check, test_fixtures_clean.)

The real values come from this machine: config.local.json, and every identifier
field (fixture_mask.FIELD_ROLES) in every snapshot in the reports folder. Each
source has its own test, and each skips, saying why, when its source is absent.
"""
import json
import os
import re
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fixture_mask as fm  # noqa: E402

SKILL = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", "fixtures"}


def reports_dir(cfg):
    env = os.environ.get("SECURITY_SNAPSHOT_REPORTS_DIR")
    if env:
        return Path(env)
    ws = SKILL.parents[2]  # <workspace>/.claude/skills/security-snapshot
    if not (ws / ".claude" / ".workspace").exists():
        return None
    scope = cfg.get("default_scope") or "workspace"
    return ws / "artifacts" / "security-snapshot" if scope == "workspace" else ws / "projects" / scope / "artifacts" / "security-snapshot"


def local_config():
    local = SKILL / "scripts" / "config.local.json"
    return json.loads(local.read_text() or "{}") if local.exists() else {}


def config_terms(cfg):
    return {v for v in (cfg.get("github_org"), cfg.get("aws_profile")) if v and v != "default"}


def snapshot_terms(cfg):
    """(substrings, hyphenated repo names) from every snapshot's identifier fields."""
    subs, names = set(), set()
    rd = reports_dir(cfg)
    dated = sorted(p for p in rd.iterdir() if p.name.isdigit()) if rd and rd.is_dir() else []
    for folder in dated:
        for fname in fm.SNAPSHOT_FILES:
            f = folder / fname
            if not f.exists():
                continue
            for path, v in fm.iter_strings(json.loads(f.read_text())):
                if not v.strip():
                    continue
                role = fm.FIELD_ROLES.get(f"{fname}:{path}")
                if role in ("ACCOUNT", "ORG"):
                    subs.add(v)
                elif role in ("REPO", "ECR_REPO"):
                    ns, name = fm._split_ecr(v)
                    if ns:
                        subs.add(ns + "/")
                    if "-" in name:  # single words (logger, media) are ordinary words; see fixture_mask.find_leaks
                        names.add(name)
    return subs, names


def find_real(text, subs, names):
    subs, names = {s for s in subs if s.strip("/ ")}, {n for n in names if n.strip()}  # an empty term matches everything
    low = text.lower()
    hits = {s for s in subs if s.lower() in low or s.lower().replace("/", "\\/") in low}  # also as written in a regex
    if names:
        pat = r"(?<![\w-])(" + "|".join(map(re.escape, sorted(names, key=len, reverse=True))) + r")(?![\w-])"
        hits |= set(re.findall(pat, text, re.IGNORECASE))
    return hits


def shipped_files():
    """Every text file, whatever its extension (tests/pre-commit has none)."""
    for p in sorted(SKILL.rglob("*")):
        rel = p.relative_to(SKILL)
        if p.is_file() and not SKIP_DIRS & set(rel.parts) and p.name != "config.local.json":
            try:
                yield rel, p.read_text()
            except UnicodeDecodeError:
                continue


def leaks(subs, names):
    files = list(shipped_files())
    assert len(files) > 20, "the walk found too few files to mean anything"
    # File names only: the hits themselves are the real values.
    return sorted(str(rel) for rel, text in files if find_real(text, subs, names))


class TestNoRealIdentifiers(unittest.TestCase):
    def test_the_search_finds_names_in_any_case_and_escaped(self):
        subs, names = {"acme-org", "acme/"}, {"svc-billing"}
        self.assertEqual(find_real('url = "github.com/ACME-ORG/x"', subs, names), {"acme-org"})
        self.assertEqual(find_real(r"/data-copy=\"acme\/svc-billing\"/", subs, names), {"acme/", "svc-billing"})
        self.assertEqual(find_real("# see SVC-Billing", subs, names), {"SVC-Billing"})
        self.assertEqual(find_real("svc-billing-v2 and my-svc-billing", subs, names), set())
        self.assertEqual(find_real("any text at all", {"", "/"}, {""}), set())

    def test_the_collector_reads_every_snapshot_and_both_captures(self):
        with tempfile.TemporaryDirectory() as d:
            for date, ecr, gh in (("20260901", "acme/svc-old-one", "svc-gh-only"), ("20261001", "acme/svc-new-one", "single")):
                (Path(d) / date).mkdir()
                (Path(d) / date / "raw.json").write_text(json.dumps(
                    {"account": "999988887777", "repositories": [{"repositoryAggregation": {"repository": ecr}}]}))
                (Path(d) / date / "github-raw.json").write_text(json.dumps({"vuln_alerts_detail": [{"repo": gh}]}))
            with mock.patch.dict(os.environ, {"SECURITY_SNAPSHOT_REPORTS_DIR": d}):
                subs, names = snapshot_terms({})
        self.assertEqual(subs, {"999988887777", "acme/"})
        self.assertEqual(names, {"svc-old-one", "svc-new-one", "svc-gh-only"})  # single words are left out

    def test_the_walk_reads_every_shipped_file_and_no_fixture(self):
        rels = {str(rel) for rel, _ in shipped_files()}
        self.assertLessEqual({"SKILL.md", "tests/pre-commit", "scripts/dashboard/moved.js", "scripts/movement_page.py"}, rels)
        self.assertFalse({r for r in rels if r.startswith("tests/fixtures/") or r.endswith("config.local.json")})

    def test_no_shipped_file_names_a_configured_value(self):
        subs = config_terms(local_config())
        if not subs:
            self.skipTest("no config.local.json on this machine: no org or profile to compare against")
        self.assertEqual(leaks(subs, set()), [])

    def test_no_shipped_file_names_an_identifier_from_a_snapshot(self):
        subs, names = snapshot_terms(local_config())
        if not (subs or names):
            self.skipTest("no snapshots in the reports folder on this machine: no account, namespace or repo to compare against")
        self.assertEqual(leaks(subs, names), [])


if __name__ == "__main__":
    unittest.main()
