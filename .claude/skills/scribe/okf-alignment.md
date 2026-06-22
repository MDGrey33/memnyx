# OKF Alignment Profile

Companion profile for `scribe`. This is the **pinned** operating default for OKF-aligned output — the skill reads it, not the live spec, so a multi-service rollout produces consistent structure and format changes happen on purpose between batches.

| Field | Value |
|---|---|
| OKF version tracked | v0.1 |
| Profile freshness | 2026-06-12 (from the boilerplate-redesign OKF research; **not re-fetched since**) |
| Canonical spec | `github.com/GoogleCloudPlatform/knowledge-catalog/okf` |
| Refresh mechanism | `--refresh-okf` (Phase 2) — fetch live spec, diff against this profile, human-approve, update |

> **Freshness caveat.** OKF was ~1 day old (v0.1) when this profile was captured, so it is expected to churn. The values below reflect that research, not a live fetch this session. Before a documentation batch, run `--refresh-okf` (once built) or manually re-verify against the canonical spec. Treat anything here as "what we tracked", not "what OKF guarantees today".

## Stable core (what we adopt)

The parts of OKF stable enough to build on now:

- **Format:** markdown files with **YAML frontmatter**.
- **Required frontmatter field:** `type`.
- **Adopted frontmatter fields:** `title`, `description`, `tags`, `timestamp` (alongside `type`).
- **One concept per file** — a reference doc covers a single concept, not a grab-bag.
- **Cross-links between concepts** — concepts reference each other explicitly.
- **`index.md`** — an entry point for progressive disclosure across the concept set.

## Why Memnyx is already near-OKF

Memnyx memory atoms already carry `type` / `name` / `description` frontmatter and `[[links]]`, and `MEMORY.md` is an index. So emitting OKF-shaped reference docs is mostly free here — the house style and the open standard already converge. This is why we align closely rather than invent a parallel structure.

## Deliberately not adopted (yet)

- `log.md` (OKF activity log) — noted in the research but not wired into the doc set the skill maintains. Revisit on refresh.
- Hard binding to any v0.1 field beyond the stable core above — the spec is too young to bind tightly. Follow closely, don't be religious.

## Mapping to the scaffolded doc set

OKF frontmatter applies to the **on-demand reference docs** (`.claude/docs/*` and any concept files), not to `CLAUDE.md` (operating model, not a knowledge concept). The always-loaded `project-context.md` may carry light frontmatter but stays lean — its job is brevity, not catalog completeness.
