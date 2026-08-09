---
name: pull-contributions
description: Pull generalized contributions from a project into Memnyx. Runs `sanitizer --check` as a mandatory gate before integration.
user_invocable: true
args: Path to a workspace's contributions/ folder (e.g., <workspace>/contributions/)
---

## Model Selection

See `.claude/skills/_shared/MODEL_SELECTION.md` (in your workspace) for full policy.

- **Default model:** Haiku 4.5 — mechanical file copy + path rewrite from project to Memnyx
- **Promote to Sonnet when:** a contribution needs de-identification or rewording before merging
- **Promote to Opus when:** never

# Pull Contributions — Integrate Project Learnings into Memnyx

You are integrating generalized contributions from a project into Memnyx. This skill is meant to be run **from the Memnyx repo**, not from a project.

## Steps

1. **Locate contributions**: The user provides the path to `<workspace>/contributions/` (e.g., `~/workspace/contributions/`). Read all `.md` files in that folder **that do not start with `integrated-` or `skipped-`**. Files with the `integrated-` prefix have already been applied; files with the `skipped-` prefix were reviewed and rejected — skip both silently. `sanitizer-report-*.md` and `lessons-scan-*.md` files are skill output, not contributions — skip those too. Both skips protect workspaces still holding files written before those skills were routed to `artifacts/`; a deployed copy only changes on `/setup-workspace sync`, so the window stays open until each adopter syncs and migrates.

   If no path is provided, ask the user for it.

2. **Sanitize gate (MANDATORY)**: Run `sanitizer` in check mode on the contributions folder:
   ```
   /sanitizer <contributions-folder-path> --check --mode=boilerplate
   ```
   - Verdict `CLEAN` → proceed.
   - Verdict `FINDINGS_PRESENT` → **halt**. Surface the sanitizer report. Do NOT pull any contribution with findings. Ask the user to run `/sanitizer <path> --apply` in the source project to fix, then re-run this skill.
   - Read the gate from the verdict, not from a process exit code — a skill runs inside the model turn and cannot set one.
   - Do not duplicate sanitization logic here — the sanitizer is the single source of truth for what leaks.

3. **Review each contribution** (content check only, not PII/secret — that's sanitizer's job):
   - **Actionable**: The recommendation is concrete enough to apply.
   - **Categorized correctly**: The type and target file make sense.

3. **Present a summary** of all contributions found:

   ```
   Contributions found: [count]
   ─────────────────────────────
   1. [title] (type: skill-update, target: .claude/skills/hello/SKILL.md)
   2. [title] (type: convention, target: CLAUDE.md)
   ...
   ```

   Ask: "Which contributions should I integrate? (all / specific numbers / none)"

4. **For each approved contribution**, apply the changes:

   - **skill-update**: Read the target skill file, apply the recommended changes, show the diff to the user for approval before writing.
   - **new-skill**: Create the new skill directory and SKILL.md. Show the content for approval.
   - **convention**: Add to the relevant section of CLAUDE.md or `.claude/docs/conventions.md`. **Budget gate for always-loaded targets:** if the target is a file CLAUDE.md `@`-imports (e.g. `.claude/docs/agent-guardrails.md`), measure it first (tokens ≈ bytes/4) against the always-loaded thresholds in `.claude/skills/finance-controller/references/thresholds.md`. At yellow (>2,000 tokens) or above, the addition is zero-sum: draft a displacement or condensation of at least the addition's size in the same change, and let the user decide which rule loses its slot. Safety rules (production read-only, secrets handling, and similar) are exempt from displacement and may land at yellow — flag the overage instead, so compression rebalances among style and process rules.
   - **memory-template**: Update the memory file templates (MEMORY.md, lessons-learned.md, etc.).
   - **docs**: Update the target doc file.
   - **config**: Update the target config file. Be extra careful with `.mcp.json` and `settings.json`.

5. **Always ask for approval** before writing any changes. Show exact diffs or new content.

6. **After integration**, ask: "Should I mark the processed contributions as integrated?"
   - If yes, rename applied contribution files to add an `integrated-` prefix (e.g., `integrated-2025-06-15-improve-hello-mcp-retry.md`), and contributions the user reviewed and rejected to add a `skipped-` prefix. Both prevent re-processing on future runs.

7. **Update CLAUDE.md** if new skills were added (add to the skills table).

8. **Report**:

   ```
   Pull Complete
   =============
   Reviewed: [count] contributions
   Integrated: [count]
   Skipped: [count] (with reasons)
   Files modified: [list]

   Remember to commit the changes to the Memnyx repo.
   ```

## Important Rules

- **Never auto-apply**: Always show changes and get user approval before modifying any file
- **Flag leaks**: If a contribution contains project-specific details, flag it and suggest how to generalize
- **Preserve structure**: When editing existing files, maintain their format and style
- **One at a time**: Apply contributions individually so the user can approve/reject each one
