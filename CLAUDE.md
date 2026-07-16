# [Project Name]

> Brief project description. Replace this with your project's purpose.

## Memory & Knowledge

Three scopes, each with its own owner and location:

| Scope | Location | Purpose |
|-------|----------|---------|
| Personal | `<workspace>/me/` | Identity, team roster, brag log, growth notes |
| Project | `<project>/.claude/memory/` + project root | Process knowledge, domain context, working state |
| Contributions | `<workspace>/contributions/` | Generalised lessons staged for Memnyx |

Project layout:

```
<project root>/
├── workstreams/           # Per-topic working context (gitignored)
├── sessions/active/       # Active session markers (gitignored)
├── sessions/              # Closed session narratives (gitignored)
├── collected/             # Raw collection outputs from skills (gitignored)
└── artifacts/             # Synthesised skill outputs (gitignored)

.claude/
├── memory/
│   ├── MEMORY.md              # Distilled knowledge (curated, always loaded)
│   ├── lessons-learned.md     # Raw lessons inbox (always loaded)
│   └── project-context.md     # Domain context (always loaded)
├── docs/
│   ├── architecture.md        # Workspace project-architecture template, deployed by init (on-demand)
│   └── conventions.md         # Workspace code-conventions template, deployed by init (on-demand)
└── settings.json
```

## Agent Behavior

See `.claude/docs/agent-guardrails.md` for operational principles.

Agents live in `.claude/agents/` (deployed + synced like skills):

| Agent | Purpose |
|-------|---------|
| `research-expert` | Parallel web-research specialist behind `/research`; gathers corroborated evidence from multiple independent sources and writes a report to keep the caller's context small. |
| `memnyx-guardian` | Read-only PR reviewer that guards Memnyx's spirit while enabling contributions — full code review + philosophy alignment + skill-table parity, with a plain-words merge recommendation and staged (never auto-posted) comments. Run on request or on a schedule. |

## Prerequisites

Run `/setup-workspace init --workspace <path>` to initialise a workspace (see README for the sibling-layout requirement). A semantic-memory backend is optional — run `/setup-cognee` or `/setup-wikibase` after the workspace is verified end-to-end (see `.claude/docs/memory-systems.md` to choose).

## Available Skills

| Skill | Purpose |
|-------|---------|
| `/setup-workspace` | (v2) Workspace lifecycle — `init` (first-time setup: deploys skills/agents/docs, generates `CLAUDE.md`), `add-project <slug>` (scaffolds + registers a project), `sync` (re-copies skills/agents from source, flags conflicts) |
| `/project-registry` | (v2) Manage the workspace project registry — `add` / `remove` / `update` / `list`. Single mutation point; other skills read the index directly. |
| `/hello` | Start a new session — loads context, checks MCP health, recaps last session |
| `/bye` | End the session — summarize work, capture lessons, persist memory |
| `/lessons` | Capture lessons (default) OR `scan` session files / `scan --deep` JSONL transcripts for skill-change proposals. Auto-invoked by `/bye`. |
| `/skills-manager` | Manage skills — add, update, remove, and review (auto-invoked by `/lessons`, or use manually) |
| `/mcp-doctor` | Check health of configured MCP servers (session mode by default; `--deep` for process-level diagnosis) |
| `/collect-my-activity` | Collect user's daily activity from Slack, Jira, Confluence, GitHub, Drive |
| `/collect-team-activity` | Collect a team member's daily activity (leadership roles) |
| `/one-on-one-prep` | Synthesize a member's activity into 1:1 meeting prep |
| `/log` | Append structured entry to agent log (internal/auto-only, not user-invocable) |
| `/contribute` | Generalize a lesson and stage it for Memnyx contribution |
| `/pull-contributions` | Pull generalized contributions from a project into Memnyx |
| `/setup-cognee` | Install and configure cognee-mcp on this machine (semantic-memory backend option) |
| `/setup-wikibase` | Install and configure a local Wikibase Suite — a Wikidata-style knowledge graph with claim-level provenance (alternative semantic-memory backend to cognee). See `.claude/docs/memory-systems.md`. |
| `/setup-auto-memory` | Wire in the optional auto-memory system. See `auto-memory/README.md`. |
| `/setup-playwright-mcp` | Install and configure Playwright MCP for browser automation |
| `/research` | Unified research with three depth modes — `--shallow` (parallel web search via the `research-expert` agent), `--standard` (decompose → parallel subagents → synthesize → cite-check), `--deep` (9-stage pipeline: breadth, depth, gap-fill, contradiction detection, theory, fact-check, tiered output). Replaces the former `deep-research-orchestrator`. |
| `/setup-voice` | Install a local, offline neural voice interface (macOS Apple Silicon) — mlx-whisper (STT) + Kokoro TTS wired into `voice-claude` / `vtranscribe` CLI scripts. No cloud APIs. |
| `/say-it` | Speak content aloud via Kokoro neural TTS (local, offline) |
| `/humanise` | Rewrite text so it reads like a person wrote it, not an LLM — strip AI "tells" (em-dash overuse, rule-of-three, corporate diction, reflexive hedging) while preserving meaning. Register-aware. |
| `/linkedin-pitch-deflector` | Sweep unread LinkedIn DMs — deflect cold sales pitches, socially probe ambiguous openers, hand genuine threads back to you. Drives logged-in Chrome via the chrome-control MCP. |
| `/sanitizer` | Scrub a file/dir/glob for secrets, PII, private context, and tone risks before publishing. Auto-invoked by `/contribute` and `/pull-contributions`. Has a `--check` mode for pre-commit/CI gates. |
| `/finance-controller` | Audit CLAUDE.md, skills, MCPs for cost and context efficiency. Produces a prioritized report; delegates execution to `skills-manager` or asks for approval. Use weekly or when sessions feel slow. |
| `/claude-expert` | Reference for Claude Code surfaces — skills vs hooks vs subagents vs MCPs vs memory vs settings. Use when asked "where should this live" or "how does Claude Code X work". Routes to the doer skill; never edits itself. |
| `/scribe` | Generate or maintain a project's Claude-facing docs (`CLAUDE.md`, `.claude/docs/*`, project-context, README) from verified facts. Fast pass commits directly-readable signals; `--deep` dispatches a `scribe:scribe-explorer` per subsystem plus an independent `scribe:scribe-verifier` pass, routing unconfirmed claims to a hazards artifact. Packaged as a skills-directory plugin — autoloads as `scribe@skills-dir`, bundling its two agents. |
| `/google-script-deploy` | Deploy an HTML file as a Google Apps Script web app with a stable URL. Called by other skills (e.g. a dashboard-generating skill) with a `sourceDir` argument; handles clasp setup, auth, project creation, and in-place redeploys. |
| `/security-snapshot` | Full security pipeline — AWS Inspector V2 + GitHub security alerts → correlation → self-contained HTML dashboard with trend history. Org config in `scripts/config.local.json` (gitignored; overlays the committed template); first run prompts for it. Run monthly or on demand. |

