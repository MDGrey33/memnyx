# Cognee MCP Usage Guide

This project can optionally use [cognee](https://github.com/topoteretes/cognee) via MCP for semantic memory. Cognee is **not** wired into the standard session loop (`/hello`, `/bye`, `/lessons`) — those rely on markdown memory (`.claude/memory/`) as the primary, always-on store. Use cognee deliberately, on demand, when you want semantic recall over a corpus that a plain grep won't serve well.

## Available MCP Tools

The server exposes 11 tools; the two you'll use directly for text-based memory:

### `remember`
Store data in memory.

```
remember(data="Session summary: implemented auth flow using JWT tokens...")
```

Without `session_id`, this runs the full add + cognify pipeline **synchronously** — it ingests the text and extracts entities/relationships into the graph before returning. This can take minutes on a real corpus (measured ~264s on a ~7,500-token input) — never call it on a path a user is waiting on. With `session_id`, it stores to a fast session-cache only and does **not** persist to the permanent graph.

### `recall`
Search memory with auto-routing.

```
recall(query="authentication patterns used in this project")
```

Supports `search_type` overrides (`GRAPH_COMPLETION`, `RAG_COMPLETION`, `CHUNKS`, etc.) and `datasets` filtering. Typical latency 5–21s for `GRAPH_COMPLETION`.

### `cognify_file`
Ingest a file (base64-encoded) into memory. Runs the add step synchronously but **dispatches cognify in the background** — the call itself returns fast even though graph processing continues after.

### `list_datasets_json`
List datasets as structured JSON. Useful as a health check.

## Why it's opt-in, not automatic

Two properties make cognee a poor fit for anything on the hot path (session start/close):

- **`remember` (without `session_id`) blocks for as long as graph extraction takes** — no fire-and-forget mode for raw text short of the `cognify_file` file-upload route.
- **Every `remember`/`recall` call costs LLM inference** — there's no free tier of usage. Storing on every session close, whether or not anything ever queries it back, is pure spend with no proven return.

`/hello`, `/bye`, and `/lessons` were previously wired to call `cognee_add`/`cognee_cognify`/`cognee_search` — none of which exist on the real server (that was a doc/skill drift bug, not a deliberate design). They've been reverted to markdown-memory-only. If you want cognee's semantic recall, invoke it explicitly — e.g. ask "check cognee for prior work on X" — rather than expecting it in the standard flow.

## When Cognee is Unavailable

Every skill degrades gracefully without it. Markdown memory files are the primary persistent store regardless of cognee's health.

## Troubleshooting

- **MCP not connecting**: Run `/mcp-doctor` for diagnostics, then `/setup-cognee` if needed.
- **`recall` returns nothing**: confirm the target dataset actually has data (`list_datasets_json`) — an empty graph returns nothing to find.
- **Slow `remember` calls**: expected — see the synchronous-pipeline note above. Use `cognify_file` if you need a faster-returning write path.
