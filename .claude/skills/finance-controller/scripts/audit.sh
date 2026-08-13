#!/usr/bin/env bash
# finance-controller audit — deterministic scan of Claude Code setup.
# No LLM calls. Pure bash + awk + jq. Emits JSON to stdout.
set -euo pipefail

SKILLS_DIR="${HOME}/.claude/skills"
CLAUDE_MD="${CLAUDE_MD:-./CLAUDE.md}"
# Skill output belongs under artifacts/<skill-slug>/, never in contributions/ --
# that directory is the /contribute -> /pull-contributions staging queue.
OUT_DIR="${OUT_DIR:-artifacts/finance-controller}"
mkdir -p "$OUT_DIR"

# Rough tokens-per-char: 1 token ≈ 4 chars (English, conservative).
bytes_to_tokens() { awk -v b="$1" 'BEGIN { printf "%d", b/4 }'; }

# ---------- CLAUDE.md ----------
if [[ -f "$CLAUDE_MD" ]]; then
  cmd_bytes=$(wc -c <"$CLAUDE_MD" | tr -d ' ')
  cmd_tokens=$(bytes_to_tokens "$cmd_bytes")
else
  cmd_bytes=0
  cmd_tokens=0
fi

# ---------- Always-loaded @-imports (CLAUDE.md) ----------
# Every file CLAUDE.md @-imports (memory index, agent-guardrails.md) loads on
# every session start — measure each one against the always-loaded budget.
imports_json="[]"
if [[ -f "$CLAUDE_MD" ]]; then
  claude_md_dir=$(cd "$(dirname "$CLAUDE_MD")" && pwd)
  imports_json=$(
    { grep -oE '(^|[[:space:]])@[A-Za-z0-9._~/-]+' "$CLAUDE_MD" 2>/dev/null || true; } \
      | sed -E 's/^[[:space:]]*@//' | sort -u \
      | while IFS= read -r rel; do
          p="$rel"
          [[ "$p" == "~/"* ]] && p="${HOME}/${p#\~/}"
          [[ "$p" != /* ]] && p="$claude_md_dir/$p"
          [[ -f "$p" ]] || continue
          bytes=$(wc -c <"$p" | tr -d ' ')
          tokens=$(bytes_to_tokens "$bytes")
          jq -n --arg path "$rel" --argjson bytes "$bytes" --argjson tokens "$tokens" \
            '{path:$path, bytes:$bytes, tokens:$tokens}'
        done | jq -s '.'
  )
fi

# ---------- Skills ----------
skills_json="[]"
if [[ -d "$SKILLS_DIR" ]]; then
  skills_json=$(
    for d in "$SKILLS_DIR"/*/; do
      [[ -d "$d" ]] || continue
      name=$(basename "$d")
      [[ "$name" == "_archive" || "$name" == "_shared" ]] && continue
      skill_md="$d/SKILL.md"
      [[ -f "$skill_md" ]] || continue
      bytes=$(wc -c <"$skill_md" | tr -d ' ')
      tokens=$(bytes_to_tokens "$bytes")
      model=$(awk 'tolower($0) ~ /default model:/ { sub(/.*[Dd]efault model:[[:space:]]*/,""); print; exit }' "$skill_md" | tr -d '*' | awk '{$1=$1; print}')
      refs_shared=$(grep -c "_shared/MODEL_SELECTION" "$skill_md" 2>/dev/null | head -1)
      [[ -z "$refs_shared" ]] && refs_shared=0
      jq -n --arg name "$name" \
            --argjson bytes "$bytes" \
            --argjson tokens "$tokens" \
            --arg model "${model:-}" \
            --argjson refs_shared "$refs_shared" \
            '{name:$name, bytes:$bytes, tokens:$tokens, model:$model, references_shared_policy:($refs_shared>0)}'
    done | jq -s '.'
  )
fi

# ---------- MCPs ----------
mcp_json="[]"
if command -v claude >/dev/null 2>&1; then
  mcp_raw=$(claude mcp list 2>/dev/null || true)
  if [[ -n "$mcp_raw" ]]; then
    mcp_json=$(
      echo "$mcp_raw" \
        | awk -F':' '
            /Connected|Failed|Needs authentication|✓|✗|!/ {
              name=$1; gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
              status="unknown"
              if (match($0, /✓ Connected/))                status="connected"
              else if (match($0, /✗ Failed/))               status="failed"
              else if (match($0, /Needs authentication/))   status="needs_auth"
              print name "\t" status
            }
          ' \
        | jq -R -s 'split("\n") | map(select(length>0)) | map(split("\t")) | map({name:.[0], status:.[1]})'
    )
  fi
fi

mcp_count=$(echo "$mcp_json" | jq 'length')
mcp_connected=$(echo "$mcp_json" | jq '[.[] | select(.status=="connected")] | length')

# ---------- Flags ----------
flags=$(jq -n \
  --argjson cmd_tokens "$cmd_tokens" \
  --argjson skills "$skills_json" \
  --argjson imports "$imports_json" \
  --argjson mcp_count "$mcp_count" \
  --argjson mcp_connected "$mcp_connected" '
  {
    claude_md: (
      if   $cmd_tokens > 8000 then "red"
      elif $cmd_tokens > 5000 then "orange"
      elif $cmd_tokens > 3000 then "yellow"
      else "green" end
    ),
    always_loaded_imports: [ $imports[] | {path, tokens, severity: (
      if   .tokens > 3000 then "red"
      elif .tokens > 2500 then "orange"
      elif .tokens > 2000 then "yellow"
      else "green" end
    )} ],
    mcps: (
      if   $mcp_connected > 12 then "red"
      elif $mcp_connected > 8  then "orange"
      elif $mcp_connected > 5  then "yellow"
      else "green" end
    ),
    bloated_skills: [ $skills[] | select(.tokens > 1500) | {name, tokens, severity: (if .tokens>3000 then "red" elif .tokens>1500 then "orange" else "yellow" end)} ],
    missing_model_tier: [ $skills[] | select((.model|length)==0 and (.references_shared_policy|not)) | .name ],
    total_skills: ($skills | length),
    skills_with_tier: [ $skills[] | select((.model|length)>0 or .references_shared_policy) ] | length
  }
')

# ---------- Final JSON ----------
report=$(jq -n \
  --arg generated_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --argjson cmd_bytes "$cmd_bytes" \
  --argjson cmd_tokens "$cmd_tokens" \
  --argjson imports "$imports_json" \
  --argjson skills "$skills_json" \
  --argjson mcps "$mcp_json" \
  --argjson flags "$flags" '
  {
    generated_at: $generated_at,
    claude_md: {bytes:$cmd_bytes, tokens:$cmd_tokens},
    always_loaded_imports: $imports,
    skills: $skills,
    mcps: $mcps,
    flags: $flags
  }
')

echo "$report" | tee "$OUT_DIR/finance-controller-audit.json" >/dev/null
echo "$report"
