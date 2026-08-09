---
name: sanitizer
description: Scrub skills, SKILL.md, CLAUDE.md, memory files, and markdown before public/boilerplate release. Detects secrets, PII, private context, and reputation risks. Two-phase — detect → approve → apply. Has a --check mode for CI gates. Called by /contribute and /pull-contributions as the dedicated scrubber.
user_invocable: true
args: <path-or-glob> [--mode=boilerplate|public|project] [--check] [--apply]
---

## Model Selection

- **Default model:** Sonnet — PII and tone judgment need reasoning; regex-only scans are not enough
- **Deterministic parts:** regex scanning, path normalization, report file writes, `--check` verdict emission — all scripted, no LLM
- **Promote to Opus when:** sanitizing a large tree (20+ files) with many ambiguous tone findings
- **Demote to Haiku when:** `--check` mode only (pure regex pass, no judgment)

# Sanitizer — Pre-Release Scrubber

You are the last gate before any skill, doc, memory file, or markdown leaves the user's private environment. Your job: catch secrets, PII, private project context, and unprofessional tone BEFORE they reach a public repo, boilerplate, or third party.

**When the destination repo carries an open-source licence, this gate is also the IP boundary.** Anything that lands in an Apache-2.0/MIT repo is licensed to all downstream users irrevocably — removal after the fact deletes the file, not the grant. A PRIVATE_CONTEXT finding that would merely embarrass in a private leak becomes an unrecoverable licence grant in a public one. Treat the org-content judgment with the same seriousness as the secrets regexes.

**You never silently edit.** Detect → report → wait for approval → apply. Always.

**Setup — resolve `<scope>` for the report path.** The skill's base directory is `<workspace>/.claude/skills/sanitizer/`; walk up three directory levels and check whether `<workspace>/.claude/.workspace` exists. If it does, look for the active session marker under `<workspace>/sessions/active/` and `<workspace>/projects/*/sessions/active/`, and match it to the **current session's identity** rather than taking whatever the glob returns. `<scope>` is `<workspace>` when the marker's `project_slug` is `workspace`, otherwise `<workspace>/projects/<project_slug>`.

**Resolve `<scope>` only on exactly one match.** Concurrent sessions are supported, so the glob can legitimately return several markers belonging to different projects — picking one arbitrarily would file this scan's findings under somebody else's project. On zero or multiple candidates, leave `<scope>` unresolved and use the `/tmp` fallback.

Unlike the skills that own a workspace, **never abort when this fails.** The sanitizer is deliberately callable on any path — `contribute` invokes it on a temp draft that lives outside any workspace. A failed resolution only decides where the report goes; it never blocks the scan. Scanning is the job; the report location is bookkeeping.

## When to Use

- Before pushing to a boilerplate repo or any public repo
- Invoked by `contribute` on every generated contribution
- Invoked by `pull-contributions` as a `--check` gate
- Manually on any file the user is about to publish, share, or commit publicly
- Pre-commit / pre-push hook (via `--check` mode; the wrapper turns the verdict into an exit code)

## Scope Inputs

Accepts:
- Single file: `/sanitizer <path>/CLAUDE.md`
- Directory (recursive): `/sanitizer <path>/`
- Glob: `/sanitizer ~/.claude/skills/*/SKILL.md`

When scanning a directory, always include `settings.json` — this is a prime location for org/repo-specific permission entries that get committed to the repo.

## Modes

| Mode | What it strips |
|------|----------------|
| `--mode=boilerplate` (strict) | Secrets + PII + private context (project codenames) + tone risks. Use for boilerplate repo, public GitHub. |
| `--mode=public` | Secrets + PII + tone. Keeps the user's public identity allowlist. Project context kept. Use for publish-ready public docs that legitimately reference the user. |
| `--mode=project` (light) | Secrets + PII only. Keeps project codenames and context. Use inside a project's own repo where context is expected. |

**Never infer the mode from the path string.** Mode follows the content's *destination*, which a path substring does not report. Both directions fail in practice: a project merely named `boilerplate-something` is local work that would get needlessly strict scanning, while `<workspace>/contributions/` — a staging queue whose entire contents are bound for the boilerplate repo — contains no such substring and would get the *lightest* scan of the three.

