"""The code-auditor gate, and the gate's own failure path.

Run with:
    uv run --with pytest pytest scripts/test_validate_code_auditor.py -v

Both matter. A structural check whose failure path is never exercised decays into decoration
without announcing it: three of validate_code_auditor's assertions once returned a pass on the
exact mutations they exist to catch, and only running those mutations revealed it. So CI runs
the check AND proves the check can still fail.
"""
import validate_code_auditor as v


def test_package_passes_the_gate():
    problems = v.check(v.DEFAULT_DIR)
    assert problems == [], "code-auditor package failed its structural gate:\n  " + "\n  ".join(problems)


def test_gate_catches_every_known_mutation():
    """Each mutation below is a defect that reached review, or was one edit away."""
    assert v.self_test(), "the gate missed a mutation it is supposed to catch"
