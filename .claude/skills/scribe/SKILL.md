---
name: scribe
description: Scribe — the project-documentation skill. Generate or maintain a project's Claude-facing documentation (CLAUDE.md, .claude/docs/*, project-context.md, README) from verified facts. Use when the user says "document this project", "write the docs for X", "the docs are stale", "fill in the .claude docs", or "/scribe". Detects existing doc state and routes between from-scratch and update. Verify-before-assert is the core discipline — confirmed facts go to committed docs, inferred/uncertain ones go to a separate hazards artifact, never silently into the repo.
user_invocable: true
args: "Optional: --scratch (force from-scratch), --from-session (incremental update from this session's work), --deep (per-claim source verification + hazards output), --refresh-okf (refresh the OKF alignment profile). No flag = detect doc state and route at fast depth."
---

# Scribe

You are documenting a software project so that a future engineer — or a future Claude session — can become productive without reconstructing context from code and tribal knowledge every time. The danger you design against is not an empty doc; it is a **confidently wrong** one. A misleading doc is worse than no doc. Verification is the product here, not a nicety.

This SKILL.md is the operating instruction; a separate design spec holds the rationale — consult it only if a decision turns on the *why*.

## The one rule that everything else serves

**Verify before assert.** Every factual claim in a committed doc is grounded in a source you actually read. But "verify" does not mean "trace everything with a sub-agent" — a fact read directly from an authoritative signal is verified *by the read*. The gate is on claims that need tracing or are echoed from existing prose. See **Claim provenance** below; it is the spine of this skill.

## Entry points

One shared engine, three ways in. The mode is **inferred from doc state, then confirmed with the user** — never assumed silently.

- **`/scribe` (no flag) — detect and route.** Scan the repo's doc state (`CLAUDE.md`, `.claude/docs/*`, `README`, `.claude/memory/*`). Absent or sparse → propose documenting from scratch. Present → propose an update. **Hybrid is the common real case** — prose docs (`CLAUDE.md`, `README`) already exist but the structured set (`.claude/docs/*`, memory) is absent. Don't force scratch-xor-update: create the missing structure (the *Standalone* path) and fill it, while treating the existing prose as category-3 to be carried-not-clobbered. Confirm the inferred mode before doing work.
- **`/scribe --scratch`** — explicit override: full from-scratch generation, regardless of what exists.
- **`/scribe --from-session`** — explicit override: incremental update from the current session's work (the mode `/bye` will eventually nudge toward). Consult the project's **doc-sync table** (the per-project mapping in its `CLAUDE.md`, per the doc-maintenance convention) to learn which surfaces map to what the session changed; update only those, and fall back to the standard doc set when no table exists.
- **`/scribe --deep`** — run at deep depth: sub-agent codebase exploration, per-claim category-2 verification, an independent verification reviewer, and a hazards artifact for what couldn't be confirmed. See *The deep pass* below.

**Mode and depth are orthogonal.** Mode (scratch / update / from-session) is *what doc state you start from*; depth (fast / deep) is *how hard you verify*. The no-flag default routes the mode and runs at fast depth; `--deep` raises the depth for whichever mode the detect step inferred. A deep `--scratch`, a deep update, and a deep from-session are all valid.

### What detect-and-route can and cannot see — be honest

The cheap scan detects **structure**: which doc files exist, which are empty stubs, which sections are missing, and grep-level contradictions (a README naming an env var that no longer exists in `.env.example`). It does **not** detect semantic drift — "are these docs actually current against the code?" is the expensive deep-verification question, and the fast pass does not answer it.

So when you route on the cheap scan, never report "your docs are current." Report what you checked (structure, presence, obvious contradictions) and flag the rest: *"semantic freshness unverified — run a deep pass to confirm."* Claiming a freshness check you did not perform is the same failure mode as the confidently-wrong doc, one level up.

## Claim provenance — the spine

Before any claim enters a committed doc, place it in one of three categories. The category, not the section it would live in, decides whether the current pass may commit it.

**Category 1 — directly readable from an authoritative signal.** The signal *is* the ground truth; reading it is the verification. Examples: dependencies / scripts / `engines.node` / package name from `package.json`; module and directory layout from the tree; which config files exist (`tsconfig.json`, `Dockerfile`, `.github/workflows/*`, test/lint/format configs); declared test runner, linter, formatter; environment variables *as declared* in any committed env file (the declaration — not whether the code honours it). **The fast pass commits these.** Test to apply: *is this file the authority for this claim?* `package.json` is the authority for "what dependencies are installed."

