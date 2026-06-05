#!/usr/bin/env bash
# Autonomous bug-fix worker.
#
# Spawned (detached) by the backend when a user clicks "Auto-fix & Deploy" on a
# run-bug report. Runs Claude Code headless on the repo to fix the reported bug,
# then redeploys the backend with a health-checked rollback.
#
#   usage: auto_fix.sh <report_json_path>
#
# Safety rails:
#   * Work happens on a fresh `autofix/<stamp>` branch.
#   * The user's current (uncommitted) work is committed as a SNAPSHOT first, so a
#     rollback (`git reset --hard <snapshot>`) restores it exactly — nothing is lost.
#   * After the fix, the backend is restarted and health-checked. If it does not
#     come back, the fix is rolled back to the snapshot and the backend restarted
#     again.
#   * Progress is written to <report>.autofix.json for the UI to poll.
#
# This script must run DETACHED from the backend process (the backend spawns it
# with start_new_session) so that killing the backend during restart does not
# kill this worker.
set -uo pipefail

REPORT="${1:?usage: auto_fix.sh <report_json_path>}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:$PATH"

STAMP="$(date -u +%Y%m%d-%H%M%S)"
BRANCH="autofix/${STAMP}"
STATUS_FILE="${REPORT%.json}.autofix.json"
LOG_FILE="${REPORT%.json}.autofix.log"
MODEL="${PDP_AUTOFIX_MODEL:-claude-opus-4-8}"
MAX_TURNS="${PDP_AUTOFIX_MAX_TURNS:-80}"

# shellcheck source=/dev/null
[ -f "$REPO_DIR/config.env" ] && source "$REPO_DIR/config.env"
BACKEND_PORT="${BACKEND_PORT:-8000}"
HEALTH_URL="http://localhost:${BACKEND_PORT}/api/tools/"

# ── status helper (writes JSON the UI polls) ──────────────────────────────────
json_escape() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1" 2>/dev/null || printf '"%s"' "$1"; }

write_status() {  # write_status <phase> <message>
  local phase="$1" msg="${2:-}"
  {
    printf '{\n'
    printf '  "phase": %s,\n'        "$(json_escape "$phase")"
    printf '  "message": %s,\n'      "$(json_escape "$msg")"
    printf '  "branch": %s,\n'       "$(json_escape "$BRANCH")"
    printf '  "base_commit": %s,\n'  "$(json_escape "${BASE_COMMIT:-}")"
    printf '  "snapshot_commit": %s,\n' "$(json_escape "${SNAP_COMMIT:-}")"
    printf '  "fix_commit": %s,\n'   "$(json_escape "${FIX_COMMIT:-}")"
    printf '  "log_file": %s,\n'     "$(json_escape "$LOG_FILE")"
    printf '  "updated_at": %s\n'    "$(json_escape "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
    printf '}\n'
  } > "$STATUS_FILE"
}

log() { echo "[$(date -u +%H:%M:%S)] $*" >> "$LOG_FILE"; }

cd "$REPO_DIR" || { write_status "error" "repo dir not found"; exit 1; }
: > "$LOG_FILE"
log "auto_fix start — report=$REPORT model=$MODEL"
write_status "starting" "Preparing isolated fix branch"

# ── 1. snapshot current work onto a new branch ────────────────────────────────
BASE_COMMIT="$(git rev-parse HEAD 2>/dev/null)"
if ! git checkout -b "$BRANCH" >> "$LOG_FILE" 2>&1; then
  write_status "error" "could not create branch $BRANCH"
  exit 1
fi
git add -A >> "$LOG_FILE" 2>&1
git commit -m "autofix: WIP snapshot before fixing ${REPORT##*/}" --no-verify >> "$LOG_FILE" 2>&1 || log "nothing to snapshot"
SNAP_COMMIT="$(git rev-parse HEAD)"
log "snapshot commit = $SNAP_COMMIT (base was $BASE_COMMIT)"

