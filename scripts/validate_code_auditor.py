#!/usr/bin/env python3
"""Structural gate for the code-auditor skill package.

Run before any promotion PR, and after any edit round. Exits non-zero on failure.

Written after a review round in which eighteen of nineteen findings were applied to the
three prose files and the one file that is JSON was silently skipped — and then reported
as done. Every assertion below is a failure that actually happened or was one edit away.

    python3 scripts/validate_code_auditor.py [path-to-skill-dir]
    python3 scripts/validate_code_auditor.py --self-test   # prove the gate can fail

The self-test is wired into CI alongside the check itself: a gate whose failure path is never
exercised decays into decoration, silently. Three of the assertions below returned a pass on the
exact mutations they exist to catch, and only running those mutations revealed it.
"""
import json
import os
import re
import shutil
import sys
import tempfile

# Resolve from the repo root the way scripts/check_skill_tables.py does, so this works from a CI
# checkout rather than from any one person's layout. An explicit path argument still wins.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(REPO_ROOT, ".claude", "skills", "code-auditor")

REQUIRED = [
    ".claude-plugin/plugin.json",
    "SKILL.md",
    "review-contract.md",
    "inspect-contract.md",
    "agents/code-auditor-examiner.md",
    "agents/code-auditor-verifier.md",
    "agents/code-auditor-security.md",
]

AGENTS = ["examiner", "verifier", "security"]

# Claims the package must never make. Each was a real finding.
FORBIDDEN = [
    ("cannot be primed", "overclaims independence the orchestrator does not have"),
    ("no shared context", "the other half of the same overclaim — equally false for the orchestrator"),
    ("built-in code-review", "names an external tool whose internals we must not rely on"),
    ("enclosing function of each hunk", "asserts another tool's internals"),
    ("each behind its own verification", "asserts another tool's internals"),
    ("discards findings", "asserts another tool's internals"),
    ("angle of a change", "advertises diff angle-splitting, which belongs to the delegated pass"),
]

# Decisions that were made and then retired. Re-introducing one silently undoes a review round.
RETIRED = [
    ("always dispatched", "the security agent is dispatched on the surface gate, not on every run"),
]

# The class of defect that produced a fresh contradiction in all three review rounds:
# a vocabulary changed in the file that emits it and not in the file that consumes it.
# A literal denylist catches yesterday's mistake; this catches the shape.
COUNTED_INTERNALS = re.compile(
    r"(?i)\b(it|its|the built-in|the reviewer|the delegated pass)\b[^.]{0,40}"
    r"\b(runs|has|uses|performs)\b[^.]{0,20}\b(angles?|passes|checks)\b"
)

VERDICTS = r"CONFIRMED|PLAUSIBLE \((?:trigger|unread)\)|REFUTED|CAN'T-CONFIRM"

# The closure check compares two sets built from the same markup, so an edit landing in BOTH files
# cancels out and passes. Pin the expected sets instead: erosion then shows up as a missing member,
# not as a silent agreement between two shrinking sets.
EXPECTED_VERDICTS = {"CONFIRMED", "PLAUSIBLE (trigger)", "PLAUSIBLE (unread)", "REFUTED", "CAN'T-CONFIRM"}
EXPECTED_REACHABILITY = {"established", "partial", "untraced"}

# Four of the package's regressions were a description advertising a contract the body had
# abandoned. The closure check below reads bodies only — bold tokens, parentheticals — so a bare
# token in frontmatter is invisible to it. This is the narrow check that covers that surface.
RETIRED_IN_DESCRIPTION = [
    (r"PLAUSIBLE(?!\s*\()", "bare PLAUSIBLE — the verdict was split into (trigger) and (unread)"),
    (r"\bangle of a change\b", "diff angle-splitting, which belongs to the delegated pass"),
    (r"\bReachability\b.*\bverdict\b", "reachability is an input, not a verdict"),
]
REACHABILITY = r"established|partial|untraced"


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    out = {}
    for line in m.group(1).split("\n"):
        mm = re.match(r"^([a-zA-Z_]+):\s*(.*)$", line)
        if mm:
            out[mm.group(1)] = mm.group(2).strip()
    return out