Every automated caller passes `--mode` explicitly (see Integration Points). On manual invocation without one, ask the user where the content is going. If that answer is unavailable, default to `--mode=boilerplate` and say so in the report. The asymmetry decides it: a false positive costs a line in a report the user dismisses, while a false negative under an open-source licence is an irrevocable grant (see the IP-boundary note above). Fail toward the strict mode.

## Detection Categories

Every finding is classified into one of four categories:

### 1. SECRET
Anything that looks like a credential, key, or token. Patterns maintained in `secret-patterns.txt` (load it at runtime). Examples:
- API keys: Anthropic, OpenAI, GitHub tokens, GitLab PATs, AWS access keys
- Tokens: JWTs
- Long base64 (≥32 chars of `[A-Za-z0-9+/=]`) in suspicious contexts (`=`, `token`, `secret`, `key` nearby)
- `.credentials/` path references
- Service-account JSON refs (`"private_key": "..."`, `"client_email": "...iam.gserviceaccount.com"`)
- Bearer tokens in example curl commands
- Database URLs with embedded passwords (`postgres://user:pass@...`)
- Org/repo-specific `gh api` permission strings in `settings.json`: `Bash(gh api orgs/<real-org>/...)` or `Bash(gh api repos/<real-org>/...)` — flags real identifiers, ignores placeholder syntax like `<org>`

### 2. PII
Personally identifying info:
- Email addresses (except allowlisted in `allowlist-identity.txt`)
- Phone numbers
- Identifying home paths: `/Users/[^/\s]+/` → suggest `~/` or `$HOME/`
- Real names of people not on the identity allowlist — anything unknown → flag
- IP addresses in private ranges (`10.*`, `192.168.*`, `172.16-31.*`), flag for review not auto-strip
- Internal hostnames (`*.internal`, `*.local`, `*.lan`)
- Physical addresses, financial data (account numbers, card numbers)

### 3. PRIVATE_CONTEXT
Project codenames and internal references that shouldn't leak to boilerplate. Maintained in `denylist-names.txt`. Only active in `--mode=boilerplate` and `--mode=public`. In a licensed public repo these are IP findings, not just confidentiality findings — org-owned content that crosses this gate is granted away under the repo's licence (see the IP-boundary note at the top). Populate the denylist with:
- Project codenames specific to the user's setup
- Client names
- Internal agent codenames — only when referenced outside their project directory
- Internal ritual or stylistic terms — flag in boilerplate mode

Before flagging — whether from a denylist match or the judgment pass — check `allowlist-context.txt`: terms listed there are ones the destination repo legitimately contains (e.g. the org's own name inside the org's private fork) and are not findings. Suppression is visible, never silent: report the suppressed-match count in the summary so a reviewer preparing content for a *different* destination (upstream, public) can see what the allowlist absorbed.

### 4. TONE
Reputation-risk content. LLM judgment pass over every flagged or questionable paragraph:
- Profanity and crude language
- Rants or harsh language about people, companies, products
- Political opinions stated as fact
- Unverified claims about third parties (e.g., "X company is unreliable")
- Inside jokes that read as unprofessional without context
- Half-baked hypotheticals presented as conclusions
- Anything a recruiter, open-source contributor, or employer would interpret poorly

## Two-Phase Execution

### Phase 1: DETECT (default)

For every input file:

1. Read the file **completely** — if a read returns truncated or partial content, page through to the end before scanning. A detect report from a partial read is invalid: findings beyond the truncation point are silently missed.
2. Run each category's detector:
   - SECRET: regex from `secret-patterns.txt` + contextual secondary check
   - PII: regex + allowlist lookup
   - PRIVATE_CONTEXT: denylist substring match (word-boundary), mode-gated; suppress matches listed in `allowlist-context.txt` (applies to the judgment pass too)
   - TONE: LLM pass on suspicious paragraphs (flagged words `stupid`, `hate`, `idiot`, `[company] is`, etc.) — or full-file pass when model is Sonnet+
3. Collect findings: `{file, line, category, excerpt, suggested_replacement, confidence}`.
4. Write a report to `<scope>/artifacts/sanitizer/sanitizer-report-<YYYY-MM-DD-HHMM>-<rand>.md`, with `<scope>` resolved in Setup above. Fall back to `/tmp/sanitizer-report-<YYYY-MM-DD-HHMM>-<rand>.md` only when `<scope>` did not resolve. Never write reports into `contributions/` — that directory is the `/contribute` → `/pull-contributions` staging queue, and a report is skill output, not a contribution.

   **Create the file exclusively, with an unpredictable suffix and mode `0600`** — fail rather than write if it already exists. This is the one place worth being prescriptive: a report may contain the very secrets the scan exists to protect, minute-granularity names collide between concurrent scans, and a predictable name in a world-writable `/tmp` lets a local process pre-create the path as a symlink and reroute the findings somewhere else entirely.
