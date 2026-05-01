import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MoleculeRow, SequenceCollectionRow, SequenceEntryRow
from app.db.session import get_db

router = APIRouter()


# ── Collections ───────────────────────────────────────────────────────────────

@router.get("/collections/")
async def list_collections(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(
        select(SequenceCollectionRow).order_by(SequenceCollectionRow.created_at.desc())
    )).scalars().all()
    result = []
    for col in rows:
        count = (await db.execute(
            select(func.count()).where(SequenceEntryRow.collection_id == col.id)
        )).scalar() or 0
        result.append({
            "id": col.id, "name": col.name, "description": col.description,
            "entry_count": count, "created_at": col.created_at.isoformat(),
        })
    return result


@router.post("/collections/", status_code=201)
async def create_collection(body: dict[str, Any], db: AsyncSession = Depends(get_db)) -> dict:
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    row = SequenceCollectionRow(
        id=str(uuid.uuid4()),
        name=name,
        description=body.get("description") or None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "name": row.name, "description": row.description,
            "entry_count": 0, "created_at": row.created_at.isoformat()}


@router.get("/collections/{coll_id}/")
async def get_collection(coll_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    col = await db.get(SequenceCollectionRow, coll_id)
    if col is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    entries = (await db.execute(
        select(SequenceEntryRow)
        .where(SequenceEntryRow.collection_id == coll_id)
        .order_by(SequenceEntryRow.created_at.desc())
    )).scalars().all()
    return {
        "id": col.id, "name": col.name, "description": col.description,
        "entry_count": len(entries), "created_at": col.created_at.isoformat(),
        "entries": [_entry_dict(e) for e in entries],
    }


@router.put("/collections/{coll_id}/")
async def update_collection(coll_id: str, body: dict[str, Any], db: AsyncSession = Depends(get_db)) -> dict:
    col = await db.get(SequenceCollectionRow, coll_id)
    if col is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    if "name" in body and str(body["name"]).strip():
        col.name = str(body["name"]).strip()
    if "description" in body:
        col.description = body["description"] or None
    await db.commit()
    await db.refresh(col)
    return {"id": col.id, "name": col.name, "description": col.description,
            "created_at": col.created_at.isoformat()}


@router.delete("/collections/{coll_id}/", status_code=204)
async def delete_collection(coll_id: str, db: AsyncSession = Depends(get_db)) -> None:
    col = await db.get(SequenceCollectionRow, coll_id)
    if col is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    entries = (await db.execute(
        select(SequenceEntryRow).where(SequenceEntryRow.collection_id == coll_id)
    )).scalars().all()
    for e in entries:
        await db.delete(e)
    await db.delete(col)
    await db.commit()


# ── Entries ───────────────────────────────────────────────────────────────────

def _entry_dict(e: SequenceEntryRow) -> dict:
    return {
        "id": e.id, "collection_id": e.collection_id,
        "name": e.name, "heavy_chain": e.heavy_chain, "light_chain": e.light_chain,
        "source_molecule_id": e.source_molecule_id, "notes": e.notes,
        "created_at": e.created_at.isoformat(),
    }


@router.get("/collections/{coll_id}/entries/")
async def list_entries(coll_id: str, q: str = "", db: AsyncSession = Depends(get_db)) -> list[dict]:
    stmt = select(SequenceEntryRow).where(SequenceEntryRow.collection_id == coll_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(
            SequenceEntryRow.name.like(like),
            SequenceEntryRow.heavy_chain.like(like),
        ))
    stmt = stmt.order_by(SequenceEntryRow.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [_entry_dict(e) for e in rows]


@router.post("/collections/{coll_id}/entries/", status_code=201)
async def add_entry(coll_id: str, body: dict[str, Any], db: AsyncSession = Depends(get_db)) -> dict:
    col = await db.get(SequenceCollectionRow, coll_id)
    if col is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    vh = str(body.get("heavy_chain", "")).strip()
    if not vh:
        raise HTTPException(status_code=422, detail="heavy_chain is required")
    entry = SequenceEntryRow(
        id=str(uuid.uuid4()),
        collection_id=coll_id,
        name=body.get("name") or None,
        heavy_chain=vh,
        light_chain=str(body["light_chain"]).strip() or None if body.get("light_chain") else None,
        source_molecule_id=body.get("source_molecule_id") or None,
        notes=body.get("notes") or None,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _entry_dict(entry)


@router.delete("/entries/{entry_id}/", status_code=204)
async def delete_entry(entry_id: str, db: AsyncSession = Depends(get_db)) -> None:
    entry = await db.get(SequenceEntryRow, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    await db.delete(entry)
    await db.commit()


# ── Import from Results DB ────────────────────────────────────────────────────

@router.post("/collections/{coll_id}/import/", status_code=201)
async def import_from_molecules(
    coll_id: str, body: dict[str, Any], db: AsyncSession = Depends(get_db)
) -> list[dict]:
    col = await db.get(SequenceCollectionRow, coll_id)
    if col is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    molecule_ids: list[str] = body.get("molecule_ids", [])
    created = []
    for mol_id in molecule_ids:
        mol = await db.get(MoleculeRow, mol_id)
        if mol is None or not mol.heavy_chain:
            continue
        entry = SequenceEntryRow(
            id=str(uuid.uuid4()),
            collection_id=coll_id,
            name=mol.name,
            heavy_chain=mol.heavy_chain,
            light_chain=mol.light_chain or None,
            source_molecule_id=mol.id,
        )
        db.add(entry)
        created.append(entry)
    await db.commit()
    for e in created:
        await db.refresh(e)
    return [_entry_dict(e) for e in created]