def check(d, counts=None):
    fails = []
    counts = counts if counts is not None else []

    for rel in REQUIRED:
        if not os.path.isfile(os.path.join(d, rel)):
            fails.append(f"missing file: {rel}")
    if fails:
        return fails

    texts = {rel: open(os.path.join(d, rel), encoding="utf-8").read() for rel in REQUIRED}
    skill = texts["SKILL.md"]

    fm = frontmatter(skill)
    if not fm:
        fails.append("SKILL.md: no frontmatter")
    else:
        if fm.get("name") != "code-auditor":
            fails.append(f"SKILL.md: name is {fm.get('name')!r}")
        if len(fm.get("description", "")) < 120:
            fails.append("SKILL.md: description too short to trigger reliably")

    for rel in ["SKILL.md"] + [f"agents/code-auditor-{a}.md" for a in AGENTS]:
        desc = (frontmatter(texts[rel]) or {}).get("description", "")
        for pat, why in RETIRED_IN_DESCRIPTION:
            if re.search(pat, desc):
                fails.append(f"{rel}: description advertises {why}")

    for a in AGENTS:
        rel = f"agents/code-auditor-{a}.md"
        f = frontmatter(texts[rel])
        if not f:
            fails.append(f"{rel}: no frontmatter")
            continue
        if f.get("name") != f"code-auditor-{a}":
            fails.append(f"{rel}: name is {f.get('name')!r}, breaking namespaced dispatch")
        if f.get("tools") != "Read, Grep, Glob":
            fails.append(f"{rel}: tools are {f.get('tools')!r} — the read-only lock is the guarantee")
        if "Bash" in f.get("tools", ""):
            fails.append(f"{rel}: HAS BASH — inverts the reviewer/reviewed trust relationship")
        if not f.get("model"):
            fails.append(f"{rel}: no model pinned")

    manifest = json.loads(texts[".claude-plugin/plugin.json"])
    if manifest.get("name") != "code-auditor":
        fails.append("plugin.json: name mismatch")
    if manifest.get("skills") != ["./"]:
        fails.append(f"plugin.json: skills is {manifest.get('skills')!r}, breaking skills-dir autoload")

    # The manifest is prose too. It was the file that got skipped.
    everything = "\n".join(texts.values()) + json.dumps(manifest)
    for bad, why in FORBIDDEN:
        if bad in everything:
            fails.append(f"forbidden claim {bad!r}: {why}")

    for bad, why in RETIRED:
        if bad in everything:
            fails.append(f"retired decision reintroduced {bad!r}: {why}")

    m = COUNTED_INTERNALS.search(everything)
    if m:
        fails.append(f"counts another tool's internals: {m.group(0)!r}")

    # Vocabulary closure. Every token one file emits must be routed somewhere, and every token
    # a consumer routes must actually be emitted. Both directions, because both have broken.
    verifier = texts["agents/code-auditor-verifier.md"]
    security = texts["agents/code-auditor-security.md"]
    contract = texts["review-contract.md"]

    emitted = set(re.findall(rf"\*\*({VERDICTS})\*\*", verifier))
    routed = set(re.findall(rf"\*\*({VERDICTS})\*\*", contract))
    for tok in sorted(emitted - routed):
        fails.append(f"verifier emits {tok!r} but the review contract routes it nowhere")
    for tok in sorted(routed - emitted):
        fails.append(f"review contract routes {tok!r} but the verifier never emits it")
    for tok in sorted(EXPECTED_VERDICTS - emitted):
        fails.append(f"verdict {tok!r} has left the verifier's vocabulary — erosion in both files cancels out of the orphan check")
    for tok in sorted(EXPECTED_VERDICTS - routed):
        fails.append(f"verdict {tok!r} has left the review contract's routing")

    reach = set(re.findall(rf"\*\*({REACHABILITY})\*\*", security))
    # Extract whatever the conversion sentence actually names, not only tokens already expected —
    # an invented token is invisible to a pattern built from the known set. (This is the fix that
    # did not work the first time: the demonstrated mutation added "*unreachable*" and passed.)
    mapped = set(re.findall(r"\*([a-z-]+)\* becomes", skill))
    for tok in sorted(reach - mapped):
        fails.append(f"security emits reachability {tok!r} that SKILL.md never converts to a verdict")
    for tok in sorted(mapped - reach):
        fails.append(f"SKILL.md converts reachability {tok!r} that the security agent never emits")
    for tok in sorted(EXPECTED_REACHABILITY - reach):
        fails.append(f"reachability {tok!r} has left the security agent's vocabulary")

    counts.append(f"verdicts {len(emitted)}/{len(EXPECTED_VERDICTS)} emitted, {len(routed)} routed; "
                  f"reachability {len(reach)}/{len(EXPECTED_REACHABILITY)} emitted, {len(mapped)} mapped")

    ns = re.findall(r"`code-auditor:code-auditor-(?:examiner|verifier|security)`", skill)
    if len(ns) < 6:
        fails.append(f"only {len(ns)} namespaced agent references; a bare name falls back to an unlocked subagent")
    bare = re.findall(r"(?<!:)`code-auditor-(?:examiner|verifier|security)`", skill)
    if bare:
        fails.append(f"{len(bare)} bare agent references remain — a reader will copy the wrong one")

    for ref in re.findall(r"`([a-z0-9\-]+\.md)`", skill):
        if ref == "SKILL.md" or "_shared" in ref:
            continue
        if not os.path.isfile(os.path.join(d, ref)):
            fails.append(f"SKILL.md references a file that does not exist: {ref}")

    return fails


