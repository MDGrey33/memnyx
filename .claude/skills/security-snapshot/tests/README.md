# Tests

Needs `boto3`, the same as the skill: the capture tests import `posture_snapshot.py`,
which imports it. Install it as `SKILL.md` describes. The dashboard's JavaScript tests (`tests/js/`) need
`node` and no packages; `test_dashboard_js.py` runs them, and skips them when node is absent.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests   # from the skill root
python3 tests/run_mutants.py .                                     # every mutant must be KILLED
```

To run the suite before every commit, from the skill directory:
`cp tests/pre-commit "$(git rev-parse --git-path hooks)/pre-commit" && chmod +x "$(git rev-parse --git-path hooks)/pre-commit"`.
The hook works whether the skill is its own repo or sits under `.claude/skills/` in a larger one; in a
larger repo it runs only for commits that touch the skill. It blocks a commit when any test fails.
Mutants stay manual (about a minute).

## Guards

Three tests catch failures that otherwise surface only in a live run or after publishing:

- `test_capture_main.py` and `test_github_capture_main.py` run each capture's `main()` end to
  end with `--save --raw`, on fixture data with AWS and `gh` stubbed.
- `test_static_names.py` fails on a name a script uses but never defines, including one taken
  from another script (`from movement import X`, `movement.X`).
- `test_no_real_identifiers.py` fails if any shipped file names the real org or AWS profile
  (from `config.local.json`), or an account, namespace or hyphenated repo name from any
  snapshot in the reports folder. Each source skips, with its reason, when absent, so on a
  fresh clone this test checks nothing.

## Fixtures

`fixtures/<set>/<date>/` holds snapshot files masked by `scripts/fixture_mask.py`:
account, org, repository names, ECR namespaces, layer digests and AMI ids are
replaced with aliases; package names, CVE ids, severities, dates and counts are
real. `test_fixtures_clean.py` checks every committed fixture, needs no real
data, and fails on any unclassified field.

Regenerate a set from real snapshots (writes nothing if the leak check fails):

```bash
python3 scripts/fixture_mask.py --reports-dir <reports dir> --dates <d1> <d2> --out tests/fixtures/<set> --alert-repos 2 --code-scanning 50
```

A field added to any collector must be classified in `FIELD_ROLES` before the
masker will run — as an identifier role, or as `PUBLIC`.

`--alert-repos 2` keeps per-alert GitHub detail for the two repos with most alerts on
the newest date, the same two on every date. `--code-scanning 50` keeps 50
code-scanning alerts per date, which only the dashboard build counts. That detail
is most of a snapshot's size and no test asserts on its totals; the aggregates stay whole.
