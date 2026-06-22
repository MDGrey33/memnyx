---
name: setup-voice
description: Install a local neural voice interface for Claude Code on macOS Apple Silicon. Wires mlx-whisper (STT) + Kokoro TTS (offline neural voices) into voice-claude and vtranscribe CLI scripts. Two voice contexts — personal (af_heart) and tech (af_bella). Multi-session safe — concurrent sessions speak in turn (global lock) and announce their name. No cloud APIs, no API keys.
user_invocable: true
---

# Setup Voice — Local Neural Voice Interface (macOS Apple Silicon)

Installs a fully local voice pipeline:

- **STT:** `mlx-whisper` — OpenAI Whisper on Apple MLX, Metal-accelerated
- **TTS:** `kokoro-onnx` — Kokoro 82M neural TTS, offline, two context voices
- **Recording:** `sox` (`rec`) — microphone capture with silence detection
- **Scripts:** `voice-claude`, `vtranscribe`, `kokoro-say` in `~/.local/bin/`

---

## Prerequisites

- macOS on Apple Silicon (M1 or later)
- Homebrew (`brew`)
- `uv` — `brew install uv`
- Python 3.12 — `brew install python@3.12`
- `ffmpeg` — `brew install ffmpeg`
- `~/.local/bin/` on `$PATH` — the standard per-user bin dir; `uv` (above) already installs here, so it is usually present and on `PATH`. Create it and add it to `PATH` if missing.
- `claude` CLI installed and authenticated

---

## Step 1 — Install system dependencies

```bash
brew install sox ffmpeg
```

`sox` provides the `rec` command for microphone capture. `ffmpeg` is required by mlx-whisper for audio conversion.

---

## Step 2 — Install mlx-whisper (STT)

```bash
uv tool install --python 3.12 mlx-whisper
```

Installs `mlx_whisper` CLI globally via uv. Uses Apple MLX for Metal-accelerated transcription.

**Verify:**

```bash
mlx_whisper --help
```

Model (`mlx-community/whisper-turbo`) downloads automatically on first transcription (~1.5 GB, one-time).

---

## Step 3 — Install Kokoro TTS (offline neural voices)

```bash
uv venv --python 3.12 ~/.local/share/kokoro-venv
~/.local/share/kokoro-venv/bin/python -m ensurepip
~/.local/share/kokoro-venv/bin/python -m pip install kokoro-onnx soundfile
```

Download model files (~337 MB total, one-time):

```bash
mkdir -p ~/.cache/kokoro
curl -L -o ~/.cache/kokoro/kokoro-v1.0.onnx \
  "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
curl -L -o ~/.cache/kokoro/voices-v1.0.bin \
  "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
```

---

## Step 4 — Create `kokoro-say`

Create `~/.local/bin/kokoro-say` with the content below, then `chmod +x ~/.local/bin/kokoro-say`.

