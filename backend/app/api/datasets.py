import csv
import io
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DatasetEntryRow, DatasetRow, MoleculeRow
from app.db.session import get_db

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_cols(ds: DatasetRow) -> list[dict]:
    try:
        return json.loads(ds.columns or "[]")
    except Exception:
        return []


def _ds_dict(ds: DatasetRow, entry_count: int = 0) -> dict:
    return {
        "id": ds.id,
        "name": ds.name,
        "description": ds.description,
        "columns": _parse_cols(ds),
        "entry_count": entry_count,
        "created_at": ds.created_at.isoformat(),
        "updated_at": ds.updated_at.isoformat(),
    }


def _entry_dict(e: DatasetEntryRow) -> dict:
    try:
        data = json.loads(e.data or "{}")
    except Exception:
        data = {}
    return {
        "id": e.id,
        "dataset_id": e.dataset_id,
        "name": e.name,
        "heavy_chain": e.heavy_chain,
        "light_chain": e.light_chain,
        "source_molecule_id": e.source_molecule_id,
        "data": data,
        "created_at": e.created_at.isoformat(),
        "updated_at": e.updated_at.isoformat(),
    }


# ── Dataset CRUD ──────────────────────────────────────────────────────────────

@router.get("/")
async def list_datasets(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(
        select(DatasetRow).order_by(DatasetRow.updated_at.desc())
    )).scalars().all()
    result = []
    for ds in rows:
        count_row = await db.execute(
            select(DatasetEntryRow.id).where(DatasetEntryRow.dataset_id == ds.id)
        )
        count = len(count_row.scalars().all())
        result.append(_ds_dict(ds, count))
    return result


@router.post("/", status_code=201)
async def create_dataset(body: dict[str, Any], db: AsyncSession = Depends(get_db)) -> dict:
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    ds = DatasetRow(
        id=str(uuid.uuid4()),
        name=name,
        description=body.get("description") or None,
        columns=json.dumps(body.get("columns", [])),
    )
    db.add(ds)
    await db.commit()
    await db.refresh(ds)
    return _ds_dict(ds, 0)


