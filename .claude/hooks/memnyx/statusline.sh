#!/bin/bash
# Status line: the model and how full the context window is. Installed by
# /setup-workspace only when no status line is set in any settings scope. Outside
# the workspace root, where its settings.json does not load, the `mmn` launcher
# passes it with --settings under the same rule (see templates/memnyx.sh.tmpl).
# Yellow from 60%, red from 75%: the cue to checkpoint the ledger or run /compact.
in=$(cat)
command -v jq >/dev/null 2>&1 || { printf 'context – (jq not installed)'; exit 0; }
model=$(printf '%s' "$in" | jq -r '.model.display_name // "?"' 2>/dev/null)
n=$(printf '%s' "$in" | jq -r '.context_window.used_percentage // empty | numbers | floor' 2>/dev/null)
if [ -z "$n" ]; then printf '%s · context –' "${model:-?}"; exit 0; fi
if [ "$n" -ge 75 ]; then c='\033[31m'; elif [ "$n" -ge 60 ]; then c='\033[33m'; else c='\033[32m'; fi
printf "%s · ${c}context %s%%\033[0m" "${model:-?}" "$n"