# ── 2. run Claude Code headless to fix the bug ────────────────────────────────
write_status "fixing" "Claude is diagnosing and fixing the bug"
PROMPT="You are fixing a bug in this repository (an antibody-design pipeline platform). \
Read the JSON file at ${REPORT}. Its \`summary\` field describes the bug to fix — it is either a \
structured report of a FAILED pipeline run (failed node, tool, error, recent logs, input shapes) \
or a manually-filed bug description. \
Diagnose the ROOT CAUSE and fix it in the codebase with the minimal, correct change. \
Follow the conventions in CLAUDE.md and docs/adding-tools.md. \
Do NOT restart any servers, do NOT run the app, do NOT commit — just edit the source files. \
When finished, state in one or two sentences what the root cause was and what you changed."

# IMPORTANT: strip ANTHROPIC_API_KEY so the CLI uses its own OAuth session. The
# key inherited from backend/.env (or config.env) is invalid for CLI use and
# makes `claude` fail with "Invalid API key", producing an empty (no-op) fix.
# Same workaround as backend/app/api/compute.py::generate_code.
if env -u ANTHROPIC_API_KEY claude -p "$PROMPT" \
      --add-dir "$REPO_DIR" \
      --model "$MODEL" \
      --max-turns "$MAX_TURNS" \
      --dangerously-skip-permissions \
      >> "$LOG_FILE" 2>&1; then
  log "claude finished"
else
  log "claude exited non-zero (continuing to evaluate diff)"
fi

# ── 3. commit the fix ─────────────────────────────────────────────────────────
# Detect "no real fix" by staging and diffing against the snapshot commit, NOT by
# `git status --porcelain`: a dirty git *submodule* (e.g. tools/progen2) shows up
# as porcelain output but is NOT a code change Claude made, and would otherwise
# trick us into "deploying" an empty fix.
write_status "committing" "Recording the fix"
git add -A >> "$LOG_FILE" 2>&1
if git diff --cached --quiet HEAD; then
  write_status "no_change" "Claude made no code changes — nothing to deploy"
  log "no staged changes vs snapshot; leaving on branch $BRANCH"
  exit 0
fi
git commit -m "autofix: fix for ${REPORT##*/}" --no-verify >> "$LOG_FILE" 2>&1 || true
FIX_COMMIT="$(git rev-parse HEAD)"
log "fix commit = $FIX_COMMIT"

# ── 4. optional: run backend tests (informational only) ───────────────────────
write_status "testing" "Running backend tests"
if [ -d "$REPO_DIR/backend/tests" ] && [ -x "$REPO_DIR/backend/.venv/bin/python" ]; then
  ( cd "$REPO_DIR/backend" && .venv/bin/python -m pytest tests -q ) >> "$LOG_FILE" 2>&1 \
    && log "tests passed" || log "tests reported failures (informational, not blocking)"
fi

# ── 5. restart backend + health check ─────────────────────────────────────────
restart_backend() {
  lsof -ti:"${BACKEND_PORT}" | xargs kill -9 2>/dev/null || true
  sleep 1
  ( cd "$REPO_DIR/backend" && source .venv/bin/activate \
      && nohup uvicorn app.main:app --host 127.0.0.1 --port "${BACKEND_PORT}" > /tmp/backend.log 2>&1 & )
}

health_ok() {
  for _ in $(seq 1 30); do
    sleep 1
    curl -sfL "$HEALTH_URL" > /dev/null 2>&1 && return 0
  done
  return 1
}

write_status "restarting" "Restarting backend with the fix"
restart_backend
log "backend restarted; waiting for health"

if health_ok; then
  write_status "deployed" "Fix deployed and backend healthy (branch $BRANCH)"
  log "DEPLOYED ok on $BRANCH"
  exit 0
fi

# ── 6. rollback ───────────────────────────────────────────────────────────────
log "backend UNHEALTHY after fix — rolling back to snapshot $SNAP_COMMIT"
write_status "rolling_back" "Backend failed health check — reverting the fix"
git reset --hard "$SNAP_COMMIT" >> "$LOG_FILE" 2>&1
restart_backend
if health_ok; then
  write_status "rolled_back" "Fix reverted; backend healthy again (your work is preserved on $BRANCH)"
  log "ROLLED BACK ok"
else
  write_status "error" "Backend unhealthy even after rollback — manual intervention needed; see $LOG_FILE"
  log "ROLLBACK FAILED — manual fix required"
fi
exit 0