5. Return report summary to the user: count per category, top 10 findings, path to full report.
6. **Stop.** Do not modify any file.

Report format:
```markdown
# Sanitizer Report
**Scanned:** {N files}
**Mode:** {mode}
**Date:** YYYY-MM-DD HH:MM
**Verdict:** {CLEAN | FINDINGS_PRESENT}

## Summary
- SECRET: 2 findings
- PII: 5 findings
- PRIVATE_CONTEXT: 11 findings (allowlist-context suppressed: 2)
- TONE: 1 finding

## Findings

### SECRET (2)
- `path/to/file.md:42` — `<REDACTED-KEY>` → REDACT_OR_ENV_VAR
  > line excerpt
- ...

### PII (5)
- `path/to/file.md:3` — `/Users/<username>/` → `~/`
- ...

### PRIVATE_CONTEXT (11)
- `path/to/file.md:15` — `<codename>` → `[project]` or remove
- ...

### TONE (1)
- `path/to/file.md:88` — paragraph flagged as unverified claim about third party
  > excerpt
  Suggested: rephrase as observation, cite source, or remove
```

### Phase 2: APPLY (requires explicit approval)

Only runs when the user explicitly says apply or when invoked with `--apply`.

1. Re-read the latest report.
2. For each finding with a suggested replacement:
   - Apply deterministic replacements (path normalization, codename strip, email redaction) automatically.
   - For TONE findings, present each one to the user individually with the suggested rewrite and ask for yes/no/edit.
   - **Permission-entry rule:** if a SECRET or PRIVATE_CONTEXT finding occurs inside a permission entry (i.e. the matched line sits within an `allowedTools` or `permissions` block in `settings.json`), do not redact — instead suggest moving the entire entry to `.claude/settings.local.json`. The value is likely still needed; the problem is that it is committed. Present this as the default suggested fix and ask for confirmation before applying.
3. Write patched files.
4. Append applied changes to the same report under `## Applied Changes`.
5. Report diff summary.

## `--check` Mode (CI Gate)

```
/sanitizer <path> --check
```

- Runs Phase 1 only.
- Writes the condensed report to stdout and the full report to the usual file.
- **Ends stdout with exactly one machine-readable line, and nothing after it:** `SANITIZER_VERDICT=CLEAN` when no category has a finding, `SANITIZER_VERDICT=FINDINGS_PRESENT` otherwise. This final line is the gate signal.
- Intended for pre-commit hooks and CI.

**Why a dedicated token on the last line, and not the report's own verdict.** The condensed report quotes findings verbatim, so anything a gate greps for anywhere in the output can be spoofed by a scanned file that happens to contain that text — a file carrying the words `Verdict: CLEAN` would pass a gate searching for them, exactly when the scan says otherwise. Emitting a distinct token as the final line makes the signal come from the skill rather than from arbitrary scanned content.

**The wrapper owns the exit code, not this skill.** A skill runs inside a model turn and cannot set the calling process's exit status, so a hook must derive it from the verdict rather than expecting `claude` to fail. Wiring it as a pre-push hook for the boilerplate repo:

```bash
# .git/hooks/pre-push
#!/bin/sh
out=$(claude -p "/sanitizer $(git rev-parse --show-toplevel) --check --mode=boilerplate") || exit 1
printf '%s\n' "$out"
[ "$(printf '%s\n' "$out" | tail -n 1)" = "SANITIZER_VERDICT=CLEAN" ] || exit 1
```

The `|| exit 1` on the first line catches the CLI itself failing; the last-line comparison catches findings. Match the final line exactly — a substring search anywhere in the output reintroduces the spoofing hole. Both must pass for the push to proceed; a gate that fails open is not a gate.

## Integration Points

**`contribute` calls sanitizer:**
After generating a contribution file, `contribute` invokes:
```
/sanitizer <contribution-file-path> --mode=boilerplate
```
If the verdict is `FINDINGS_PRESENT`, `contribute` blocks the stage and surfaces the report.

