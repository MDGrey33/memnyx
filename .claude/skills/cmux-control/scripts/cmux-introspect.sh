#!/usr/bin/env bash
# cmux-introspect — map every cmux tab and, for Claude Code tabs, tie it to its
# session id, live turn-state, and on-disk transcript. Pure read-only.
#
#   ./cmux-introspect.sh            # table of all surfaces across all workspaces
#   ./cmux-introspect.sh <ref>      # deep-dive one surface (read its screen + transcript tail)
set -uo pipefail
CMUX="${CMUX:-/Applications/cmux.app/Contents/Resources/bin/cmux}"
export CMUX_QUIET=1
SESS=~/.cmuxterm/claude-hook-sessions.json

# surface UUID -> claude session id, via the cmux hook session map
sid_for() { python3 -c '
import json,sys
m=json.load(open(sys.argv[1]))["activeSessionsBySurface"]
print(m.get(sys.argv[2],{}).get("sessionId",""))' "$SESS" "$1" 2>/dev/null; }

# claude session id -> transcript jsonl on disk
transcript_for() { [ -n "$1" ] && find ~/.claude/projects -name "$1.jsonl" 2>/dev/null | head -1; }

if [ $# -ge 1 ]; then
  ref="$1"
  echo "== screen =="; "$CMUX" read-screen --surface "$ref" --lines 40 2>&1
  uuid="$("$CMUX" identify --surface "$ref" 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["caller"]["surface_ref"])' 2>/dev/null)"
  echo; echo "(for transcript, pass the surface UUID; use the table view to get it)"
  exit 0
fi

printf '%-13s %-13s %-38s %-22s %s\n' WORKSPACE SURFACE SURFACE_UUID CLAUDE_STATE NAME
"$CMUX" workspace list 2>/dev/null | grep -oE 'workspace:[0-9]+' | while read -r ws; do
  state="$("$CMUX" list-status --workspace "$ws" 2>/dev/null | grep -oE 'claude_code=[^ ]+( [^ ]+)?' | sed 's/claude_code=//;s/ icon.*//' | head -1)"
  "$CMUX" list-pane-surfaces --workspace "$ws" --id-format both 2>/dev/null | while read -r line; do
    sref="$(echo "$line" | grep -oE 'surface:[0-9]+' | head -1)"
    uuid="$(echo "$line" | grep -oiE '[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}' | head -1)"
    [ -z "$sref" ] && continue
    name="$(echo "$line" | sed -E 's/^[* ]*surface:[0-9]+ [0-9A-Fa-f-]+ //;s/ +\[.*\]//')"
    printf '%-13s %-13s %-38s %-22s %s\n' "$ws" "$sref" "${uuid:--}" "${state:--}" "$name"
  done
done
