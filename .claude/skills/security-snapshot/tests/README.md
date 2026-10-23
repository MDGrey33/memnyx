# Tests

Stdlib only — no install needed.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests   # from the skill root
python3 tests/run_mutants.py .                                     # every mutant must be KILLED
```

To run the suite before every commit: `cp tests/pre-commit .git/hooks/ && chmod +x .git/hooks/pre-commit`.
The hook blocks a commit when any test fails. Mutants stay manual (about a minute).

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