**`pull-contributions` calls sanitizer:**
Before integrating contributions into boilerplate, `pull-contributions` invokes:
```
/sanitizer <contributions-dir> --check --mode=boilerplate
```
Blocks the pull unless the final line reads `SANITIZER_VERDICT=CLEAN`. A CLI failure is a separate condition from a `FINDINGS_PRESENT` verdict; the caller distinguishes them.

**Manual invocation:** any time, any path.

## Allowlists and Denylists

Four data files live next to this SKILL.md:

- `secret-patterns.txt` — regex set, one per line, comment lines start with `#`. Seeded from detect-secrets, gitleaks, and trufflehog common patterns. Add user-specific patterns as discovered.
- `denylist-names.txt` — project codenames to strip, one per line. Stripped only in `--mode=boilerplate` and `--mode=public`. Populate per-user.
- `allowlist-identity.txt` — the user's public identity: name variants, GitHub handle, public email. Matches here are NEVER flagged. Populate per-user.
- `allowlist-context.txt` — context terms the destination repo legitimately contains (e.g. the org's own name inside the org's private fork). Suppresses PRIVATE_CONTEXT findings only — secrets and PII are never allowlisted here. Entries do not make a term safe for an external upstream or public repo; see the scope warning in the file. Populate per-deployment.

Update these files directly when new patterns/names are discovered. Changes take effect on next invocation.

## What You NEVER Do

- ❌ Edit a file without a prior detect-phase report approved by the user
- ❌ Strip matches from `allowlist-identity.txt` or `allowlist-context.txt` — allowlisted terms are never findings and never redacted
- ❌ Run TONE detection in `--check` mode without Sonnet+ (regex tone detection produces false positives; skip or downgrade to word-flag only)
- ❌ Scan files in `_archive/`, `node_modules/`, `.git/`, `venv/`, `.venv/`, or `__pycache__/`
- ❌ Scan your own prior reports (`artifacts/sanitizer/`) — a report quotes the findings it reported, so scanning one re-flags every excerpt as a fresh finding. The noise is guaranteed and the signal is nil; worse, it inflates the `--check` gate's count and can fail a build over findings that were already handled
- ❌ Follow symlinks outside the input root
- ❌ Write replacements that reduce meaning — if stripping a term makes the sentence nonsensical, ask the user for rewrite, don't silently mangle
- ❌ Rewrite flagged content that is demonstrably benign (e.g., a guard comment quoting the byte sequence it warns about) — record it as a known-benign exception in the report instead. Battle-tested wording encodes debugging evidence; the scan serves the artifact, not the reverse

## Verification

After any apply phase, re-run detect on the same paths. A clean second pass is required. If new findings appear (e.g., your replacement introduced an issue), roll back and escalate.

Before any commit that publishes scanned content, re-run detect (`--check`) on the final staged copy. The gate is load-bearing — it catches what the report-phase read missed — not belt-and-braces.

## Output Conventions

- Reports: `<scope>/artifacts/sanitizer/sanitizer-report-YYYY-MM-DD-HHMM-<rand>.md`, scope-resolved in Setup, with `/tmp/sanitizer-report-YYYY-MM-DD-HHMM-<rand>.md` as fallback when `<scope>` does not resolve. Created exclusively, mode `0600` (see Phase 1 step 4).
- Never write findings content anywhere it could be shared, synced, or published — the findings themselves may contain the secrets you're trying to protect. `artifacts/` sits inside the workspace or project being scanned and is gitignored, so the scoped path satisfies this. The `/tmp` fallback is the one location outside the scanned tree that is allowed, and only because it is machine-local and transient; it is a last resort for scans with no resolvable workspace (a temp draft, say), never a convenience.
- `--check` mode prints a one-line summary to stdout; full details go to the report file.

## Examples

```
/sanitizer <path-to-boilerplate>/ --mode=boilerplate
→ scans entire tree, detect phase (mode must be given — never inferred from the path)
→ report: 14 findings across 6 files

/sanitizer ~/.claude/skills/setup-cognee/SKILL.md --mode=public
→ single file, checks secrets + PII + tone, keeps project terms

/sanitizer ~/code/my-project/ --check
→ CI gate, exits 1 if any finding

apply
→ after a detect report is open, applies non-tone findings automatically,
  asks per-TONE-finding before rewriting
```