### Skill chains (automatic)
- `/hello` → `/mcp-doctor` (session mode: enumerates loaded tools, no process spawning)
- `/bye` → `/lessons` → `/skills-manager`
- `/setup-cognee` → `/mcp-doctor`
- `/setup-playwright-mcp` → `/mcp-doctor`
- `/contribute` → `/sanitizer` (blocks staging on any finding)
- `/pull-contributions` → `/sanitizer --check` (blocks pull on any finding)
- `/scribe` → `/sanitizer` (blocks on findings in generated docs)

## Skills Governance

Skills in `.claude/skills/` are **deployed copies** — maintained in the boilerplate source, not in service repos. Do not edit them here directly.

To propose a skill improvement:
1. Use `/contribute` to generalise the lesson and stage it in `<workspace>/contributions/`
2. The Memnyx maintainer runs `/pull-contributions` to apply it
3. Changes land via GitHub PR and maintainer review

`/skills-manager` identifies improvement opportunities during sessions and guides you through step 1.

## Workflow

1. **Setup** (once per machine): `/setup-workspace init --workspace <path>` from the cloned source dir
2. **Start**: `/hello` at the beginning of each session
3. **Work**: use skills, register projects with `/setup-workspace add-project`
4. **End**: `/bye` when done
5. **Sync** (periodic): `/setup-workspace sync` to pull upstream skill updates

## Detailed Docs

Refer to these files for more detail (use `@` to include them in context):
- `docs/v2-design-principles.md` — Memnyx v2 architecture, lifecycle, and naming/conventions (the *what* and *why* of the v2 design)
- `.claude/docs/memory-systems.md` — how to choose a semantic-memory backend (markdown / cognee / Wikibase)
- `.claude/docs/cognee-usage.md` — how to use cognee MCP tools for semantic memory
- `.claude/docs/wikibase-migration-patterns.md` — patterns for the Wikibase provenance-graph backend
- `.claude/docs/agent-guardrails.md` — operational rules for agents working in this repo

`.claude/docs/architecture.md` and `.claude/docs/conventions.md` are **not** Memnyx docs — they ship as empty templates that `init` deploys into each workspace for the user's *own* project. Memnyx's own architecture and conventions live in `docs/v2-design-principles.md`.

## Keeping docs in sync

`README.md`, this `CLAUDE.md`, `.claude/docs/*` and each skill's `SKILL.md` are part of Memnyx — they move in the same change as the code that affects them, not deferred. A stale doc is worse than no doc (see `<workspace>/.claude/memory/feedback_doc_maintenance_discipline.md` for the general principle; this section is the Memnyx-specific mapping).

| If you changed... | Update... |
|---|---|
| Added / removed / renamed a skill | `README.md` (Skills Reference table + skill chains), this `CLAUDE.md` (Available Skills table + skill chains) |
| Behaviour of a skill (steps, flags, inputs) | that skill's `SKILL.md` |
| Setup / workflow steps a user follows | `README.md` (Quick Start), this `CLAUDE.md` (Workflow) |
| A template under `.claude/skills/setup-workspace/templates/` | the template itself; and if structural, `init.py` or `add_project.py` `STARTER_MAP` |
| Added / removed / renamed an **agent** | `README.md` and this `CLAUDE.md` (note the agent where relevant; agents live in `.claude/agents/`, deployed + synced like skills) |
| An agent operating rule | `.claude/docs/agent-guardrails.md` (overwritten by `init` and `sync` — Memnyx is the canonical source) |
| Architecture, lifecycle, or skill-chain wiring | `docs/v2-design-principles.md` |
| Code style, file organisation, naming patterns | `docs/v2-design-principles.md` (`## Naming`, `## Skill authoring principles`) |
| A new doc surface | the row above for that surface, and this table |