> **Env files — declaration authority *and* leak hazard.** "As declared in an env file" means any committed env file (`.env.example`, but also `.env.production`, `.env.local`, etc.) is the authority for *which variables are declared* — read variable **names** from it. But a non-template env file holds **live values** (passwords, API keys), unlike a `.example` template. So such a file is simultaneously a category-1 signal and a sanitizer hazard: quote names only, never values, and see the sanitize step on how to handle a repo that commits real secrets.

**Category 2 — needs tracing or synthesis.** Cannot be confirmed without following code across files and reasoning about runtime. Examples: data flow ("an event enters via X, is processed by Y, persisted by Z"); architecture invariants ("all repository access goes through a single accessor function"); conventions that gate behaviour ("controllers must validate the tenant before any query"); whether a declared env var is *actually honoured* by the code; the dark-corner hazards. **Deep pass only.** The fast pass leaves a clearly-marked TODO and does not guess.

**Category 3 — echoed from existing docs.** Prose in an existing `CLAUDE.md` / `README` / docs not backed by a category-1 signal. **The fast pass never re-asserts it.** Carry it forward only as "carried from existing docs — unverified", or drop it. The deep pass re-grounds it against source — at which point it becomes a confirmed fact, or moves to the hazards bucket if it turns out wrong.

> **Bounded debunking trace — the one sanctioned exception.** When an existing doc makes a category-3 claim that is *actively misleading* if left standing (e.g. a README declares an HTTP port configurable via an env var, but the code hardcodes it), the fast pass MAY read the single file needed to debunk it — a bounded category-2 trace in service of *not* laundering a dangerous claim. Mark the result confirmed-by-trace and stop; do not let it pull you into tracing the broader subsystem (that stays a deep-pass TODO). The test: you are reading one file to *prevent* a false assertion, not to *manufacture* a new one.

**The instructive edge — internalize this.** A representative failure: a README claims an HTTP port is configurable via an env var (a category-3 echoed claim), but *correcting* it requires category-2 tracing — reading the server bootstrap to find the port hardcoded. That is exactly how a fast generator mints a misleading doc with fresh authority: it copies prose it never grounded. Fast pass must never launder category 3 into a confident assertion.

## The pipeline (shared engine)

1. **Detect** — read existing doc state; infer mode (scratch vs update) and depth; confirm with the user. Be honest about structural-vs-semantic (above).
2. **Gather** — read the existing docs and the cheap signals. Deep pass: dispatch sub-agents to explore the codebase by subsystem (see *The deep pass*).
3. **Verify** — categorize every load-bearing claim (1/2/3). *Load-bearing* = a claim a reader or agent would act on (architecture, gating conventions, env vars, data flow). Descriptive filler is not adversarially re-checked — low harm, high noise. Unverified category-2/3 claims do not enter committed docs.
4. **Write** — fill the target doc files, **creating any that are absent** (see *Standalone* below — never assume a scaffold exists). Preserve template scaffolding comments where they exist (append below them; never strip them). OKF-aligned structure for reference docs (see the companion profile) — when a file carries both, YAML frontmatter goes *above* the preserved HTML comment block, not in place of it. `README.md` is human-facing and exempt from OKF frontmatter. Respect doc layering. Trim duplication to pointers — point at `CLAUDE.md` rather than copy the dir tree into three files.
5. **Sanitize** — run `/sanitizer` scoped to the destination before anything touches a shared repo. **Block only on *our own output* — a finding means a real value leaked into the generated docs; fix the doc and re-run.** This is not optional: docs are designed to be portable, so leaked data travels. **Do not block on the repo's pre-existing hygiene.** If the source repo itself commits secrets (a real `.env` file with live values, a committed private key), that is existing code, not something this run produced — *flag it to the user as a finding they decide on*, and do not refuse to document the repo over it. Block on what we write; flag what we find.
6. **Review** — the default reviewer is an **independent verification pass** (see *Verification pass*): a sub-agent re-checks each load-bearing confirmed claim against source, blind to your reasoning ("does this hold?"). The failure mode is wrong facts, not buggy code, so this is the right reviewer. `memnyx-guardian` reviews the *skill itself* when it is promoted upstream — a separate flow, not part of running the skill. `/code-review` is opt-in only when a run also touched code.
7. **Output** — committed docs (clean, confirmed only) + the deep pass's separate hazards / open-questions artifact for the inferred and uncertain (see *Hazards artifact*). Propose diffs; the human applies. Never auto-commit or auto-edit shared-repo docs.

## The deep pass (`--deep`)

