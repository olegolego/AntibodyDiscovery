#!/usr/bin/env bash
# code_watchdog.sh — runs every 20 min, checks code health + HADDOCK, notifies via macOS
LOG=/Users/oswaldkid/Biotools/AntibodyDiscovery/watchdog.log
FRONTEND=/Users/oswaldkid/Biotools/AntibodyDiscovery/frontend
BACKEND=/Users/oswaldkid/Biotools/AntibodyDiscovery/backend/app
T=/var/folders/sc/p9r70hcn2t784t76qgsbn7fc0000gn/T

notify() {
  osascript -e "display notification \"$1\" with title \"BioTools Watchdog\" sound name \"Ping\"" 2>/dev/null
  echo "[$(date '+%H:%M:%S')] NOTIFY: $1" >> "$LOG"
}

check_once() {
  ts=$(date '+%H:%M:%S')
  issues=()

  # ── 1. TypeScript ──────────────────────────────────────────────────────────
  ts_errors=$(cd "$FRONTEND" && npx tsc --noEmit 2>&1 | grep -c "error TS" || echo 0)
  if [ "$ts_errors" -gt 0 ] 2>/dev/null; then
    issues+=("TS: $ts_errors errors")
  fi

  # ── 2. Python syntax ───────────────────────────────────────────────────────
  py_errors=0
  for f in $(find "$BACKEND" -name "*.py" -not -path "*__pycache__*" -not -path "*/.venv/*"); do
    python3 -m py_compile "$f" 2>/dev/null || py_errors=$((py_errors+1))
  done
  if [ "$py_errors" -gt 0 ]; then
    issues+=("Python: $py_errors syntax errors")
  fi

  # ── 3. Backend alive ───────────────────────────────────────────────────────
  if ! curl -sf http://localhost:8000/api/tools/ > /dev/null 2>&1; then
    issues+=("Backend: DOWN")
  fi

  # ── 4. HADDOCK / loop progress ────────────────────────────────────────────
  flex_pdbs=0
  flex_dirs=0
  for dir in $(find "$T" -name "4_flexref" -type d 2>/dev/null | grep -v '/data/'); do
    cnt=$(ls "${dir}"/*.pdb 2>/dev/null | wc -l | tr -d ' ')
    flex_pdbs=$((flex_pdbs + cnt))
    flex_dirs=$((flex_dirs + 1))
  done

  loop_json=$(curl -sf http://localhost:8000/api/loop-runs/b7fc778c-1567-48b2-81fd-01484866210a/ 2>/dev/null)
  loop_iter=$(echo "$loop_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('current_iteration','?'))" 2>/dev/null)
  loop_status=$(echo "$loop_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null)
  run_ids=$(echo "$loop_json" | python3 -c "import json,sys; d=json.load(sys.stdin); ids=d.get('run_ids',[]); print(ids[-1] if ids else '')" 2>/dev/null)
  run_status=$(curl -sf "http://localhost:8000/api/runs/${run_ids}/" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null)

  # ── 5. Log summary ────────────────────────────────────────────────────────
  summary="loop=iter${loop_iter}(${loop_status}) run=${run_status} flex_dirs=${flex_dirs} flex_pdbs=${flex_pdbs} ts_err=${ts_errors} py_err=${py_errors}"
  echo "[$ts] $summary" >> "$LOG"

  # ── 6. Notify on issues or key events ─────────────────────────────────────
  if [ "${#issues[@]}" -gt 0 ]; then
    notify "CODE ISSUES: ${issues[*]}"
  fi

  if [ "$run_status" = "succeeded" ]; then
    notify "Iter ${loop_iter} SUCCEEDED — loop advancing. Restart backend!"
  fi

  if [ "${#issues[@]}" -eq 0 ]; then
    notify "✓ Code OK | iter=${loop_iter} run=${run_status} flex=${flex_pdbs}pdbs"
  fi
}

echo "[$(date '+%H:%M:%S')] Watchdog started (20-min interval)" >> "$LOG"
notify "Watchdog started — checks every 20 min"

while true; do
  check_once
  sleep 1200   # 20 minutes
done
