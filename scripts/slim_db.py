#!/usr/bin/env python3
"""Slim the protein_design.db: strip PDB strings and embedding arrays from node_analyses
and runs.data, then VACUUM to reclaim disk space.

Run once: python3 scripts/slim_db.py
Safe to re-run (idempotent — already-slimmed rows are skipped).
"""
import json
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).parent.parent / "backend" / "protein_design.db"


_LARGE_KEYS = {"model_artifact", "committees", "architecture_spec"}


def slim_value(k: str, v):
    if k in _LARGE_KEYS:
        return f"__artifact_{k}__"
    if isinstance(v, str) and len(v) > 512:
        return "__artifact__"
    if isinstance(v, list) and len(v) > 64 and v and isinstance(v[0], (int, float)):
        return f"__embedding_{len(v)}d__"
    if isinstance(v, dict) and len(str(v)) > 500_000:
        return f"__large_dict__"
    return v


def slim_dict(d: dict) -> dict:
    return {k: slim_value(k, v) for k, v in d.items()}


def slim_node_analyses(conn: sqlite3.Connection) -> tuple[int, int]:
    rows = conn.execute("SELECT rowid, data FROM node_analyses").fetchall()
    updated = skipped = 0
    for rowid, raw in rows:
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        slimmed = slim_dict(data)
        new_raw = json.dumps(slimmed)
        if len(new_raw) < len(raw):
            conn.execute("UPDATE node_analyses SET data=? WHERE rowid=?", (new_raw, rowid))
            updated += 1
        else:
            skipped += 1
    conn.commit()
    return updated, skipped


def slim_runs(conn: sqlite3.Connection) -> tuple[int, int]:
    rows = conn.execute("SELECT id, data FROM runs").fetchall()
    updated = skipped = 0
    for run_id, raw in rows:
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        changed = False
        for nr in data.get("nodes", {}).values():
            if nr.get("outputs"):
                slimmed = slim_dict(nr["outputs"])
                if slimmed != nr["outputs"]:
                    nr["outputs"] = slimmed
                    changed = True
        if changed:
            conn.execute("UPDATE runs SET data=? WHERE id=?", (json.dumps(data), run_id))
            updated += 1
        else:
            skipped += 1
    conn.commit()
    return updated, skipped


def main():
    if not DB.exists():
        print(f"DB not found: {DB}")
        sys.exit(1)

    size_before = DB.stat().st_size
    print(f"DB size before: {size_before / 1e9:.2f} GB")

    conn = sqlite3.connect(str(DB))
    conn.execute("PRAGMA journal_mode=WAL")

    print("Slimming node_analyses…")
    upd, skip = slim_node_analyses(conn)
    print(f"  updated {upd} rows, skipped {skip}")

    print("Slimming runs…")
    upd, skip = slim_runs(conn)
    print(f"  updated {upd} rows, skipped {skip}")

    print("Running VACUUM (this rewrites the file — may take a minute)…")
    conn.execute("VACUUM")
    conn.close()

    size_after = DB.stat().st_size
    saved = (size_before - size_after) / 1e9
    print(f"DB size after:  {size_after / 1e9:.2f} GB  (saved {saved:.2f} GB)")


if __name__ == "__main__":
    main()
