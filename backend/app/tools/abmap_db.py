"""AbMAP embedding cache/database.

Lookup key: MoleculeKey(vh, vl).primary() + embedding params.
Stores the full embedding vector and metadata so the AbMAP server is never
called twice for the same (sequence, params) combination.

All public methods are async — safe to call from FastAPI / executor context.
"""
import json
from typing import Any

from sqlalchemy import select

from app.core.molecule_key import MoleculeKey
from app.db.models import AbMAPEmbeddingRow
from app.db.session import AsyncSessionLocal


class AbMAPCache:
    """Async DB-backed cache for AbMAP embeddings, keyed by (VH, VL) + params."""

    # ── Lookup ────────────────────────────────────────────────────────────────

    async def get(
        self,
        vh: str,
        vl: str = "",
        *,
        chain_type: str = "H",
        task: str = "structure",
        embedding_type: str = "fixed",
        num_mutations: int = 10,
    ) -> dict[str, Any] | None:
        """Return cached {embedding, metadata} or None if not found."""
        key = MoleculeKey(vh, vl)
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(AbMAPEmbeddingRow)
                .where(
                    AbMAPEmbeddingRow.molecule_key == key.primary(),
                    AbMAPEmbeddingRow.chain_type == chain_type.upper(),
                    AbMAPEmbeddingRow.task == task,
                    AbMAPEmbeddingRow.embedding_type == embedding_type,
                    AbMAPEmbeddingRow.num_mutations == num_mutations,
                )
                .order_by(AbMAPEmbeddingRow.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()

        if row is None:
            return None
        return {
            "embedding": json.loads(row.embedding_json),
            "metadata": {
                "chain_type":      row.chain_type,
                "task":            row.task,
                "embedding_type":  row.embedding_type,
                "num_mutations":   row.num_mutations,
                "sequence_length": row.sequence_length,
                "embedding_shape": json.loads(row.embedding_shape) if row.embedding_shape else None,
            },
        }

    # ── Store ─────────────────────────────────────────────────────────────────

    async def put(
        self,
        vh: str,
        vl: str = "",
        *,
        chain_type: str = "H",
        task: str = "structure",
        embedding_type: str = "fixed",
        num_mutations: int = 10,
        result: dict[str, Any],
        run_id: str | None = None,
        node_id: str | None = None,
    ) -> str:
        """Save result to DB. Returns the molecule_key (primary hash)."""
        key = MoleculeKey(vh, vl)
        meta = result.get("metadata") or {}
        shape = meta.get("embedding_shape")

        async with AsyncSessionLocal() as db:
            row = AbMAPEmbeddingRow(
                molecule_key=key.primary(),
                heavy_chain=key.vh or None,
                light_chain=key.vl or None,
                chain_type=chain_type.upper(),
                task=task,
                embedding_type=embedding_type,
                num_mutations=num_mutations,
                embedding_json=json.dumps(result["embedding"]),
                embedding_shape=json.dumps(shape) if shape else None,
                sequence_length=meta.get("sequence_length"),
                run_id=run_id,
                node_id=node_id,
            )
            db.add(row)
            await db.commit()

        return key.primary()

    # ── Query by (VH, VL) ─────────────────────────────────────────────────────

    async def list_for_molecule(
        self, vh: str, vl: str = ""
    ) -> list[dict[str, Any]]:
        """Return all embeddings for a given (VH, VL) pair, newest first."""
        key = MoleculeKey(vh, vl)
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(AbMAPEmbeddingRow)
                .where(AbMAPEmbeddingRow.molecule_key == key.primary())
                .order_by(AbMAPEmbeddingRow.created_at.desc())
            )).scalars().all()

        return [_row_to_summary(r) for r in rows]

    async def list_for_key(self, molecule_key: str) -> list[dict[str, Any]]:
        """Return all embeddings for a raw molecule_key hex string."""
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(AbMAPEmbeddingRow)
                .where(AbMAPEmbeddingRow.molecule_key == molecule_key)
                .order_by(AbMAPEmbeddingRow.created_at.desc())
            )).scalars().all()
        return [_row_to_summary(r) for r in rows]

    async def get_embedding_by_id(self, row_id: str) -> dict[str, Any] | None:
        """Fetch full embedding vector by row UUID."""
        async with AsyncSessionLocal() as db:
            row = await db.get(AbMAPEmbeddingRow, row_id)
        if row is None:
            return None
        return {
            "id": row.id,
            "molecule_key": row.molecule_key,
            "embedding": json.loads(row.embedding_json),
            "metadata": {
                "chain_type":      row.chain_type,
                "task":            row.task,
                "embedding_type":  row.embedding_type,
                "num_mutations":   row.num_mutations,
                "sequence_length": row.sequence_length,
                "embedding_shape": json.loads(row.embedding_shape) if row.embedding_shape else None,
            },
            "run_id": row.run_id,
            "created_at": row.created_at.isoformat(),
        }

    async def stats(self) -> dict[str, Any]:
        from sqlalchemy import func
        async with AsyncSessionLocal() as db:
            total = (await db.execute(
                select(func.count()).select_from(AbMAPEmbeddingRow)
            )).scalar() or 0
            molecules = (await db.execute(
                select(func.count(AbMAPEmbeddingRow.molecule_key.distinct()))
            )).scalar() or 0
        return {"total_embeddings": total, "unique_molecules": molecules}


# ── Module-level singleton ────────────────────────────────────────────────────

abmap_cache = AbMAPCache()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_summary(row: AbMAPEmbeddingRow) -> dict[str, Any]:
    return {
        "id":              row.id,
        "molecule_key":    row.molecule_key,
        "chain_type":      row.chain_type,
        "task":            row.task,
        "embedding_type":  row.embedding_type,
        "num_mutations":   row.num_mutations,
        "sequence_length": row.sequence_length,
        "embedding_shape": json.loads(row.embedding_shape) if row.embedding_shape else None,
        "run_id":          row.run_id,
        "created_at":      row.created_at.isoformat(),
    }