def self_test(src=None):
    """Mutate a copy and assert the gate catches each mutation. A check that cannot fail is worse than none.

    Takes the source explicitly. It used to read sys.argv, which is correct from a shell and wrong
    from anywhere else — under pytest argv[1] is the test file, and the copy step failed on it.
    """
    src = src or DEFAULT_DIR
    mutations = [
        ("Bash added to an agent",
         lambda d: _sub(f"{d}/agents/code-auditor-security.md", "tools: Read, Grep, Glob", "tools: Read, Grep, Glob, Bash")),
        ("agent name truncated",
         lambda d: _sub(f"{d}/agents/code-auditor-verifier.md", "name: code-auditor-verifier", "name: verifier")),
        ("manifest overclaim reintroduced",
         lambda d: _sub(f"{d}/.claude-plugin/plugin.json", "Read-only.", "It cannot be primed. Read-only.")),
        ("external internals asserted",
         lambda d: _sub(f"{d}/SKILL.md", "## Evidence classes", "It reads the enclosing function of each hunk.\n\n## Evidence classes")),
        ("dangling companion reference",
         lambda d: _sub(f"{d}/SKILL.md", "`review-contract.md`", "`gone.md`")),
        ("verdict emitted but not routed",
         lambda d: _sub(f"{d}/review-contract.md", "**PLAUSIBLE (unread)**", "**PLAUSIBLE (unheard)**")),
        ("reachability emitted but unmapped",
         lambda d: _sub(f"{d}/SKILL.md", "*untraced* becomes", "*untracked* becomes")),
        ("retired decision reintroduced",
         lambda d: _sub(f"{d}/SKILL.md", "dispatched whenever the surface gate fires", "always dispatched")),
        ("frontmatter advertises retired vocabulary",
         lambda d: _sub(f"{d}/agents/code-auditor-verifier.md",
                        "PLAUSIBLE (trigger) / PLAUSIBLE (unread)", "PLAUSIBLE")),
        # The three below were demonstrated against an earlier version of this gate, which
        # returned PASS on each. They are kept as the regression suite for those holes.
        ("symmetric vocabulary erosion (passed before)",
         lambda d: (_sub(f"{d}/agents/code-auditor-verifier.md", "**CAN'T-CONFIRM**", "CAN'T-CONFIRM"),
                    _sub(f"{d}/review-contract.md", "**CAN'T-CONFIRM**", "CAN'T-CONFIRM"))),
        ("reachability mapped but never emitted (passed before)",
         lambda d: _sub(f"{d}/SKILL.md", "*untraced* becomes CAN'T-CONFIRM",
                        "*untraced* becomes CAN'T-CONFIRM, *unreachable* becomes REFUTED")),
        ("SKILL.md description advertises retired vocabulary (passed before)",
         lambda d: _sub(f"{d}/SKILL.md", "Read-only — it never fixes",
                        "Returns PLAUSIBLE findings. Read-only — it never fixes")),
    ]
    ok = True
    for name, mutate in mutations:
        tmp = tempfile.mkdtemp()
        dst = os.path.join(tmp, "code-auditor")
        shutil.copytree(src, dst)
        mutate(dst)
        caught = check(dst)
        print(f"  {'caught ' if caught else 'MISSED '} {name}" + (f"  -> {caught[0]}" if caught else ""))
        ok = ok and bool(caught)
        shutil.rmtree(tmp)
    return ok


def _sub(path, old, new):
    s = open(path, encoding="utf-8").read()
    assert old in s, f"self-test anchor missing in {path}: {old!r}"
    open(path, "w", encoding="utf-8").write(s.replace(old, new, 1))


if __name__ == "__main__":
    _args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--self-test" in sys.argv:
        print("self-test — each mutation must be caught:")
        sys.exit(0 if self_test(_args[0] if _args else None) else 1)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = args[0] if args else DEFAULT_DIR
    counts = []
    problems = check(target, counts)
    for line in counts:
        print(line)
    if problems:
        print(f"FAIL ({len(problems)}):")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("PASS")
