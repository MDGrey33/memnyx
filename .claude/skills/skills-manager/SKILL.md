---
name: skills-manager
description: Manage skills — add, update, remove, and review based on lessons or user requests
user_invocable: true
args: Optional description of what to add, update, remove, or improve
---

# Skills Manager — Skills Lifecycle

You manage the full lifecycle of skills: adding new skills, updating existing ones, removing obsolete ones, and reviewing skills based on lessons learned or explicit user requests.

## Model Selection

See `.claude/skills/_shared/MODEL_SELECTION.md` (in your workspace) for full policy.

- **Default model:** Sonnet — weighing lessons, researching practices, and drafting skill changes is judgment work
- **Deterministic parts:** skill inventory and section-presence checks (grep, file listing) — scripts, not LLM calls
- **Promote to Opus when:** holistic skill-system review, or a proposal that restructures how skills interact (finance-controller escalates its hard judgment calls here)
- **Demote to Haiku when:** never — even a small skill edit changes behaviour other skills depend on

## Steps

**Setup — Resolve `<workspace>`**: The skill's base directory is `<workspace>/.claude/skills/skills-manager/`; walk up three directory levels and validate that `<workspace>/.claude/.workspace` exists. Abort with a setup-broken error if validation fails.

1. **Understand the trigger and load lessons context**: Review the lessons or requests passed as input. Derive the active project slug from the session marker (scan `<workspace>/sessions/active/*.md` and `<workspace>/projects/*/sessions/active/*.md`; use `project_slug` from frontmatter — skip project-scope read if no marker exists or `project_slug` is `workspace`). Then read the following files (skip silently if missing):
   - `<workspace>/projects/<slug>/.claude/memory/lessons-learned.md` (project scope, when a project marker is active)
   - `<workspace>/.claude/memory/lessons-learned.md` (workspace scope)

   Scan all entries for recurring mentions of the same skill, bug patterns, or convention violations that span multiple sessions. These inform step 2 even when not explicitly passed as args. If invoked manually with no args, use the lessons as the starting point for proposing improvements rather than asking the user what to do.

2. **Assess what's needed**: Determine the appropriate action:

   **For updates** — only propose changes when:
   - A recurring pattern suggests a workflow improvement
   - A bug pattern could be prevented by a skill adjustment
   - A convention should be enforced in a skill's instructions
   - A new capability or tool should be integrated

   **For new skills** — propose a new skill when:
   - The user explicitly requests one
   - A repeated workflow would benefit from codification
   - A gap exists in the current skill set that lessons have exposed

   **For removal** — propose removing a skill when:
   - The user explicitly requests it
   - A skill is superseded by another or is no longer relevant
   - Two skills overlap significantly and should be consolidated

3. **Research best practices**: Use web search to find current best practices related to the proposed changes. Look for:
   - Claude Code skill authoring patterns
   - Relevant tool or framework documentation
   - Community conventions for the topic
   - Relevant knowledge from similar shared skills

   Apply the four **skill authoring principles** (write the *what* not the *how*; agentic-first for external services; nudge on known agent friction; deterministic prescription only for stable mechanical work) — these are your operating default, used directly with no file load. When a call is genuinely contested — a best-practice-vs-principle conflict, or an edge the one-liners don't settle — consult `<source>/docs/v2-design-principles.md` for the full rationale: resolve `<source>` from `<workspace>/.claude/.source`; if it or the file is absent, proceed on the inline principles and note the doc was unavailable. If an up-to-date best practice conflicts with a principle, **flag the conflict explicitly in the proposal** — do not silently pick one. The user decides whether to update the principle (best practice has moved on) or apply the principle and override the best practice for this skill (principle still holds).

4. **Read current skills**: Read the relevant skill files from `.claude/skills/*/SKILL.md` to understand current behavior.

5. **Propose changes**: Present specific, concrete changes with:
   - Which skill file to modify
   - What to add, remove, or change
   - Research-backed rationale for the change
   - Expected improvement
   - Make sure the changes dont overlap or contradict other services, all skills should work together as a system
   - **"Deterministic lookup" smell check**: if a SKILL.md step claims a deterministic lookup at a scoped path (`<scope>/<path>/<key>`) but `<scope>` can only be learned by reading the lookup target itself, the claim is circular — it hides an implicit scan, and the executing model will either invent one or fail the lookup. Fix by requiring the routing field to be recalled alongside the key, documenting a small fixed-set probe fallback ("try `<workspace>/<path>` first, else glob `<workspace>/projects/*/<path>`"), or re-architecting so the lookup doesn't need scope. Never ship "deterministic" wording an executor can only satisfy by scanning.
   - Identify if additional files need to be updated including but not limited to claude.md and README if relevant
   - Honours the four skill authoring principles (above; full rationale in `<source>/docs/v2-design-principles.md`, loaded only when a decision turns on it). If a researched best practice conflicts with a principle, the proposal must surface the conflict and recommend a resolution — never silently choose.
   - **Model Selection check**: if the skill being added, updated, or reviewed lacks a `## Model Selection` section, draft one as part of the proposal. Apply the shared policy's decision order (script? → Haiku? → Sonnet default? → Opus, sparingly?) to the skill's actual work — read `.claude/skills/_shared/MODEL_SELECTION.md` for tier definitions, and match the block conventions of skills that already carry one. A tier gap caught here ships annotated instead of waiting for the next `/finance-controller` audit.
   - **MCP tool verification check**: if the skill being added, updated, or reviewed calls an MCP tool by name in its instructions, verify each named tool against the live tool schema (`ToolSearch` or equivalent introspection) before approving. A tool name that doesn't resolve on the live server is a blocking finding, not a style note — flag it and require a fix before merge. A tool renamed or removed since a skill was last verified can survive multiple reviews undetected precisely because nothing else in the pipeline checks it mechanically.

   If no changes are warranted, say so and explain why.

6. **IMPORTANT — Ask for approval**: **Never modify skill files without explicit user approval.** Present the proposal and wait for confirmation.

7. **Apply changes** (if approved): Edit the skill files as approved. Then log the change by appending to `.claude/memory/lessons-learned.md`:

   ```markdown
   - **[YYYY-MM-DD]** [tool-usage] Updated [skill-name] skill: [brief description of change]
   ```

8. **Report**: Summarize what was changed (or that no changes were made).
