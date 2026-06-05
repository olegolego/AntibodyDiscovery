#!/usr/bin/env python3
"""Watch the bug database and auto-debug new bugs.

Detects new bugs the simple way the user asked for: by comparing how many bugs
exist now to how many have already been processed (state in bugs/.watch_state.json).
For each new bug it writes a report file and hands it to scripts/auto_fix.sh, which
runs Claude Code headless to fix the bug, then redeploys with health-checked rollback.

Usage:
  python scripts/bug_watch.py --once            # process any new bugs and exit
  python scripts/bug_watch.py --interval 30     # poll every 30s forever
  python scripts/bug_watch.py --interval 30 --dry-run   # just report, don't fix

Add bugs with: python scripts/bug_db.py add "Title" "Description"
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import bug_db  # same directory

REPO_DIR = Path(__file__).resolve().parents[1]
AUTOFIX = REPO_DIR / "scripts" / "auto_fix.sh"
REPORTS_DIR = Path(__import__("os").getenv("PDP_REPORTS_DIR", str(REPO_DIR / "bug_reports")))
STATE_FILE = bug_db.BUGS_DIR / ".watch_state.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"processed": 0}


def _save_state(state: dict) -> None:
    bug_db.BUGS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _write_report(bug: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    summary = f"# Bug #{bug['id']}: {bug.get('title','')}\n\n{bug.get('description','')}\n"
    record = {
        "type": "manual-bug",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bug_id": bug["id"],
        "title": bug.get("title", ""),
        "summary": summary,
    }
    path = REPORTS_DIR / f"{stamp}_bug-{bug['id']}.json"
    path.write_text(json.dumps(record, indent=2))
    return path


def _debug_bug(bug: dict, dry_run: bool) -> None:
    print(f"[bug-watch] NEW bug #{bug['id']}: {bug.get('title','')}", flush=True)
    report = _write_report(bug)
    if dry_run:
        print(f"[bug-watch]   dry-run — wrote report {report.name}, not invoking fixer", flush=True)
        return
    print(f"[bug-watch]   handing to auto_fix.sh ({report.name}) …", flush=True)
    # Foreground + sequential: auto_fix.sh restarts the backend, so we must not
    # run two of them at once. The watcher is independent of the backend process.
    subprocess.run(["bash", str(AUTOFIX), str(report)], cwd=str(REPO_DIR))
    status_file = report.with_suffix("")  # strip .json
    status = report.parent / f"{report.stem}.autofix.json"
    phase = "?"
    if status.exists():
        try:
            phase = json.loads(status.read_text()).get("phase", "?")
        except Exception:
            pass
    print(f"[bug-watch]   bug #{bug['id']} finished — phase={phase}", flush=True)
    bug_db.set_status(bug["id"], f"autofix:{phase}")


def _check_once(dry_run: bool) -> int:
    bugs = bug_db.load()
    state = _load_state()
    processed = int(state.get("processed", 0))
    count = len(bugs)
    if count <= processed:
        return 0
    new_bugs = [b for b in bugs if b["id"] > processed]
    print(f"[bug-watch] {len(new_bugs)} new bug(s) detected ({processed} → {count})", flush=True)
    for bug in new_bugs:
        _debug_bug(bug, dry_run)
        state["processed"] = bug["id"]
        _save_state(state)  # checkpoint after each so a crash never reprocesses
    return len(new_bugs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="check once and exit")
    ap.add_argument("--interval", type=int, default=0, help="poll every N seconds (loop)")
    ap.add_argument("--dry-run", action="store_true", help="write report but don't run the fixer")
    args = ap.parse_args()

    if not args.interval or args.once:
        _check_once(args.dry_run)
        return 0

    print(f"[bug-watch] polling every {args.interval}s — Ctrl+C to stop", flush=True)
    try:
        while True:
            _check_once(args.dry_run)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[bug-watch] stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
