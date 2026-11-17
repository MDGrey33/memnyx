"""Committed fixtures must be masked. Runs anywhere — needs no real data.

Every identifier position must hold an alias, every string field must be
classified, and no 12-digit number other than the fake account may appear.
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fixture_mask as fm  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TWELVE_DIGITS = re.compile(r"(?<!\d)\d{12}(?!\d)")


def check_fixture_dir(root: Path) -> tuple[int, list[str]]:
    """Return (files checked, problems) for every snapshot file under root."""
    checked, problems = 0, []
    for f in sorted(root.rglob("*.json")):
        if f.name not in fm.SNAPSHOT_FILES:
            continue
        checked += 1
        rel = f.relative_to(root)
        data = json.loads(f.read_text())
        for path, value in fm.iter_strings(data):
            role = fm.FIELD_ROLES.get(f"{f.name}:{path}")
            if role is None:
                problems.append(f"{rel}:{path}: unclassified field")
            elif role in fm.IDENTIFIER_ROLES and not fm.ALIAS_PATTERNS[role].match(value):
                problems.append(f"{rel}:{path}: {role} is not an alias: {value!r}")
        for n in set(TWELVE_DIGITS.findall(f.read_text())) - {fm.FAKE_ACCOUNT}:
            problems.append(f"{rel}: 12-digit number {n}")
    # A real layer digest or AMI id has the same shape as a fake one, so the
    # grammar cannot tell them apart. Fakes are generated from `layer-<i>` /
    # `ami-<i>` with i counting up from 1, so require every value to be one of
    # the first N such fakes, N being how many distinct values the set holds.
    for role, prefix, length in (("LAYER", "sha256:", 64), ("AMI", "ami-", 17)):
        seed = role.lower()
        values = {v for f in root.rglob("*.json") if f.name in fm.SNAPSHOT_FILES
                  for p, v in fm.iter_strings(json.loads(f.read_text()))
                  if fm.FIELD_ROLES.get(f"{f.name}:{p}") == role}
        allowed = {prefix + fm._fake_hex(f"{seed}-{i}", length) for i in range(1, len(values) + 1)}
        for v in sorted(values - allowed):
            problems.append(f"{role} is not a generated fake: {v!r}")
    return checked, problems


class TestCommittedFixtures(unittest.TestCase):
    def test_fixtures_are_masked(self):
        checked, problems = check_fixture_dir(FIXTURES)
        self.assertGreater(checked, 0, f"no fixture files found under {FIXTURES}")
        self.assertEqual(problems, [], "\n".join(problems[:20]))


class TestCheckerRejectsDirtyFixtures(unittest.TestCase):
    """The check above is only worth something if it can fail."""

    def _problems(self, data):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "raw.json").write_text(json.dumps(data))
            return check_fixture_dir(Path(d))[1]

    def test_real_identifier_at_an_identifier_position(self):
        self.assertTrue(self._problems({"repositories": [{"repositoryAggregation": {"repository": "acme/billing-api"}}]}))
        self.assertTrue(self._problems({"account": "999988887777"}))

    def test_real_layer_digest_with_a_valid_shape(self):
        self.assertTrue(self._problems({"base_layers": [{"layer": "sha256:" + "ab" * 32}]}))

    def test_real_ami_with_a_valid_shape(self):
        self.assertTrue(self._problems({"amis": [{"amiAggregation": {"ami": "ami-0123456789abcdef0"}}]}))

    def test_unclassified_field(self):
        self.assertTrue(self._problems({"image_tag": "release-v1"}))

    def test_twelve_digit_number_in_a_public_field(self):
        problems = self._problems({"generated_at": "arn:aws:iam::999988887777:root"})
        self.assertEqual(problems, ["raw.json: 12-digit number 999988887777"])

    def test_clean_file_passes(self):
        self.assertEqual(self._problems({"account": fm.FAKE_ACCOUNT, "region": fm.FAKE_REGION}), [])
        self.assertEqual(len(self._problems({"account": fm.FAKE_ACCOUNT, "region": "eu-west-1"})), 1)


if __name__ == "__main__":
    unittest.main()
