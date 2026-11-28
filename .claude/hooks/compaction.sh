#!/bin/bash
# Compaction safeguard. Claude Code can replace earlier messages with a summary at
# any time; these hooks steer what the summary keeps and point the resumed session
# back at its session marker and ledger. Wired into .claude/settings.json by
# /setup-workspace (init and sync); deployed and updated like a skill.
#
#   compaction.sh pre     PreCompact: what it prints becomes instructions for the summary
#   compaction.sh post    PostCompact: saves the summary to a log, for reassessment
#   compaction.sh resume  SessionStart (matcher "compact"): what it prints is added to context
#
# COMPACTION_LOG_DIR overrides where `post` writes, and COMPACTION_WORKSPACE
# which workspace is scanned for markers (both used by the tests).
# Never blocks compaction: every path exits 0.

# The workspace: the nearest folder above this script holding .claude/.workspace.
ws=$(cd -- "$(dirname -- "$0")" && pwd -P)
while [ "$ws" != / ] && [ ! -e "$ws/.claude/.workspace" ]; do ws=$(dirname -- "$ws"); done
[ -n "${COMPACTION_WORKSPACE:-}" ] && ws=$COMPACTION_WORKSPACE
[ -e "$ws/.claude/.workspace" ] || exit 0
input=$(cat 2>/dev/null)

# Active session markers, with their ledgers. The marker whose cc_session_id
# equals the hook's session_id is this session's; if none matches (an older
# marker, or /hello could not read the id), every active marker is listed.
markers() {
    sid=$(field .session_id)
    mine="" all=""
    for m in "$ws"/sessions/active/*.md "$ws"/projects/*/sessions/active/*.md; do
        [ -f "$m" ] || continue
        p=$(sed -n 's/^project_slug: *//p' "$m" | head -1)
        w=$(sed -n 's/^workstream_slug: *//p' "$m" | head -1)
        i=$(sed -n 's/^open_item_slug: *//p' "$m" | head -1)
        c=$(sed -n 's/^cc_session_id: *//p' "$m" | head -1)
        if [ -z "$p" ] || [ "$p" = workspace ]; then l="$ws/workstreams/$w.md"
        else l="$ws/projects/$p/workstreams/$w.md"; fi
        line=$(printf -- '- marker %s\n  project=%s workstream=%s open_item=%s\n  ledger %s' \
            "$m" "${p:-workspace}" "${w:-?}" "${i:-?}" "$l")
        all="$all$line
"
        if [ "$sid" != "?" ] && [ -n "$c" ] && [ "$c" = "$sid" ]; then mine="$mine$line
"; fi
    done
    if [ -n "$mine" ]; then
        echo "This session's marker (matched on Claude Code's session id):"
        printf '%s' "$mine"
    elif [ -n "$all" ]; then
        echo "Active session markers (none carries this session's id, so all are listed):"
        printf '%s' "$all"
    else
        echo "Active session markers: none found"
    fi
}

field() { v=$(printf '%s' "$input" | jq -r "$1 // \"?\"" 2>/dev/null); printf '%s' "${v:-?}"; }

case "${1:-}" in
pre)
    cat <<'TXT'
In the summary, keep these, in this order:
1. Every decision the user made in this conversation, with their exact words and the date.
2. Questions still open: what was asked, what the user has not answered, what waits on whom.
3. Repository state: branch, latest commits, what is pushed, open pull requests.
4. The path of every file written or changed in this conversation.
5. The next step.
6. The session markers and ledgers listed below, word for word.
Point to files rather than restating their content: the files survive, the conversation does not.
TXT
    echo
    markers
    ;;
post)
    dir=${COMPACTION_LOG_DIR:-$ws/artifacts/compaction-safeguard/log}
    mkdir -p "$dir"
    t=$(field .trigger); case "$t" in manual | auto) ;; *) t=unknown ;; esac
    f="$dir/$(date +%Y-%m-%d-%H%M%S)-$t.md"
    {
        echo "# Compaction $(date +%Y-%m-%dT%H:%M:%S%z)"
        echo
        echo "- trigger: $(field .trigger)"
        echo "- session: $(field .session_id)"
        echo "- transcript: $(field .transcript_path)"
        echo
        echo "## The summary as produced"
        echo
        printf '%s' "$input" | jq -r '.compact_summary // "(no summary in the hook input)"' 2>/dev/null
    } >"$f"
    ;;
resume)
    cat <<'TXT'
Earlier messages in this conversation were replaced by a summary. Before acting on anything:
read the session marker and the ledger for the work in progress (listed below), and trust them
over the summary where the two differ. If several markers are listed, use the one whose project
and workstream match the summary. Decisions made from here on go into that ledger in the same turn.
TXT
    echo
    markers
    ;;
esac
exit 0
