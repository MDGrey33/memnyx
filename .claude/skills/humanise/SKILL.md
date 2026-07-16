---
name: humanise
description: Rewrite text so it reads like a person wrote it, not an LLM — strip the AI "tells" (em-dash overuse, "it's not just X, it's Y", rule-of-three everywhere, corporate diction like delve/leverage/robust, reflexive hedging, mechanical transitions and summary-closers, uniform sentence rhythm) while preserving meaning and precision. Register-aware (Slack/peer, internal email, external email, formal doc, marketing). Use when the user says "humanise this", "humanize", "make it sound human", "remove the AI tells", "de-AI this", "make it sound less like a bot", "/humanise", or asks why a draft reads machine-generated.
user_invocable: true
args: <text | file path | "last response"> [register: slack|internal|external|formal|marketing] [--light | --deep] [--diagnose]
allowed-tools: Read, Write, Edit, Bash(python3 *)
---

## Model Selection

See `~/.claude/skills/_shared/MODEL_SELECTION.md`.

- **Default model:** Sonnet 4.6 — the rewrite is judgment, not find/replace. Tells must be removed *without* losing meaning, precision, or the author's voice.
- **Demote to Haiku when:** `--diagnose` only (the detector is a pure Python script — no LLM needed to run it).
- **Promote to Opus when:** rewriting a long document (1000+ words) in `--deep` mode where structural pacing across many sections matters.

## What this is

Two halves, like `say-it` (strip engine + judgment):

1. **The detector** — `humanise.py`, a deterministic script. It *measures* tells (counts em-dashes, flags corporate words, scores burstiness). It never rewrites.
2. **The rewrite** — the model reads the detector's report + the rules below and rewrites by hand. The judgment is the model's; the script just points at what to fix.

**The goal is authentically human prose, not gaming an AI-detector.** A human reader spots tells before a detector does. Write for the reader.

## The procedure

