"""MoleculeResultCache — unified DB-backed result cache for all tools.

Drop-in replacement for ToolCache. Every entry is stored in the main DB
`tool_cache` table with an optional `molecule_key` so results are queryable
by (VH, VL) pair across all tools and runs.

Lookup key:  SHA-256 of (tool_id + tool_version + sorted inputs JSON)
Molecule key: MoleculeKey(vh, vl).primary() — extracted automatically from
              inputs that contain heavy_chain / light_chain / sequence.
              Nullable for tools whose inputs are PDB blobs (EquiDock receptor).
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.core.molecule_key import MoleculeKey
from app.db.models import ToolCacheRow
from app.db.session import AsyncSessionLocal


class MoleculeResultCache:
    """Async DB-backed cache. Works as a drop-in for the old sync ToolCache."""

    def __init__(self, tool_id: str, tool_version: str) -> None:
        self.tool_id = tool_id
        self.tool_version = tool_version

    # ── Hashing ───────────────────────────────────────────────────────────────

    def _inputs_hash(self, inputs: dict[str, Any]) -> str:
        h = hashlib.sha256()
        h.update(f"{self.tool_id}:{self.tool_version}:".encode())
        for k in sorted(inputs.keys()):
            h.update(json.dumps({k: inputs[k]}, sort_keys=True, ensure_ascii=True).encode())
        return h.hexdigest()

    @staticmethod
    def _molecule_key(inputs: dict[str, Any]) -> str | None:
        mk = MoleculeKey.from_inputs(inputs)
        return mk.primary() if mk else None

    # ── Cache interface ───────────────────────────────────────────────────────

    async def get(self, inputs: dict[str, Any]) -> dict[str, Any] | None:
        h = self._inputs_hash(inputs)
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(ToolCacheRow).where(
                    ToolCacheRow.tool_id == self.tool_id,
                    ToolCacheRow.inputs_hash == h,
                    ToolCacheRow.tool_version == self.tool_version,
                ).limit(1)
            )).scalar_one_or_none()
        if row is None:
            return None
        return json.loads(row.outputs_json)

    async def put(
        self,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        *,
        run_id: str | None = None,
        node_id: str | None = None,
    ) -> None:
        h = self._inputs_hash(inputs)
        mol_key = self._molecule_key(inputs)
        preview = {
            k: (str(v)[:120] + "…" if isinstance(v, str) and len(v) > 120 else v)
            for k, v in inputs.items()
        }
        async with AsyncSessionLocal() as db:
            # Upsert by inputs_hash — replace stale entries for same inputs
            existing = (await db.execute(
                select(ToolCacheRow).where(
                    ToolCacheRow.tool_id == self.tool_id,
                    ToolCacheRow.inputs_hash == h,
                ).limit(1)
            )).scalar_one_or_none()
            if existing:
                existing.outputs_json = json.dumps(outputs)
                existing.run_id = run_id
                existing.node_id = node_id
                existing.tool_version = self.tool_version
                existing.molecule_key = mol_key or existing.molecule_key
                existing.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
            else:
                db.add(ToolCacheRow(
                    id=str(uuid.uuid4()),
                    tool_id=self.tool_id,
                    tool_version=self.tool_version,
                    inputs_hash=h,
                    molecule_key=mol_key,
                    inputs_preview=json.dumps(preview),
                    outputs_json=json.dumps(outputs),
                    run_id=run_id,
                    node_id=node_id,
                ))
            await db.commit()

    # ── Results queries ───────────────────────────────────────────────────────

    async def list_for_molecule(self, vh: str, vl: str = "") -> list[dict[str, Any]]:
        """All cached results for a (VH, VL) pair from this tool."""
        key = MoleculeKey(vh, vl).primary()
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(ToolCacheRow).where(
                    ToolCacheRow.tool_id == self.tool_id,
                    ToolCacheRow.molecule_key == key,
                ).order_by(ToolCacheRow.created_at.desc())
            )).scalars().all()
        return [_row_summary(r) for r in rows]

    async def stats(self) -> dict[str, Any]:
        from sqlalchemy import func
        async with AsyncSessionLocal() as db:
            total = (await db.execute(
                select(func.count()).where(ToolCacheRow.tool_id == self.tool_id)
            )).scalar() or 0
            molecules = (await db.execute(
                select(func.count(ToolCacheRow.molecule_key.distinct())).where(
                    ToolCacheRow.tool_id == self.tool_id,
                    ToolCacheRow.molecule_key.is_not(None),
                )
            )).scalar() or 0
        return {"tool_id": self.tool_id, "entries": total, "unique_molecules": molecules}


# ── Cross-tool queries (used by /api/results/cache) ──────────────────────────

async def list_cache_for_molecule(vh: str, vl: str = "") -> list[dict[str, Any]]:
    """All cached results across ALL tools for a (VH, VL) pair."""
    key = MoleculeKey(vh, vl).primary()
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ToolCacheRow).where(
                ToolCacheRow.molecule_key == key,
            ).order_by(ToolCacheRow.tool_id, ToolCacheRow.created_at.desc())
        )).scalars().all()
    return [_row_summary(r) for r in rows]


async def list_cache_for_key(molecule_key: str) -> list[dict[str, Any]]:
    """All cached results across all tools for a raw molecule_key hex."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ToolCacheRow).where(
                ToolCacheRow.molecule_key == molecule_key,
            ).order_by(ToolCacheRow.tool_id, ToolCacheRow.created_at.desc())
        )).scalars().all()
    return [_row_summary(r) for r in rows]


async def cache_stats_all() -> list[dict[str, Any]]:
    from sqlalchemy import func
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(
                ToolCacheRow.tool_id,
                func.count().label("entries"),
                func.count(ToolCacheRow.molecule_key.distinct()).label("unique_molecules"),
                func.max(ToolCacheRow.created_at).label("latest"),
            ).group_by(ToolCacheRow.tool_id)
        )).all()
    return [
        {"tool_id": r.tool_id, "entries": r.entries,
         "unique_molecules": r.unique_molecules, "latest": str(r.latest)}
        for r in rows
    ]


def _row_summary(row: ToolCacheRow) -> dict[str, Any]:
    return {
        "id":           row.id,
        "tool_id":      row.tool_id,
        "tool_version": row.tool_version,
        "molecule_key": row.molecule_key,
        "molecule_key_short": row.molecule_key[:12] if row.molecule_key else None,
        "inputs_preview": json.loads(row.inputs_preview) if row.inputs_preview else {},
        "run_id":       row.run_id,
        "node_id":      row.node_id,
        "created_at":   row.created_at.isoformat(),
    }
