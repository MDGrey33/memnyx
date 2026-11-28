#!/bin/bash
# Status line: the model and how full the context window is. Installed by
# /setup-workspace only when the workspace has no statusLine of its own.
# Yellow from 60%, red from 75%: the cue to checkpoint the ledger or run /compact.
in=$(cat)
model=$(printf '%s' "$in" | jq -r '.model.display_name // "?"')
pct=$(printf '%s' "$in" | jq -r '.context_window.used_percentage // empty')
if [ -z "$pct" ]; then printf '%s · context –' "$model"; exit 0; fi
n=${pct%.*}
if [ "$n" -ge 75 ]; then c='\033[31m'; elif [ "$n" -ge 60 ]; then c='\033[33m'; else c='\033[32m'; fi
printf "%s · ${c}context %s%%\033[0m" "$model" "$n"