@router.get("/{ds_id}/")
async def get_dataset(ds_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    ds = await db.get(DatasetRow, ds_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    entries = (await db.execute(
        select(DatasetEntryRow)
        .where(DatasetEntryRow.dataset_id == ds_id)
        .order_by(DatasetEntryRow.created_at.asc())
    )).scalars().all()
    result = _ds_dict(ds, len(entries))
    result["entries"] = [_entry_dict(e) for e in entries]
    return result


@router.patch("/{ds_id}/")
async def update_dataset(ds_id: str, body: dict[str, Any], db: AsyncSession = Depends(get_db)) -> dict:
    """Update name/description and/or replace the columns schema."""
    ds = await db.get(DatasetRow, ds_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if "name" in body and str(body["name"]).strip():
        ds.name = str(body["name"]).strip()
    if "description" in body:
        ds.description = body["description"] or None
    if "columns" in body:
        ds.columns = json.dumps(body["columns"])
    ds.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(ds)
    count_row = await db.execute(
        select(DatasetEntryRow.id).where(DatasetEntryRow.dataset_id == ds_id)
    )
    return _ds_dict(ds, len(count_row.scalars().all()))


@router.delete("/{ds_id}/", status_code=204)
async def delete_dataset(ds_id: str, db: AsyncSession = Depends(get_db)) -> None:
    ds = await db.get(DatasetRow, ds_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    entries = (await db.execute(
        select(DatasetEntryRow).where(DatasetEntryRow.dataset_id == ds_id)
    )).scalars().all()
    for e in entries:
        await db.delete(e)
    await db.delete(ds)
    await db.commit()


# ── Entry CRUD ────────────────────────────────────────────────────────────────

@router.get("/{ds_id}/entries/")
async def list_entries(ds_id: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(
        select(DatasetEntryRow)
        .where(DatasetEntryRow.dataset_id == ds_id)
        .order_by(DatasetEntryRow.created_at.asc())
    )).scalars().all()
    return [_entry_dict(e) for e in rows]


@router.post("/{ds_id}/entries/", status_code=201)
async def add_entry(ds_id: str, body: dict[str, Any], db: AsyncSession = Depends(get_db)) -> dict:
    ds = await db.get(DatasetRow, ds_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    entry = DatasetEntryRow(
        id=str(uuid.uuid4()),
        dataset_id=ds_id,
        name=body.get("name") or None,
        heavy_chain=body.get("heavy_chain") or None,
        light_chain=body.get("light_chain") or None,
        source_molecule_id=body.get("source_molecule_id") or None,
        data=json.dumps(body.get("data", {})),
    )
    db.add(entry)
    ds.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(entry)
    return _entry_dict(entry)


@router.patch("/{ds_id}/entries/{entry_id}/")
async def update_entry(
    ds_id: str, entry_id: str, body: dict[str, Any], db: AsyncSession = Depends(get_db)
) -> dict:
    """Patch one or more fields of an entry.  `data` is merged, not replaced."""
    entry = await db.get(DatasetEntryRow, entry_id)
    if entry is None or entry.dataset_id != ds_id:
        raise HTTPException(status_code=404, detail="Entry not found")
    if "name" in body:
        entry.name = body["name"] or None
    if "heavy_chain" in body:
        entry.heavy_chain = body["heavy_chain"] or None
    if "light_chain" in body:
        entry.light_chain = body["light_chain"] or None
    if "data" in body:
        existing: dict = json.loads(entry.data or "{}")
        existing.update(body["data"])
        entry.data = json.dumps(existing)
    entry.updated_at = datetime.utcnow()

    ds = await db.get(DatasetRow, ds_id)
    if ds:
        ds.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(entry)
    return _entry_dict(entry)


@router.delete("/{ds_id}/entries/{entry_id}/", status_code=204)
async def delete_entry(ds_id: str, entry_id: str, db: AsyncSession = Depends(get_db)) -> None:
    entry = await db.get(DatasetEntryRow, entry_id)
    if entry is None or entry.dataset_id != ds_id:
        raise HTTPException(status_code=404, detail="Entry not found")
    await db.delete(entry)
    await db.commit()


@router.post("/{ds_id}/entries/bulk/", status_code=201)
async def bulk_add_entries(
    ds_id: str, body: dict[str, Any], db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Add multiple entries at once (used by CSV import)."""
    ds = await db.get(DatasetRow, ds_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    rows_in: list[dict] = body.get("entries", [])
    created = []
    for r in rows_in:
        entry = DatasetEntryRow(
            id=str(uuid.uuid4()),
            dataset_id=ds_id,
            name=r.get("name") or None,
            heavy_chain=r.get("heavy_chain") or None,
            light_chain=r.get("light_chain") or None,
            source_molecule_id=r.get("source_molecule_id") or None,
            data=json.dumps(r.get("data", {})),
        )
        db.add(entry)
        created.append(entry)
    ds.updated_at = datetime.utcnow()
    await db.commit()
    for e in created:
        await db.refresh(e)
    return [_entry_dict(e) for e in created]


# ── Import from Results DB ────────────────────────────────────────────────────

@router.post("/{ds_id}/import/molecules/", status_code=201)
async def import_from_molecules(
    ds_id: str, body: dict[str, Any], db: AsyncSession = Depends(get_db)
) -> list[dict]:
    ds = await db.get(DatasetRow, ds_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    molecule_ids: list[str] = body.get("molecule_ids", [])
    created = []
    for mol_id in molecule_ids:
        mol = await db.get(MoleculeRow, mol_id)
        if mol is None:
            continue
        entry = DatasetEntryRow(
            id=str(uuid.uuid4()),
            dataset_id=ds_id,
            name=mol.name,
            heavy_chain=mol.heavy_chain or None,
            light_chain=mol.light_chain or None,
            source_molecule_id=mol.id,
            data="{}",
        )
        db.add(entry)
        created.append(entry)
    ds.updated_at = datetime.utcnow()
    await db.commit()
    for e in created:
        await db.refresh(e)
    return [_entry_dict(e) for e in created]


# ── CSV export ────────────────────────────────────────────────────────────────

@router.get("/{ds_id}/export.csv")
async def export_csv(ds_id: str, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    ds = await db.get(DatasetRow, ds_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    entries = (await db.execute(
        select(DatasetEntryRow)
        .where(DatasetEntryRow.dataset_id == ds_id)
        .order_by(DatasetEntryRow.created_at.asc())
    )).scalars().all()
    cols = _parse_cols(ds)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "VH", "VL"] + [c["name"] for c in cols])
    for e in entries:
        try:
            data = json.loads(e.data or "{}")
        except Exception:
            data = {}
        row = [e.name or "", e.heavy_chain or "", e.light_chain or ""]
        for col in cols:
            val = data.get(col["id"], "")
            row.append("" if val is None else str(val))
        writer.writerow(row)

    safe_name = ds.name.replace('"', '').replace("/", "-")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
    )
