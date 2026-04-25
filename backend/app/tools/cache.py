"""Per-tool SQLite result cache.

Each tool has its own cache.db at tools/<tool_id>/cache.db.
Cache key = SHA-256 of the canonical inputs JSON + tool version.
Outputs are stored as JSON (PDB text inlined — SQLite handles blobs up to several MB).
"""
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

# Root of the repository
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TOOLS_DIR = _REPO_ROOT / "tools"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS cache (
    input_hash    TEXT PRIMARY KEY,
    tool_version  TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    inputs_preview TEXT NOT NULL,
    outputs_json  TEXT NOT NULL
);
"""


class ToolCache:
    """Simple get/put cache backed by a per-tool SQLite file."""

    def __init__(self, tool_id: str, tool_version: str) -> None:
        self.tool_id = tool_id
        self.tool_version = tool_version
        db_path = TOOLS_DIR / tool_id / "cache.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(db_path)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(_CREATE_TABLE)
            conn.commit()

    def _hash(self, inputs: dict[str, Any]) -> str:
        # Hash full input content — never truncate, two PDBs with the same first 4 KB but
        # different tails must not collide.  We stream through a hasher to avoid duplicating
        # large strings in memory.
        h = hashlib.sha256()
        # Sort keys for determinism; encode as JSON fragments so the hasher sees the same
        # bytes regardless of Python dict ordering.
        for k in sorted(inputs.keys()):
            v = inputs[k]
            h.update(json.dumps({k: v}, sort_keys=True, ensure_ascii=True).encode())
        return h.hexdigest()

    def get(self, inputs: dict[str, Any]) -> dict[str, Any] | None:
        h = self._hash(inputs)
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT outputs_json, tool_version FROM cache WHERE input_hash = ?",
                (h,),
            ).fetchone()
        if row is None:
            return None
        outputs_json, cached_version = row
        # Invalidate if tool version changed
        if cached_version != self.tool_version:
            return None
        return json.loads(outputs_json)

    def put(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        h = self._hash(inputs)
        preview = {k: (str(v)[:120] + "…" if isinstance(v, str) and len(v) > 120 else v)
                   for k, v in inputs.items()}
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO cache
                   (input_hash, tool_version, inputs_preview, outputs_json)
                   VALUES (?, ?, ?, ?)""",
                (h, self.tool_version, json.dumps(preview), json.dumps(outputs)),
            )
            conn.commit()

    def stats(self) -> dict[str, Any]:
        with sqlite3.connect(self._db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            latest = conn.execute(
                "SELECT created_at FROM cache ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return {"tool_id": self.tool_id, "entries": count,
                "latest": latest[0] if latest else None}