```
#!/usr/bin/env bash
# Speak text using Kokoro TTS (local neural, no internet).
# Usage: kokoro-say [-v VOICE] "text"
#   Voices: af_heart (personal/default)  af_bella (tech)
#           af_sky  bf_emma  bf_isabella  am_adam  am_michael
#
# Multi-session safe: when several Claude Code sessions speak at once, playback
# is serialized by a global lock so they never overlap, and each utterance is
# prefixed with the session's short name (see kokoro-session-name) so you can
# tell which session is talking.
set -euo pipefail

VOICE="${KOKORO_VOICE:-af_heart}"
while getopts ":v:h" opt; do
  case "$opt" in
    v) VOICE="$OPTARG" ;;
    h) printf 'Usage: kokoro-say [-v voice] "text"\n'; exit 0 ;;
    :) printf 'Option -%s requires an argument.\n' "$OPTARG" >&2; exit 1 ;;
    *) printf 'Unknown option: -%s\n' "$OPTARG" >&2; exit 1 ;;
  esac
done
shift $((OPTIND - 1))

TEXT="${*}"
if [[ -z "$TEXT" ]]; then
  read -r -d '' TEXT || true
fi

# Prefix this session's short name so concurrent sessions are distinguishable
# when speaking. Empty when no name can be resolved — set KOKORO_SESSION_NAME to
# force one, or KOKORO_NO_NAME=1 to suppress the prefix entirely.
if [[ "${KOKORO_NO_NAME:-0}" != "1" ]] && command -v kokoro-session-name >/dev/null 2>&1; then
  SESSION_NAME="$(kokoro-session-name 2>/dev/null || true)"
  if [[ -n "$SESSION_NAME" ]]; then
    TEXT="${SESSION_NAME}. ${TEXT}"
  fi
fi

TMP=$(mktemp /tmp/kokoro.XXXXXX.wav)
trap 'rm -f "$TMP"' EXIT

~/.local/share/kokoro-venv/bin/python - "$VOICE" "$TEXT" "$TMP" << 'PYEOF'
import sys, warnings
warnings.filterwarnings("ignore")
import soundfile as sf
from kokoro_onnx import Kokoro

voice, text, outfile = sys.argv[1], sys.argv[2], sys.argv[3]
import os
cache = os.path.expanduser("~/.cache/kokoro")
kokoro = Kokoro(f"{cache}/kokoro-v1.0.onnx", f"{cache}/voices-v1.0.bin")
samples, sr = kokoro.create(text, voice=voice, speed=1.0, lang="en-us")
sf.write(outfile, samples, sr)
PYEOF

# Serialize playback across ALL sessions via a global advisory lock so two
# sessions never speak over each other. fcntl.flock auto-releases when this
# process exits (even on crash / Ctrl-C), so a dead session can't wedge the
# queue. Synthesis above already ran in parallel; only audible playback waits.
#
# We BLOCK and wait our turn rather than poll-then-give-up: afplay always exits
# when its wav ends, so the lock is held only for the length of real playback,
# and a held lock auto-releases if the holder dies. The alarm is a last-resort
# guard against a genuinely wedged audio device, set far above any real speech
# queue — so a burst of long utterances queues cleanly instead of stacking.
KOKORO_PLAY_WAV="$TMP" /usr/bin/python3 - << 'PYEOF'
import fcntl, os, signal, subprocess

wav      = os.environ["KOKORO_PLAY_WAV"]
lockf    = os.environ.get("KOKORO_LOCK", "/tmp/kokoro-say.lock")
backstop = int(float(os.environ.get("KOKORO_LOCK_TIMEOUT", "600")))

class _Timeout(Exception):
    pass

def _on_alarm(signum, frame):
    raise _Timeout()  # raise so flock unblocks (PEP 475 would otherwise auto-retry)

f = open(lockf, "w")
signal.signal(signal.SIGALRM, _on_alarm)
signal.alarm(backstop)
try:
    fcntl.flock(f, fcntl.LOCK_EX)   # block until it is our turn — never overlap
except _Timeout:
    pass                            # wedged > backstop s: proceed rather than hang forever
finally:
    signal.alarm(0)

subprocess.run(["afplay", wav])
# Lock released automatically when this process exits and the fd closes.
PYEOF
```

**Verify:**

```bash
kokoro-say "Hello, voice interface ready."
```

---

## Step 4b — Create `kokoro-session-name`

This helper resolves the short name `kokoro-say` speaks before each utterance.
It is optional — without it, `kokoro-say` simply adds no prefix. Create
`~/.local/bin/kokoro-session-name`, then `chmod +x ~/.local/bin/kokoro-session-name`.

