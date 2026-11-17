#!/usr/bin/env bash
# run_analysis.sh — full security analysis pipeline (no Claude needed)
#
# Usage:
#   ./run_analysis.sh                        # uses default_scope from config.json
#   ./run_analysis.sh --scope workspace      # write to <workspace>/artifacts/security-snapshot/
#   ./run_analysis.sh --scope <project>      # write to <workspace>/projects/<project>/artifacts/security-snapshot/
#
# Output lives under $REPORTS_DIR resolved from --scope.
# Equivalent to running /security-snapshot in Claude Code.
# Run monthly or on demand. Same-day re-runs overwrite; new day = new snapshot.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

# ── Locate workspace relative to this script (never from PWD — cwd drifts) ─────
# This script lives at <workspace>/.claude/skills/security-snapshot/scripts/.
WS="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
[ -f "$WS/.claude/.workspace" ] || fail "Workspace marker not found at $WS/.claude/.workspace — is this skill deployed inside a v2 workspace?"

# ── Config read: delegate to the SAME loader the Python scripts use
#    (config_util.load_config — config.json template overlaid by config.local.json).
#    Reusing it means the shell orchestrator and the scripts resolve identical
#    values with identical overlay/empty/malformed/strip handling — no divergence,
#    and a clear error (naming the offending file) on bad JSON.
cfg_get() {
  python3 -c "import sys; sys.path.insert(0, sys.argv[1]); from config_util import load_config; v = load_config().get(sys.argv[2], ''); print(v.strip() if isinstance(v, str) else ('' if v is None else v))" "$SCRIPT_DIR" "$1"
}

# ── Resolve scope from config + optional --scope flag ──────────────────────────
SCOPE="$(cfg_get default_scope)" \
  || fail "Could not resolve default_scope from config (see the error above). Run /security-snapshot first-run setup."
[ -n "$SCOPE" ] || fail "default_scope is empty — run /security-snapshot first-run setup (writes config.local.json)."
while [ $# -gt 0 ]; do
  case "$1" in
    --scope)    SCOPE="$2"; shift 2 ;;
    --scope=*)  SCOPE="${1#--scope=}"; shift ;;
    -h|--help)  sed -n '2,12p' "$0"; exit 0 ;;
    *)          fail "Unknown arg: $1" ;;
  esac
done

if [ "$SCOPE" = "workspace" ]; then
  REPORTS_DIR="$WS/artifacts/security-snapshot"
else
  if [ ! -d "$WS/projects/$SCOPE" ]; then
    cat >&2 <<EOF
✗ Project '$SCOPE' not found at $WS/projects/$SCOPE.

This usually means the skill's default_scope points at a project that doesn't
exist in this workspace. Two fixes, pick one:

  1. Edit $SCRIPT_DIR/config.local.json — set owner_project and default_scope to
     a project slug that exists in this workspace (see ls $WS/projects/).
  2. Pass --scope <name> at the CLI to override for a single run, or
     --scope workspace to write outputs at workspace level instead.
EOF
    exit 1
  fi
  REPORTS_DIR="$WS/projects/$SCOPE/artifacts/security-snapshot"
fi

mkdir -p "$REPORTS_DIR"
export SECURITY_SNAPSHOT_REPORTS_DIR="$REPORTS_DIR"

echo "Security Snapshot — $(date '+%Y-%m-%d')"
echo "========================================="
echo "Scope:       $SCOPE"
echo "Reports dir: $REPORTS_DIR"

# ── Prerequisites ──────────────────────────────────────────────────────────────
echo ""
echo "Checking prerequisites..."

python3 -c "import boto3" 2>/dev/null \
  || fail "boto3 not installed. Run: pip3 install boto3 --break-system-packages"
ok "boto3"

gh auth status --hostname github.com &>/dev/null \
  || fail "gh not authenticated. Run: gh auth login"
ok "gh CLI authenticated"

AWS_PROFILE_CFG="$(cfg_get aws_profile)" \
  || fail "Could not resolve aws_profile from config (see the error above)."
[ -n "$AWS_PROFILE_CFG" ] \
  || fail "aws_profile not set — run /security-snapshot once for first-run setup (writes config.local.json), or edit $SCRIPT_DIR/config.local.json."
aws sts get-caller-identity --profile "$AWS_PROFILE_CFG" &>/dev/null \
  || fail "AWS profile $AWS_PROFILE_CFG failed. Check credentials."
ok "AWS profile $AWS_PROFILE_CFG"

# ── Pipeline ───────────────────────────────────────────────────────────────────
echo ""
echo "→ Inspector V2 snapshot (several minutes, more on a cold run: first-seen, rebuild comparison, package managers, lever breakdown, host release)..."
python3 "$SCRIPT_DIR/posture_snapshot.py" --save --raw || fail "posture_snapshot.py failed"
ok "Inspector snapshot saved"

echo ""
echo "→ GitHub security snapshot (~2 min)..."
python3 "$SCRIPT_DIR/github_security_snapshot.py" --save --raw || fail "github_security_snapshot.py failed"
ok "GitHub snapshot saved"

echo ""
echo "→ Correlation analysis..."
python3 "$SCRIPT_DIR/correlation.py" --save --raw || fail "correlation.py failed"
ok "Correlation saved"

echo ""
echo "→ Building dashboard..."
python3 "$SCRIPT_DIR/build_dashboard.py" || fail "build_dashboard.py failed"
ok "Dashboard built"

echo ""
echo "→ Movement since the previous snapshot (reads the snapshot.json just built)..."
# Warn, don't fail: a missing movement file must not cost the snapshot itself.
if python3 "$SCRIPT_DIR/emit_movement.py" --reports-dir "$REPORTS_DIR"; then
  ok "Movement written"
else
  echo "  WARN: emit_movement.py failed — snapshot is complete, movement.md is not" >&2
fi
echo "   Why it moved: not written by this script — /security-snapshot Step 6 writes it."

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo "========================================="
ok "All steps complete."
echo "   Dashboard: $REPORTS_DIR/security-dashboard.html"
echo "   To deploy: /google-script-deploy deploy \"$REPORTS_DIR\""