1. **Get the text.** From `args` (inline / file path / "last response" = the most recent substantive thing I produced, not the reply I'm about to give). If it's a file, `Read` it.
2. **Pick the register.** If the user named one, use it. Otherwise infer from where it's going (a Slack thread → `slack`; a client → `external`). State the register you chose in one line so the user can correct it.
3. **Diagnose.** Run `python3 ~/.claude/skills/humanise/humanise.py <file-or---text>`. Read the report. It tells you exactly which tells are present and how bad.
4. **Rewrite** per the taxonomy + register below. `--light` = the three fast passes (diction, transitions/hedging, punctuation). `--deep` = all of it including structure, antithesis, tone, pacing. Default to `--light` for short messages, `--deep` for anything over a couple of paragraphs.
5. **Re-diagnose** the rewrite. Confirm the score dropped. If burstiness is still low, vary sentence length again.
6. **Deliver** the rewritten text. Name the register and (briefly) the main things you changed, so the user can learn the pattern and veto. Don't show a 10-item diff unless asked — one line of "what moved" is enough.

`--diagnose` alone = run step 3 and return the report only. No rewrite. Use it to answer "does this read like AI?".

## The taxonomy → the fix (this is the knowledge)

**Punctuation & rhythm**
- *Em-dash overuse* (every few sentences) → replace ~2/3 with commas, parentheses, periods. Keep a dash only for a genuine sharp break.
- *Low burstiness* (every sentence 15-25 words) → deliberately vary. Put a 5-word sentence next to a 35-word one. Add a fragment. Human rhythm is uneven.

**Structure**
- *Rule of three everywhere* ("fast, reliable, and scalable") → drop to two, or go to four/five (uneven), or break the grammar of one item.
- *Mechanical parallelism* (every clause same shape) → make one item a different sentence type.
- *Antithesis* ("not just X, it's Y" / "isn't merely… it's") → flatten to a direct claim. Keep the contrast only if it's real, and then rephrase off the formula.

**Transitions & signposting**
- *"Moreover / Furthermore / Additionally"* → delete ~80%. Let the content imply the link, or just use "and".
- *Summary-closers* ("In conclusion / Ultimately / At the end of the day") → delete entirely. End on the last real point.

**Diction** (swap corporate-safe abstractions for plain, specific words)
- delve→look into · leverage→use · robust→strong/reliable · seamless→smooth · foster→encourage · navigate→handle · underscore→show · pivotal→key · holistic→whole · transformative→big/major · innovative→new · ecosystem→system · empower→let/help · cutting-edge→new · facilitate→make easier · utilize→use · myriad/plethora→lots · realm/landscape→just name the thing · synergy/tapestry→delete.
- *Empty intensifiers* (highly, truly, extremely, incredibly, remarkably) → delete, or replace with a specific ("works for most teams in under five minutes").

**Hedging & filler**
- "It's worth noting / It's important to / It should be noted that / can help to" → delete the windup, start with the claim.
- *Restating the prompt* before answering → cut the first sentence or two; open on the answer.

**Tone & affect**
- *Relentless positivity* (no downsides) → name a real trade-off or limit. Humans hedge with "but / though".
- *Emoji-bullet listicle-itis* → convert to prose unless the list genuinely aids reading (steps, options).
- *Title-Case Headers* → sentence case.

**Meta**
- *Over-explaining the obvious* → delete definitions the audience already knows.
- *Uniform section length* → let one section be short, one sprawl.

## Register table (match the medium)

| Register | Contractions | Fragments | Hedging | Idioms | Avg sentence |
|---|---|---|---|---|---|
| `slack` (peer chat) | always | frequent | minimal | yes | 8-12w |
| `internal` (email) | common | occasional | moderate | some | 12-18w |
| `external` (client) | rare | no | moderate (polite) | rare | 15-22w |
| `formal` (doc/spec) | never | no | acceptable | never | 18-28w |
| `marketing` | common | frequent | minimal | some | 10-16w |

Note: in `formal`, you still vary sentence length and prefer "But" over "However" — humanising a formal doc means *naturalness*, not casualness. In `external`, keep the politeness ("thanks", "let me know") — that's human, not filler.

## What to PRESERVE (the limits — over-humanising is its own failure)

- **Never introduce factual errors.** Humanise the prose *around* the facts, not the facts. "OAuth 2.0" stays "OAuth 2.0", not "the login thing".
- **Don't strip necessary precision.** "100 requests/minute" must not become "a rate limit".
- **Never fake typos** or force slang that isn't the author's. Sloppiness reads as careless, not authentic.
- **Don't lose meaning chasing brevity**, and don't add variation for its own sake (thesaurus abuse, fragments everywhere = chaos).
- **Don't flatten the author's actual voice.** If the source already sounds like them, leave it. The job is removing the machine shine, not imposing a new style.

## The detector

```bash
python3 ~/.claude/skills/humanise/humanise.py <file>          # readable report
python3 ~/.claude/skills/humanise/humanise.py --json <file>   # machine-readable
python3 ~/.claude/skills/humanise/humanise.py --text "..."    # inline
cat draft.md | python3 ~/.claude/skills/humanise/humanise.py  # stdin
```

Output: a `tell_score` + verdict (`reads human` ≤3 · `some tells` ≤10 · `strong AI fingerprint` >10), sentence-length burstiness (stdev <6 on enough text = too uniform), dash density per 100 words, and the actual corporate words / hedges / closers / antithesis / triads / emoji it found. Calibration reference: a deliberately AI-heavy paragraph scores ~29; a hand-humanised peer message scores ~5.

## Don'ts

- Don't run the rewrite without diagnosing first — the report tells you where to aim.
- Don't claim it's "humanised" without re-running the detector to confirm the score dropped.
- Don't apply `marketing`/`slang` register to a formal or client deliverable.
- Don't humanise text that contains secrets/PII for sharing without also considering `sanitizer`.
