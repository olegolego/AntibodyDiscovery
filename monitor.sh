#!/usr/bin/env bash
# Background loop monitor — writes state snapshots to monitor.log every 5 min.
# Sends macOS notifications on key events (flexref done, iter complete, HADDOCK starts).
LOG=/Users/oswaldkid/Biotools/AntibodyDiscovery/monitor.log
T=/var/folders/sc/p9r70hcn2t784t76qgsbn7fc0000gn/T

notify() {
  osascript -e "display notification \"$1\" with title \"BioTools Loop\"" 2>/dev/null
}

last_flexref_done=""
last_run_status=""
last_iter=""

while true; do
  ts=$(date "+%H:%M:%S")

  # --- HADDOCK flexref progress ---
  flex_total=0
  flex_dirs=0
  for dir in $(find "$T" -name "4_flexref" -type d 2>/dev/null | grep -v data); do
    cnt=$(ls "${dir}"/*.pdb 2>/dev/null | wc -l | tr -d ' ')
    flex_total=$((flex_total + cnt))
    flex_dirs=$((flex_dirs + 1))
  done

  # --- Backend run status ---
  run_json=$(curl -sf http://localhost:8000/api/loop-runs/b7fc778c-1567-48b2-81fd-01484866210a/ 2>/dev/null)
  loop_iter=$(echo "$run_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('current_iteration','?'))" 2>/dev/null)
  loop_status=$(echo "$run_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null)
  run_ids_count=$(echo "$run_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('run_ids',[])))" 2>/dev/null)

  # Latest run status
  latest_run_id=$(echo "$run_json" | python3 -c "import json,sys; d=json.load(sys.stdin); ids=d.get('run_ids',[]); print(ids[-1] if ids else '')" 2>/dev/null)
  run_status=""
  if [ -n "$latest_run_id" ]; then
    run_status=$(curl -sf "http://localhost:8000/api/runs/${latest_run_id}/" 2>/dev/null | \
      python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null)
  fi

  echo "[$ts] loop=iter${loop_iter}(${loop_status}) run=${run_status} flexref_dirs=${flex_dirs} flexref_pdbs=${flex_total}" >> "$LOG"

  # Notifications on key transitions
  if [ "$run_status" = "succeeded" ] && [ "$run_status" != "$last_run_status" ]; then
    notify "Iter ${loop_iter} SUCCEEDED — loop advancing"
    echo "[$ts] *** ITER ${loop_iter} SUCCEEDED ***" >> "$LOG"
  fi

  if [ "$loop_iter" != "$last_iter" ] && [ -n "$last_iter" ]; then
    notify "Loop advanced to iter ${loop_iter}"
    echo "[$ts] *** LOOP ADVANCED TO ITER ${loop_iter} ***" >> "$LOG"
  fi

  if [ "$flex_dirs" -eq 0 ] && [ "$last_flexref_done" != "yes" ] && [ "$loop_iter" -gt 0 ] 2>/dev/null; then
    last_flexref_done="yes"
  fi
  if [ "$flex_dirs" -gt 0 ]; then
    last_flexref_done=""
  fi

  last_run_status="$run_status"
  last_iter="$loop_iter"

  sleep 300  # check every 5 minutes
done