Where category-2 claims get confirmed and the fast pass's TODOs get filled. It is a **superset run**: if the repo has no fast-pass output yet, lay the category-1 foundation first (or detect existing fast-pass docs and build on them), then add the verification layer. Single service per run — no multi-service fan-out.

**How it explores.** Decompose the codebase by subsystem (module / bounded context — for a NestJS service, roughly one unit per feature module) and dispatch a **`scribe:scribe-explorer`** sub-agent per subsystem, with bounded parallelism (one unit ≈ one context window; don't spawn an unbounded fleet). Dispatch that agent by name — it is read-only and tool-locked to Read/Grep/Glob, which is what keeps each explorer from wandering or mutating; a generic sub-agent carries none of those guarantees. Each explorer's brief is guidance, not a runbook: *trace how X actually works, cite the `file:line` that proves each claim, and flag anything you cannot confirm.* It returns confirmed facts (with source refs) plus a list of what it could not verify.

**What it confirms.** The category-2 content the fast pass deferred: data flow, architecture invariants, gating conventions, whether declared config is actually honoured, the dark corners. Every claim that lands in a committed doc carries a source reference. A claim an explorer asserts *without* a `file:line` is treated as inferred, not confirmed — it goes to the hazards bucket, not the doc.

**The split is the product.** Confirmed-with-source → committed docs (fills the TODOs, re-grounds category-3 carry-overs). Inferred / uncertain / contradictory → the hazards artifact. Worked illustration: a repository accessor whose *declared* signature disagrees with how its callers actually invoke it can't be resolved from code alone — it belongs in hazards ("verify with the team"), never asserted in `architecture.md`.

## Hazards artifact

The deep pass's inferred / uncertain bucket. **Workspace artifacts, gitignored:** `<scope>/artifacts/scribe/<service>-hazards-<date>.md` (scope resolved from the session marker, never cwd). Never the service repo — uncertain content reaches a shared repo only by an explicit human act. Shared with the team by hand only; no automatic promotion path.

- **Emit only when non-empty.** If the deep pass confirmed everything cleanly, write a one-line "no open questions" note in the run summary, not a file.
- **What goes in:** claims an explorer couldn't ground; contradictions between code and existing docs that can't be resolved from code alone (the signature-mismatch case above); dark corners that need an author or a running system to confirm. Each item names *what would resolve it* — "verify with the team", "confirm at runtime", "ask the original author".
- It is an output for humans to triage, never a source the skill reads back as fact.

## Verification pass (the reviewer)

Before committed docs are proposed, an **independent verifier** — the **`scribe:scribe-verifier`** sub-agent, dispatched by name — re-checks each load-bearing confirmed claim against source, a fresh sub-agent blind to the writer's reasoning, asked only "does this hold? cite the line, or refute it." Catches the confidently-wrong claim the writer rationalized into place.

- **Default: one verifier per claim set.** A single blind re-check is enough for most claims.
- **Escalate to a multi-vote check** only for claims the writer flagged low-confidence, or where a wrong assertion is high-blast-radius (a security or tenancy invariant). Don't run an adversarial panel on every line — that is deep-pass-on-steroids for no gain.
- A claim the verifier refutes or cannot confirm **drops from the committed docs to the hazards bucket.** The verifier returns verdicts; it never silently rewrites — you (the writer) act on them.

## Doc layering — respect what loads when

The target doc set has a deliberate load profile. Keep the always-loaded files lean and push detail down.

| Surface | Loads | Holds |
|---|---|---|
| `CLAUDE.md` | every session | operating model, doc-sync table, `@`-includes to memory |
| `.claude/memory/project-context.md` | every session | business domain, constraints, who the users are, what "done" means — short |
| `.claude/docs/architecture.md` | on demand | system shape, data flow, key components (category-2 heavy → deep pass) |
| `.claude/docs/conventions.md` | on demand | code style, patterns, gating conventions |
| `README.md` | human-facing | setup, run, env vars |

The fast pass can populate the category-1 portions of every surface (stack, structure, scripts, declared env vars, layout). It leaves category-2 sections (data flow, invariants) as marked TODOs for a deep pass.

### Standalone — create the full committed layer, not just docs

This skill **does not depend on `setup-workspace add-project` having run — and must not delegate to it.** `add-project` is workspace-coupled: it scaffolds per-engineer working dirs and registers the project in the workspace registry, both wrong for documenting an arbitrary service repo. On an unregistered repo you create the **complete committed `.claude` layer yourself**, then fill the docs. A doc set without the rest is half a layer.

The full set to ensure exists (create if absent, never clobber an existing file):

- **`.claude/docs/*`** — the reference docs, filled with verified facts, plus `index.md`.
- **`.claude/memory/`** — `project-context.md` (filled); `MEMORY.md` and `lessons-learned.md` as **header-only stubs**, so the memory system has somewhere to write.
- **`.claude/settings.json`** — `{}` if absent. Project-level allowlists evolve here; per agent-guardrails, sub-agent allowlists must be project-level.
- **`CLAUDE.md`** — the `@`-include to `project-context.md` (only if no `CLAUDE.md` exists).
- **`.gitignore` — the load-bearing safety step.** Append the per-engineer-state patterns (`workstreams/`, `sessions/`, `collected/`, `artifacts/`, `contributions/`) so a future engineer's working state can never be committed to the shared repo. Skipping this is not cosmetic — it turns the layer into a leak trap.

Do **not** create the working dirs (`sessions/`, `workstreams/`) themselves — gitignoring them suffices; empty dirs don't commit. Seed fresh stubs with their scaffolding-comment guidance. These stub definitions (memory headers, `{}`, the gitignore patterns) match what `add-project` writes — trivial and stable, but if the boilerplate changes them materially, update both.

## OKF alignment

Generated reference docs follow the Open Knowledge Format's stable core: markdown + YAML frontmatter (`type` required, plus `title` / `description` / `tags` / `timestamp`), one concept per file, cross-links between concepts, an `index.md` for progressive disclosure. The stable core is encoded in the companion profile `okf-alignment.md` next to this file — read it before writing reference docs.

Do not consult the live OKF spec on every run. The companion profile is the pinned operating default (reproducibility across a multi-service rollout, offline safety). `--refresh-okf` (below) is the deliberate path to update it.

### `--refresh-okf`

The deliberate path to keep the alignment profile current without going stale or going religious. Manual only — never scheduled.

1. **Fetch** the live OKF spec (the canonical URL in `okf-alignment.md`).
2. **Diff** it against the pinned companion profile — what fields / conventions changed, what was added, what we deliberately don't adopt.
3. **Surface** the diff for human approval. Nothing changes the profile without a yes.
4. **Update** `okf-alignment.md` on approval — bump the tracked version + freshness date, record what changed and any new deliberate-skip.

Run it before a documentation batch, or when you know OKF moved. Why not per-run: reproducibility across the rollout (a pinned profile gives consistent output; format changes happen on purpose between batches), human review before a format change reshapes every service, and offline safety.

## Boundaries — compose, don't overlap

- `setup-workspace add-project` / `init` → scaffold **empty stubs** + register. A convenience, not a precondition for this skill.
- Claude Code built-in `/init` → generate a `CLAUDE.md` from the codebase.
- `/scribe` → **populate and maintain verified content**, creating the doc structure itself when it is absent (see *Standalone* above). Works on any repo, registered or not.

Rollout per service (when registering): `add-project` (register + stub) → `/scribe` (detect → fill / verify / sanitize / review) → human PR. On an unregistered repo, skip straight to `/scribe`.

## Scope discipline

- **Single service per run. No built-in multi-service fan-out.** A batch across services, if ever wanted, is an explicit orchestration layer the user invokes — not something this skill spawns. This keeps a single command from launching an unbounded sub-agent fleet.
- Within a deep run, decompose verification by subsystem with bounded parallelism — bound each unit to one context window.

## Model Selection

Advisory — this section does not switch the session model; it states policy for sub-agent dispatch and for a reader deciding how to run the skill. See `_shared/MODEL_SELECTION.md` for the shared tier policy.

- **Detect / scan / diff** — scriptable, no model. Reading `package.json`, listing the tree, grepping for contradictions is deterministic work.
- **Fast-pass gather + write** — balanced tier (Sonnet-class). Judgment over which category-1 facts matter and how to phrase them, but bounded.
- **Deep-pass verification + synthesis** — premium tier (Opus-class). Tracing code to confirm category-2 claims and resolving contradictions is where confidently-wrong output originates; spend the reasoning here.
- **Independent verification pass** (the reviewer) — premium tier. Adversarial re-checking of load-bearing claims is high-stakes by definition.

Never use the small/fast tier for anything that produces or verifies a committed claim — only for mechanical validation.

## A note on idempotence

Re-running must preserve hand edits. Propose diffs; never clobber a file wholesale. If a doc has diverged from what the skill would generate, surface the divergence and let the human decide — same "divergent never overwrites" rule as `setup-workspace sync`.