Resolution order: `$KOKORO_SESSION_NAME` (explicit, any terminal) → the current
[cmux](https://cmux.io) tab title (automatic, when running under cmux) → empty.

```
#!/usr/bin/env bash
# Resolve a short spoken name for the CURRENT session, used by kokoro-say to
# prefix speech so concurrent sessions don't blur together. Resolution order:
#   1. $KOKORO_SESSION_NAME              explicit override (works in any terminal)
#   2. cmux tab title via $CMUX_PANEL_ID automatic, when running under cmux
#   3. (empty)                           kokoro-say then adds no prefix
# Always exits 0; never blocks kokoro-say on failure.
set -uo pipefail

MAXLEN="${KOKORO_NAME_MAXLEN:-22}"

if [[ -n "${KOKORO_SESSION_NAME:-}" ]]; then
  printf '%s\n' "${KOKORO_SESSION_NAME:0:$MAXLEN}"
  exit 0
fi

# cmux persists each tab/panel (incl. its auto-derived title) in a session JSON,
# keyed by the panel id that cmux exports as $CMUX_PANEL_ID.
CMUX_JSON="${CMUX_SESSION_JSON:-$HOME/Library/Application Support/cmux/session-com.cmuxterm.app.json}"
if [[ -n "${CMUX_PANEL_ID:-}" && -f "$CMUX_JSON" ]]; then
  MAXLEN="$MAXLEN" PANEL_ID="$CMUX_PANEL_ID" python3 - "$CMUX_JSON" <<'PY' 2>/dev/null
import json, os, re, sys

panel_id = os.environ.get("PANEL_ID", "")
maxlen   = int(os.environ.get("MAXLEN", "22"))
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)

found = {"title": None}
def walk(o):
    if isinstance(o, dict):
        if o.get("id") == panel_id and o.get("title"):
            found["title"] = o["title"]
        for v in o.values():
            walk(v)
    elif isinstance(o, list):
        for v in o:
            walk(v)
walk(data)

# Strip leading status glyph / spinner / punctuation, keep first real text.
raw = re.sub(r"^[^\w]+", "", found["title"] or "").strip()
if not raw:
    sys.exit(0)
if len(raw) > maxlen:        # shorten on a word boundary
    cut = raw[:maxlen]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    raw = cut.rstrip()
print(raw)
PY
fi
```

**Verify:**

```bash
KOKORO_SESSION_NAME="Alpha" kokoro-say "naming works"   # says: Alpha. naming works
```

---

## Step 5 — Create `vtranscribe`

Create `~/.local/bin/vtranscribe` with the content below, then `chmod +x ~/.local/bin/vtranscribe`.

```
#!/usr/bin/env bash
# Record from mic until silence, print transcript to stdout.
# Env override: WHISPER_MODEL (default: mlx-community/whisper-turbo)
set -euo pipefail

MODEL="${WHISPER_MODEL:-mlx-community/whisper-turbo}"
TMP=$(mktemp -d /tmp/vtranscribe.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

printf '🎤 Listening... (stop speaking to send)\n' >&2
rec -r 16000 -c 1 -b 16 "$TMP/audio.wav" \
  silence 1 0.1 3% 1 1.5 3% 2>/dev/null

SIZE=$(wc -c < "$TMP/audio.wav")
if (( SIZE < 10000 )); then
  printf '⚠️  No audio detected.\n' >&2
  exit 1
fi

printf '📝 Transcribing...\n' >&2
mlx_whisper "$TMP/audio.wav" \
  --model "$MODEL" \
  --output-format txt \
  --output-dir "$TMP" \
  --output-name transcript \
  2>/dev/null

tr -d '\n' < "$TMP/transcript.txt" | xargs
```

**Verify:**

```bash
vtranscribe   # speak a sentence, check output
```

---

## Step 6 — Create `voice-claude`

Create `~/.local/bin/voice-claude` with the content below, then `chmod +x ~/.local/bin/voice-claude`.

```
#!/usr/bin/env bash
# Voice interface for Claude Code.
# Usage: voice-claude [-l] [-c CONTEXT] [-m MODEL]
#   -l  loop mode (Ctrl-C to exit)
#   -c  context: personal (default) | tech
#       personal → af_heart  (warm, everyday)
#       tech     → af_bella  (clear, technical)
#   -m  Whisper model (env: VC_MODEL)
set -euo pipefail

MODEL="${VC_MODEL:-mlx-community/whisper-turbo}"
CONTEXT="${VC_CONTEXT:-personal}"
LOOP=false
SAY_PID=""

declare -A VOICE_MAP
VOICE_MAP[personal]="af_heart"
VOICE_MAP[tech]="af_bella"

while getopts ":lc:m:h" opt; do
  case "$opt" in
    l) LOOP=true ;;
    c) CONTEXT="$OPTARG" ;;
    m) MODEL="$OPTARG" ;;
    h) printf 'Usage: voice-claude [-l] [-c personal|tech] [-m model]\n'; exit 0 ;;
    :) printf 'Option -%s requires an argument.\n' "$OPTARG" >&2; exit 1 ;;
    *) printf 'Unknown option: -%s\n' "$OPTARG" >&2; exit 1 ;;
  esac
done

speak() {
  local voice="${VOICE_MAP[$CONTEXT]:-af_heart}"
  kokoro-say -v "$voice" "$1" 2>/dev/null &
  SAY_PID=$!
}

cleanup() {
  [[ -n "$SAY_PID" ]] && kill "$SAY_PID" 2>/dev/null || true
  printf '\nBye.\n'
  exit 0
}
trap cleanup INT TERM

detect_context_switch() {
  local p
  p=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  if echo "$p" | grep -qE "switch to tech|coding mode|tech mode"; then
    [[ "$CONTEXT" != "tech" ]] && { CONTEXT="tech"; printf '  [switching to Bella]\n'; }
  elif echo "$p" | grep -qE "switch to personal|personal mode"; then
    [[ "$CONTEXT" != "personal" ]] && { CONTEXT="personal"; printf '  [switching to Heart]\n'; }
  fi
}

one_turn() {
  [[ -n "$SAY_PID" ]] && kill "$SAY_PID" 2>/dev/null || true
  SAY_PID=""

  local TMP
  TMP=$(mktemp -d /tmp/vc.XXXXXX)

  printf '\n🎤 Listening... (stop speaking to send)\n'
  rec -r 16000 -c 1 -b 16 "$TMP/audio.wav" \
    silence 1 0.1 3% 1 1.5 3% 2>/dev/null

  local SIZE
  SIZE=$(wc -c < "$TMP/audio.wav")
  if (( SIZE < 10000 )); then
    printf '⚠️  No audio detected, try again.\n'
    rm -rf "$TMP"
    return 0
  fi

  printf '📝 Transcribing...\n'
  mlx_whisper "$TMP/audio.wav" \
    --model "$MODEL" \
    --output-format txt \
    --output-dir "$TMP" \
    --output-name transcript \
    2>/dev/null

  local PROMPT
  PROMPT=$(tr -d '\n' < "$TMP/transcript.txt" | xargs)
  rm -rf "$TMP"

  if [[ -z "$PROMPT" ]]; then
    printf '⚠️  Nothing heard, try again.\n'
    return 0
  fi

  detect_context_switch "$PROMPT"

  printf '\nYou: %s\n\n' "$PROMPT"
  printf '🤖 ...\n'

  local RESPONSE
  RESPONSE=$(claude -p "$PROMPT" 2>/dev/null)

  printf '\nClaude [%s]: %s\n' "$CONTEXT" "$RESPONSE"
  speak "$RESPONSE"
}

if $LOOP; then
  printf 'Voice loop active — Ctrl-C to exit.\n'
  printf 'Context: %s (%s)\n\n' "$CONTEXT" "${VOICE_MAP[$CONTEXT]}"
  while true; do
    one_turn
  done
else
  one_turn
  [[ -n "$SAY_PID" ]] && wait "$SAY_PID" 2>/dev/null || true
fi
```

---

## Voices reference

| Voice | ID | Character |
|---|---|---|
| Heart | `af_heart` | Warm, natural — everyday conversations |
| Bella | `af_bella` | Clear, precise — technical/coding sessions |
| Sky | `af_sky` | Bright, energetic — alternative option |
| Emma | `bf_emma` | British female |
| Isabella | `bf_isabella` | British female, warmer |
| Adam | `am_adam` | American male |
| Michael | `am_michael` | American male, deeper |

---

## Usage

| Command | What it does |
|---|---|
| `voice-claude` | Single voice turn, personal context |
| `voice-claude -l` | Continuous loop, Ctrl-C to exit |
| `voice-claude -c tech` | Loop or single turn in tech context |
| `voice-claude -c tech -l` | Loop in tech context |
| `vtranscribe` | Record and print transcript only |

**Mid-loop context switching** — just say it:

- "switch to tech" or "coding mode" → Bella
- "switch to personal" or "personal mode" → Heart

**Within a Claude Code session:**

```
! vtranscribe
```

Runs `vtranscribe` inline so the transcript lands directly in the conversation.

---

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `VC_CONTEXT` | `personal` | Starting context |
| `VC_MODEL` | `mlx-community/whisper-turbo` | Whisper model |
| `WHISPER_MODEL` | `mlx-community/whisper-turbo` | For `vtranscribe` |
| `KOKORO_VOICE` | `af_heart` | For `kokoro-say` direct calls |
| `KOKORO_SESSION_NAME` | (cmux title) | Name `kokoro-say` speaks before each utterance |
| `KOKORO_NO_NAME` | `0` | Set `1` to suppress the session-name prefix |
| `KOKORO_NAME_MAXLEN` | `22` | Max length of the spoken session name |
| `KOKORO_LOCK` | `/tmp/kokoro-say.lock` | Global playback lock (shared by all sessions) |
| `KOKORO_LOCK_TIMEOUT` | `600` | Anti-wedge backstop: sessions block and queue for the playback lock; this only caps the wait if the audio device is genuinely stuck |

---

## Troubleshooting

**No audio detected** — sox mic permission: System Settings → Privacy & Security → Microphone → enable Terminal / your shell.

**mlx_whisper not found** — run `uv tool update mlx-whisper` or check `~/.local/bin` is on `$PATH`.

**Kokoro model missing** — re-run the `curl` downloads in Step 3; check `~/.cache/kokoro/` contains both files.

**`rec` not found** — `brew install sox` (sox provides `rec`).

**First transcription is slow** — the Whisper model downloads (~1.5 GB) on first run. Subsequent runs are fast.
