import ast
import csv
import io
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
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
    # Single query: datasets + per-dataset entry counts via GROUP BY
    counts_q = (
        select(DatasetEntryRow.dataset_id, func.count().label("cnt"))
        .group_by(DatasetEntryRow.dataset_id)
        .subquery()
    )
    rows = (await db.execute(
        select(DatasetRow, func.coalesce(counts_q.c.cnt, 0).label("entry_count"))
        .outerjoin(counts_q, DatasetRow.id == counts_q.c.dataset_id)
        .order_by(DatasetRow.updated_at.desc())
    )).all()
    return [_ds_dict(ds, int(count)) for ds, count in rows]


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


# ── Create dataset from run / loop ────────────────────────────────────────────
# IMPORTANT: this route must be registered BEFORE /{ds_id}/ routes so that
# FastAPI matches the literal "/from_run/" path rather than treating it as a
# dataset ID (which would return 405 Method Not Allowed).

def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _infer_col_type(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    return "text"


def _humanize_col_id(col_id: str) -> str:
    """'abmap_sequence_length' → 'Abmap Sequence Length'"""
    return col_id.replace("_", " ").title()


def _parse_haddock_scores(raw: Any) -> dict[str, float]:
    """Parse haddock_scores — may be a dict, JSON string, or Python repr string."""
    if isinstance(raw, dict):
        return {k: float(v) for k, v in raw.items() if _safe_float(v) is not None}
    if isinstance(raw, str):
        for loader in (json.loads, ast.literal_eval):
            try:
                result = loader(raw)
                if isinstance(result, dict):
                    return {k: float(v) for k, v in result.items() if _safe_float(v) is not None}
            except Exception:
                pass
    return {}


def _extract_from_run_data_with_registry(
    data_json: str,
    run_idx: int,
    extract_features: Any,
    all_features_for_pipeline: Any,
) -> tuple[list[dict], list[dict]]:
    """Pull sequences + all tool features out of a serialised RunRow.data blob."""
    try:
        data = json.loads(data_json or "{}")
    except Exception:
        return [], []

    nodes: dict[str, dict] = data.get("nodes", {})
    pipeline: dict = data.get("pipeline_snapshot", {})
    pipeline_nodes: dict[str, dict] = {n["id"]: n for n in pipeline.get("nodes", [])}
    tool_map: dict[str, str] = {n["id"]: n["tool"] for n in pipeline.get("nodes", [])}

    sequences: list[dict] = []
    all_features: dict[str, Any] = {}
    tool_ids_seen: list[str] = []

    for node_id, node_run in nodes.items():
        if node_run.get("status") != "succeeded":
            continue
        outputs: dict = node_run.get("outputs") or {}
        tool: str = pipeline_nodes.get(node_id, {}).get("tool", "")
        params: dict = pipeline_nodes.get(node_id, {}).get("params", {})

        # Collect sequences from structure/sequence tools
        if any(t in tool for t in ("immunebuilder", "rfantibody", "sequence_input", "sequence_db")):
            vh = (outputs.get("heavy_chain") or params.get("heavy_chain_sequence")
                  or params.get("heavy_chain") or "")
            vl = (outputs.get("light_chain") or params.get("light_chain_sequence")
                  or params.get("light_chain") or "")
            if vh and str(vh).strip() and vh != "__artifact__":
                sequences.append({
                    "heavy_chain": str(vh).strip(),
                    "light_chain": str(vl).strip() or None,
                })

        # Collect all tool features via the registry
        tid = tool_map.get(node_id, "")
        if tid:
            tool_ids_seen.append(tid)
            feats = extract_features(tid, outputs)
            all_features.update(feats)

    # Build column definitions from discovered features
    present_ids = set(all_features.keys())
    col_defs: list[dict] = []
    seen_col_ids: set[str] = set()
    # Computed FeatureSpecs first (explicit labels/types)
    for spec in all_features_for_pipeline(list(set(tool_ids_seen))):
        if spec.col_id in present_ids and spec.col_id not in seen_col_ids:
            col_defs.append({"id": spec.col_id, "name": spec.label, "type": spec.col_type})
            seen_col_ids.add(spec.col_id)
    # Auto-scalar columns not covered by any FeatureSpec
    for feat_id in sorted(present_ids - seen_col_ids):
        col_defs.append({
            "id": feat_id,
            "name": _humanize_col_id(feat_id),
            "type": _infer_col_type(all_features.get(feat_id)),
        })
        seen_col_ids.add(feat_id)

    raw_entries: list[dict] = []
    if sequences:
        for i, seq in enumerate(sequences):
            raw_entries.append({
                "name": f"run_{run_idx}_{i}" if run_idx > 0 else f"seq_{i}",
                "heavy_chain": seq.get("heavy_chain"),
                "light_chain": seq.get("light_chain"),
                "data": all_features,
            })
    elif all_features:
        raw_entries.append({
            "name": f"run_{run_idx}" if run_idx > 0 else "run",
            "data": all_features,
        })

    return raw_entries, col_defs


# Stat fields stored per-entry in loop_history (beyond per-rank haddock_scores)
_STAT_FIELDS = [
    ("haddock_score", "HADDOCK Score"),
    ("score", "Score"),
    ("score_std", "Score Std"),
    ("vdw", "VdW"),
    ("vdw_std", "VdW Std"),
    ("desolv", "Desolv"),
    ("desolv_std", "Desolv Std"),
    ("air", "AIR"),
    ("air_std", "AIR Std"),
    ("bsa", "BSA"),
    ("bsa_std", "BSA Std"),
]


@router.post("/from_run/", status_code=201)
async def create_dataset_from_run(body: dict[str, Any], db: AsyncSession = Depends(get_db)) -> dict:
    """Extract sequences + tool features from a completed run or loop, save as a dataset.

    Accepts: {run_id?, loop_run_id?, dataset_id?, name?}
    Returns: Dataset dict with an extra `added_count` field.

    Data source — loop runs:
      loop_history records the sequence actually evaluated through the full pipeline
      (ImmuneBuilder → HADDOCK). These are the true "input sequences" — not the
      DNN-generated candidates that were proposed but never scored.
      Additionally scans each iteration's RunRow for all tool features via the registry.

    Data source — individual runs:
      Scans node outputs for sequence-producing tools + all tool features via the registry.
    """
    from app.core.tool_features import all_features_for_pipeline, extract_features
    from app.db.models import LoopRunRow, RunRow  # avoid circular import at module level

    run_id: str | None = body.get("run_id") or None
    loop_run_id: str | None = body.get("loop_run_id") or None
    dataset_id: str | None = body.get("dataset_id") or None
    name: str = str(body.get("name") or "Dataset from run").strip() or "Dataset from run"

    if not run_id and not loop_run_id:
        raise HTTPException(status_code=422, detail="Provide run_id or loop_run_id")

    new_cols: list[dict] = []
    raw_entries: list[dict] = []

    if loop_run_id:
        loop_row = await db.get(LoopRunRow, loop_run_id)
        if loop_row is None:
            raise HTTPException(status_code=404, detail="Loop run not found")

        raw_history: list[dict] = []
        try:
            raw_history = json.loads(loop_row.loop_history or "[]")
        except Exception:
            pass

        # load run_ids — stored as a JSON string in the DB, not a Python list
        try:
            run_ids: list[str] = json.loads(loop_row.run_ids or "[]")
        except Exception:
            run_ids = []
        run_rows_by_id: dict[str, Any] = {}
        if run_ids:
            result = await db.execute(
                select(RunRow).where(RunRow.id.in_(run_ids))
            )
            for rr in result.scalars().all():
                run_rows_by_id[rr.id] = rr

        # Build tool_map from the first available run (pipeline snapshot is identical per loop)
        tool_map: dict[str, str] = {}
        for rr in run_rows_by_id.values():
            try:
                snap = json.loads(rr.data or "{}").get("pipeline_snapshot", {})
                tool_map = {n["id"]: n["tool"] for n in snap.get("nodes", [])}
            except Exception:
                pass
            break

        # First pass: discover which columns have non-null values
        rank_keys: set[str] = set()
        present_stats: set[str] = set()
        present_feature_samples: dict[str, Any] = {}  # col_id → first seen value (for type inference)

        for i, entry in enumerate(raw_history):
            hs = _parse_haddock_scores(entry.get("haddock_scores"))
            rank_keys.update(hs.keys())
            for stat_id, _ in _STAT_FIELDS:
                if _safe_float(entry.get(stat_id)) is not None:
                    present_stats.add(stat_id)
            # Collect tool features from the matching RunRow
            rid = entry.get("run_id") or (run_ids[i] if i < len(run_ids) else None)
            if rid and rid in run_rows_by_id:
                try:
                    run_data = json.loads(run_rows_by_id[rid].data or "{}")
                    for node_id, node in run_data.get("nodes", {}).items():
                        if node.get("status") == "succeeded":
                            tid = tool_map.get(node_id, "")
                            feats = extract_features(tid, node.get("outputs") or {})
                            for fk, fv in feats.items():
                                if fk not in present_feature_samples:
                                    present_feature_samples[fk] = fv
                except Exception:
                    pass

        # Build column definitions
        new_cols = [{"id": "iteration", "name": "Iteration", "type": "number"}]
        for rk in sorted(rank_keys):
            label = rk.replace("rank_", "Rank ").replace("_", " ").title()
            new_cols.append({"id": f"score_{rk}", "name": f"HADDOCK {label}", "type": "number"})
        existing_col_ids = {c["id"] for c in new_cols}
        for stat_id, stat_name in _STAT_FIELDS:
            if stat_id not in existing_col_ids and stat_id in present_stats:
                new_cols.append({"id": stat_id, "name": stat_name, "type": "number"})
                existing_col_ids.add(stat_id)
        # Computed FeatureSpecs first (explicit labels/types)
        all_tool_ids = list(set(tool_map.values()))
        for spec in all_features_for_pipeline(all_tool_ids):
            if spec.col_id in present_feature_samples and spec.col_id not in existing_col_ids:
                new_cols.append({"id": spec.col_id, "name": spec.label, "type": spec.col_type})
                existing_col_ids.add(spec.col_id)
        # Auto-scalar columns not covered by any FeatureSpec
        for feat_id in sorted(present_feature_samples.keys()):
            if feat_id not in existing_col_ids:
                new_cols.append({
                    "id": feat_id,
                    "name": _humanize_col_id(feat_id),
                    "type": _infer_col_type(present_feature_samples[feat_id]),
                })
                existing_col_ids.add(feat_id)

        # Second pass: build one entry per evaluated sequence
        for i, entry in enumerate(raw_history):
            vh = str(entry.get("vh") or entry.get("heavy_chain") or "").strip()
            vl = str(entry.get("vl") or entry.get("light_chain") or "").strip() or None
            try:
                iteration = int(entry.get("iteration", 0))
            except (TypeError, ValueError):
                iteration = 0

            hs = _parse_haddock_scores(entry.get("haddock_scores"))
            row_data: dict[str, Any] = {"iteration": iteration}
            for rk in rank_keys:
                row_data[f"score_{rk}"] = hs.get(rk)
            for stat_id, _ in _STAT_FIELDS:
                if stat_id in present_stats:
                    row_data[stat_id] = _safe_float(entry.get(stat_id))

            # Merge registry features from the matching RunRow
            rid = entry.get("run_id") or (run_ids[i] if i < len(run_ids) else None)
            if rid and rid in run_rows_by_id:
                try:
                    run_data = json.loads(run_rows_by_id[rid].data or "{}")
                    for node_id, node in run_data.get("nodes", {}).items():
                        if node.get("status") == "succeeded":
                            tid = tool_map.get(node_id, "")
                            row_data.update(extract_features(tid, node.get("outputs") or {}))
                except Exception:
                    pass

            raw_entries.append({
                "name": f"iter_{iteration}",
                "heavy_chain": vh or None,
                "light_chain": vl,
                "data": row_data,
            })

    else:
        run_row = await db.get(RunRow, run_id)
        if run_row is None:
            raise HTTPException(status_code=404, detail="Run not found")
        raw_entries, new_cols = _extract_from_run_data_with_registry(
            run_row.data, 0, extract_features, all_features_for_pipeline
        )

    if not raw_entries:
        raise HTTPException(
            status_code=422,
            detail="No extractable data found — the run may still be in progress or produced no usable outputs",
        )

    # Create or append to dataset
    if dataset_id:
        ds = await db.get(DatasetRow, dataset_id)
        if ds is None:
            raise HTTPException(status_code=404, detail="Dataset not found")
        existing_ids = {c["id"] for c in _parse_cols(ds)}
        merged = _parse_cols(ds) + [c for c in new_cols if c["id"] not in existing_ids]
        ds.columns = json.dumps(merged)
    else:
        source_label = f"loop {loop_run_id}" if loop_run_id else f"run {run_id}"
        ds = DatasetRow(
            id=str(uuid.uuid4()),
            name=name,
            description=f"Imported from {source_label}",
            columns=json.dumps(new_cols),
        )
        db.add(ds)

    for ed in raw_entries:
        db.add(DatasetEntryRow(
            id=str(uuid.uuid4()),
            dataset_id=ds.id,
            name=ed.get("name"),
            heavy_chain=ed.get("heavy_chain"),
            light_chain=ed.get("light_chain"),
            data=json.dumps(ed.get("data", {})),
        ))

    ds.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(ds)

    total = (await db.execute(
        select(func.count()).where(DatasetEntryRow.dataset_id == ds.id)
    )).scalar() or 0
    return {**_ds_dict(ds, int(total)), "added_count": len(raw_entries)}


@router.get("/{ds_id}/")
async def get_dataset(
    ds_id: str,
    q: str = Query("", description="Search name, VH, VL"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    ds = await db.get(DatasetRow, ds_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    term = q.strip()
    conditions = [DatasetEntryRow.dataset_id == ds_id]
    if term:
        like = f"%{term}%"
        conditions.append(
            or_(
                DatasetEntryRow.name.ilike(like),
                DatasetEntryRow.heavy_chain.ilike(like),
                DatasetEntryRow.light_chain.ilike(like),
            )
        )

    total_filtered = (await db.execute(
        select(func.count(DatasetEntryRow.id)).where(*conditions)
    )).scalar() or 0

    total_all = total_filtered if not term else (
        (await db.execute(
            select(func.count(DatasetEntryRow.id))
            .where(DatasetEntryRow.dataset_id == ds_id)
        )).scalar() or 0
    )

    entries = (await db.execute(
        select(DatasetEntryRow)
        .where(*conditions)
        .order_by(DatasetEntryRow.created_at.asc())
        .limit(limit).offset(offset)
    )).scalars().all()

    result = _ds_dict(ds, total_all)
    result["entries"] = [_entry_dict(e) for e in entries]
    result["total_filtered"] = total_filtered
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
