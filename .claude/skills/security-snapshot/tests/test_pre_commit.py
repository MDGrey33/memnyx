"""The pre-commit hook finds the skill in either layout and runs only its suite."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "pre-commit"
PASS = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n"
FAIL = "import unittest\nclass T(unittest.TestCase):\n    def test_bad(self): self.fail('x')\n"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def fake_skill(skill, test_src):
    (skill / "tests").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: security-snapshot\n---\n")
    shutil.copy(HOOK, skill / "tests" / "pre-commit")
    (skill / "tests" / "test_fake.py").write_text(test_src)


class TestPreCommitHook(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo)
        git(self.repo, "init", "-q")

    def run_hook(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(["sh", str(HOOK)], cwd=self.repo, env=env, capture_output=True, text=True)

    def test_skill_as_its_own_repo(self):
        fake_skill(self.repo, PASS)
        git(self.repo, "add", "-A")
        r = self.run_hook()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Ran 1 test", r.stdout)

    def test_nested_skill_runs_its_own_suite_not_the_repo_tests(self):
        fake_skill(self.repo / ".claude/skills/security-snapshot", FAIL)
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_root.py").write_text(PASS)
        git(self.repo, "add", "-A")
        r = self.run_hook()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("commit blocked", r.stderr)

    def test_nested_skill_passing_suite_allows_the_commit(self):
        fake_skill(self.repo / ".claude/skills/security-snapshot", PASS)
        git(self.repo, "add", "-A")
        r = self.run_hook()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Ran 1 test", r.stdout)

    def test_commit_not_touching_the_skill_is_not_gated(self):
        fake_skill(self.repo / ".claude/skills/security-snapshot", FAIL)
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base", "--no-verify")
        (self.repo / "other.md").write_text("x\n")
        git(self.repo, "add", "other.md")
        r = self.run_hook()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
