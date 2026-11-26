#!/usr/bin/env bash
# One day's GitHub activity for one person, read with a named gh account's
# token. Used by /collect-my-activity and /collect-team-activity.
#
# Usage: bash .claude/skills/_shared/scripts/gh-activity.sh <token-handle> <subject> <start> <end>
#   token-handle  gh account whose token runs the searches (gh auth token --user)
#   subject       GitHub login to report on, or @me for the token-handle's user
#   start, end    ISO timestamps with offset, e.g. 2026-11-26T00:00:00+04:00
#
# Why a fixed script: sub-agents cannot answer permission prompts, and Claude
# Code refuses a top-level `$(...)` even under a matching allow rule. One
# script at a fixed workspace-relative path can be allowed; letting agents write and
# run their own scripts would need `Bash(bash *)`, which allows anything.
# The token stays inside this process; it is never printed.
#
# Output: four sections, each a header line then the gh JSON array:
#   == prs_authored / == prs_reviewed / == issues_authored / == issues_commented
# A section whose array holds 100 items hit the limit and may be truncated.
# Exit codes: 2 bad arguments; 3 no token for the account; 4 a search failed,
# after the run's single retry if it was rate-limited (gh's error is on
# stderr, and sections printed before it are complete); 5 gh is not installed.
# Any other code (1) is unexpected.

set -euo pipefail

if [ "$#" -ne 4 ]; then
  echo "usage: gh-activity.sh <token-handle> <subject> <start> <end>" >&2
  exit 2
fi

token_handle=$1
subject=$2
start=$3
end=$4

login_re='^[A-Za-z0-9](-?[A-Za-z0-9]){0,38}$'
ts_re='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([+-][0-9]{2}:[0-9]{2}|Z)$'

if ! [[ $token_handle =~ $login_re ]]; then
  echo "gh-activity: invalid token-handle" >&2; exit 2
fi
if [ "$subject" != "@me" ] && ! [[ $subject =~ $login_re ]]; then
  echo "gh-activity: invalid subject" >&2; exit 2
fi
if ! [[ $start =~ $ts_re ]] || ! [[ $end =~ $ts_re ]]; then
  echo "gh-activity: start and end must be ISO timestamps with an offset" >&2; exit 2
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh-activity: gh is not installed" >&2; exit 5
fi

if ! GH_TOKEN=$(gh auth token --user "$token_handle" 2>/dev/null) || [ -z "$GH_TOKEN" ]; then
  echo "gh-activity: no token for gh account '$token_handle'. Run: gh auth login --hostname github.com" >&2
  exit 3
fi
export GH_TOKEN

range="${start}..${end}"

errfile=$(mktemp)
trap 'rm -f "$errfile"' EXIT

# One search. The first rate-limited search in a run waits and retries once: a
# team run fans out many agents and GitHub's search API allows about 30 a
# minute. Only one wait per run, so the script stays inside the Bash tool's
# default two-minute timeout.
retried=0
run() {
  local label=$1; shift
  local out attempt
  for attempt in 1 2; do
    if out=$(gh search "$@" --limit 100 2>"$errfile"); then
      echo "== $label"
      printf '%s\n' "$out"
      return 0
    fi
    if [ "$attempt" = 1 ] && [ "$retried" = 0 ] && grep -qi 'rate limit' "$errfile"; then
      retried=1
      sleep "${GH_ACTIVITY_RETRY_WAIT:-60}"
      continue
    fi
    break
  done
  cat "$errfile" >&2
  echo "gh-activity: search failed: $label" >&2
  exit 4
}

run prs_authored     prs    --author="$subject"      --created="$range" --json number,title,url,repository,state,createdAt,updatedAt
run prs_reviewed     prs    --reviewed-by="$subject" --updated="$range" --json number,title,url,repository,state,updatedAt
run issues_authored  issues --author="$subject"      --created="$range" --json number,title,url,repository,state
run issues_commented issues --commenter="$subject"   --updated="$range" --json number,title,url,repository,updatedAt
