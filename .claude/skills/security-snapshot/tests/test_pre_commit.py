"""The pre-commit hook finds the skill in either layout and runs only its suite."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import unittest.mock as mock

HOOK = Path(__file__).resolve().parent / "pre-commit"
PASS = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n"
FAIL = "import unittest\nclass T(unittest.TestCase):\n    def test_bad(self): self.fail('x')\n"


def clean_env(**extra):
    """The environment without GIT_*: under `git commit -a` the hook runs with
    GIT_INDEX_FILE set to the real commit's index, and a temp repo would write there."""
    return dict({k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, **extra)


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=clean_env())


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
        return subprocess.run(["sh", str(HOOK)], cwd=self.repo, env=clean_env(PYTHONDONTWRITEBYTECODE="1"),
                              capture_output=True, text=True)

    def test_the_real_commits_index_is_never_touched(self):
        real_index = self.repo.parent / f"{self.repo.name}-real-index"
        self.addCleanup(lambda: real_index.unlink(missing_ok=True))
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": str(real_index)}):
            fake_skill(self.repo, FAIL)
            git(self.repo, "add", "-A")
            r = self.run_hook()
        self.assertFalse(real_index.exists())
        self.assertNotEqual(r.returncode, 0)  # the hook read the temp repo's index, saw the skill staged, and ran its suite

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
