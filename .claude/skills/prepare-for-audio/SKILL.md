---
name: prepare-for-audio
description: Turn message text into TTS-ready text — strip markdown (so a TTS engine never speaks "asterisk asterisk"), and in voice mode also drop emoji. A single shared cleaner meant to be reused by every channel that speaks text aloud (a local speak command, a chat-bot voice bridge, etc). Use whenever text is about to be synthesized to audio, or whenever a channel renders raw markdown.
---

# prepare-for-audio — one cleaner, every speak channel

The cleaning that makes text safe to speak is easy to leave as a *habit* baked
into a single "speak" skill — a prose instruction the model applies by hand.
That breaks the moment there's no model in the loop at send time: a dumb shell
sender or automated bridge feeds raw `**markdown**` straight to the TTS engine
and it reads "asterisk asterisk" aloud. This skill makes the cleaning a real,
deterministic, shared component instead of a habit that only holds when a
model is watching.

## The engine (single source of truth)

Put one small script under version control, e.g. `scripts/strip-markdown.py`,
and have every voice-output path call it instead of re-implementing the logic
inline:

```
echo "**hi** `x` 🤍" | python3 scripts/strip-markdown.py          # text:  "hi x 🤍"   (keeps emoji)
echo "**hi** `x` 🤍" | python3 scripts/strip-markdown.py voice    # voice: "hi x"      (drops emoji)
```

It strips bold/italic/underscore/strikethrough/code/headers/blockquote/bullets/
links/table-pipes/stray asterisks; keeps normal punctuation, apostrophes, and
non-Latin text. The optional `voice` arg additionally removes emoji and
pictographs, which a TTS engine would otherwise mispronounce or stumble on.

## Speak = prepare-for-audio THEN deliver. Delivery differs by channel

| Channel | Prepare | Deliver |
|---|---|---|
| **Local** (terminal / desktop session) | `strip-markdown.py voice` | local TTS engine → speakers (your assistant's speak-aloud skill) |
| **Remote** (chat bot / mobile bridge) | `strip-markdown.py voice` | synth → voice-note attachment on the chat channel |

So the *cleaning* is shared (this skill); only the *delivery* is
channel-specific. A plain-text sender for the same channel should also run
the text-mode engine so the chat never shows raw `**` either.

## When to use

- Before any TTS synthesis.
- Any time output goes to a surface that does not render markdown (a chat
  channel with no markdown parse mode, a plain-text channel, a TTS pipe).
- A "speak this aloud" skill should delegate its "rewrite for TTS" step here
  instead of hand-stripping markdown inline each time.
