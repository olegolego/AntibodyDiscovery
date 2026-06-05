#!/usr/bin/env python3
"""Tiny enumerated bug database.

Bugs live in an append-only JSONL file (`bugs/bugs.jsonl` at the repo root); the
1-based line number is the bug id. The watcher (scripts/bug_watch.py) detects new
bugs simply by how many lines exist vs. how many it has already processed.

Usage:
  python scripts/bug_db.py add "Title" "Longer description / repro / error text"
  python scripts/bug_db.py add "Title"            # description read from stdin
  python scripts/bug_db.py list
  python scripts/bug_db.py count
  python scripts/bug_db.py show <id>
  python scripts/bug_db.py resolve <id>
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
BUGS_DIR = Path(os.getenv("PDP_BUGS_DIR", str(REPO_DIR / "bugs")))
BUGS_FILE = BUGS_DIR / "bugs.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load() -> list[dict]:
    if not BUGS_FILE.exists():
        return []
    out: list[dict] = []
    for i, line in enumerate(BUGS_FILE.read_text().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        rec.setdefault("id", i)
        out.append(rec)
    return out


def add(title: str, description: str) -> dict:
    BUGS_DIR.mkdir(parents=True, exist_ok=True)
    bug_id = len(load()) + 1
    rec = {
        "id": bug_id,
        "title": title.strip(),
        "description": description.strip(),
        "status": "open",
        "created_at": _now(),
    }
    with open(BUGS_FILE, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def set_status(bug_id: int, status: str) -> bool:
    bugs = load()
    found = False
    for b in bugs:
        if b["id"] == bug_id:
            b["status"] = status
            b["updated_at"] = _now()
            found = True
    if found:
        with open(BUGS_FILE, "w") as f:
            for b in bugs:
                f.write(json.dumps(b) + "\n")
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]

    if cmd == "add":
        if not rest:
            print("usage: bug_db.py add <title> [description]", file=sys.stderr)
            return 1
        title = rest[0]
        description = rest[1] if len(rest) > 1 else (sys.stdin.read() if not sys.stdin.isatty() else "")
        rec = add(title, description)
        print(f"Added bug #{rec['id']}: {rec['title']}")
        return 0

    if cmd == "count":
        print(len(load()))
        return 0

    if cmd == "list":
        for b in load():
            print(f"#{b['id']:>3}  [{b.get('status','open'):<8}]  {b.get('title','')}")
        return 0

    if cmd == "show":
        if not rest:
            print("usage: bug_db.py show <id>", file=sys.stderr)
            return 1
        target = int(rest[0])
        for b in load():
            if b["id"] == target:
                print(json.dumps(b, indent=2))
                return 0
        print(f"bug #{target} not found", file=sys.stderr)
        return 1

    if cmd in ("resolve", "close"):
        if not rest:
            print(f"usage: bug_db.py {cmd} <id>", file=sys.stderr)
            return 1
        ok = set_status(int(rest[0]), "resolved")
        print("ok" if ok else "not found")
        return 0 if ok else 1

    print(f"unknown command: {cmd}\n{__doc__}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
