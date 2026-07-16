---
name: say-it
description: Speak content aloud via Kokoro neural TTS (local, offline). Use when the user says "read it for me", "read it to me", "play it in audio", "say it", "speak it", "read that aloud", "/say-it", or asks to hear something spoken instead of reading it.
user_invocable: true
args: Optional. What to speak — "last response", a section name, a file path, or inline text.
allowed-tools: Write, Bash(kokoro-say *), Bash(pkill *), Bash(kill *), Bash(ls *)
---

# Say It — Speak Content Aloud

## Prerequisites

Requires the voice stack installed via `/setup-voice`:
- `kokoro-say` in `~/.local/bin/`
- Kokoro models at `~/.cache/kokoro/`

Run `/setup-voice` first if `kokoro-say` is not found.

## Model Selection

- **Default model:** Haiku 4.5 — markdown strip + kokoro-say invocation is mechanical
- **Promote to Sonnet when:** user asks for a condensed or rephrased spoken version ("say it like a summary", "read me the gist")

## Triggers

- "read it for me", "read it to me", "read that aloud", "read the response aloud"
- "play it in audio", "play this in audio"
- "say it", "say that", "speak it", "speak that"
- "/say-it"
- Any "can you speak / read / say" request aimed at a response or file

## What to speak

- **Default:** the most recent substantive response you produced (not the reply you are about to give).
- **User specifies a section/file:** speak only that part.
- **User provides text inline:** speak it verbatim (or rephrase only if they asked).

If the content is over ~5000 words, confirm first.

## Voice selection

| Context | Voice flag |
|---|---|
| Default (tech/Claude Code sessions) | `-v af_bella` |
| If user says "warm" / "Heart" | `-v af_heart` |
| If user says "male" / "Adam" | `-v am_adam` |
| If user says "Michael" | `-v am_michael` |
| If user says "British" / "Emma" | `-v bf_emma` |

Full voice list: `af_heart`, `af_bella`, `af_sky`, `bf_emma`, `bf_isabella`, `am_adam`, `am_michael`

## The steps

1. **Rewrite for TTS.** kokoro-say reads text literally. Before invoking:
   - Strip `#`, `*`, `_`, backticks, table pipes, bullet characters.
   - Replace code blocks with a short spoken description or skip.
   - Expand obvious initialisms on first use ("PR" → "pull request", "TTS" → "text to speech").
   - Break long paragraphs into short sentences — periods drive pacing.
   - Spell tricky filenames phonetically (`CLAUDE.md` → "claude markdown").
   - Keep natural commas and periods; the voice uses them for rhythm.

2. **Invoke in the background:**
   ```bash
   kokoro-say -v af_bella "cleaned text here" &
   ```
   Always background with `&` — do not block the session.

3. **Tell the user** it's playing and how to stop it.

## Stopping

Any of: "stop", "quiet", "cancel", "enough", "shush" →
```bash
pkill -f "kokoro-say"; pkill afplay
```

## Don'ts

- Never use macOS `say` — always use `kokoro-say`.
- Don't read raw markdown aloud — strip it first.
- Don't block — always background.
- Don't speak content containing secrets or credentials without confirming.
- Don't re-speak the same content twice without being asked.
