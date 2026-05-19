from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from app.db.models import DatasetEntryRow, DatasetRow
from app.db.session import AsyncSessionLocal
from app.tools.base import RunContext, ToolSpec


def _resolve_col_id(columns_info: list[dict], col_name: str) -> str | None:
    """Return the custom column id for a given name. None means it's a built-in field."""
    if col_name in ("heavy_chain", "light_chain", ""):
        return None
    for col in columns_info:
        if col.get("name") == col_name or col.get("id") == col_name:
            return col.get("id")
    return col_name  # treat as literal id fallback


def _entry_value(entry: DatasetEntryRow, col_name: str, col_id: str | None) -> str:
    if col_name in ("heavy_chain", "light_chain"):
        return getattr(entry, col_name, "") or ""
    if not col_id:
        return ""
    raw = entry.data
    data: dict = json.loads(raw) if isinstance(raw, str) else (raw or {})
    return str(data.get(col_id, "") or "")


class DatasetToolAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        dataset_id   = str(inputs.get("dataset_id") or "").strip()
        vh_column    = str(inputs.get("vh_column") or "heavy_chain").strip()
        vl_column    = str(inputs.get("vl_column") or "light_chain").strip()
        label_column = str(inputs.get("label_column") or "").strip()

        if not dataset_id:
            raise ValueError("dataset: no dataset selected — pick one in the param panel")

        async with AsyncSessionLocal() as db:
            dataset = await db.get(DatasetRow, dataset_id)
            if dataset is None:
                raise ValueError(f"dataset: dataset '{dataset_id}' not found")

            result = await db.execute(
                select(DatasetEntryRow)
                .where(DatasetEntryRow.dataset_id == dataset_id)
                .order_by(DatasetEntryRow.created_at)
            )
            entries = result.scalars().all()

        await run_ctx.alog(f"dataset: loading {len(entries)} entries from '{dataset.name}'")

        raw_columns = dataset.columns
        columns_info: list[dict] = (
            json.loads(raw_columns) if isinstance(raw_columns, str) else (raw_columns or [])
        )

        vh_col_id    = _resolve_col_id(columns_info, vh_column)
        vl_col_id    = _resolve_col_id(columns_info, vl_column) if vl_column else None
        label_col_id = _resolve_col_id(columns_info, label_column) if label_column else None

        # Determine label column type for info metadata
        label_col_type: str | None = None
        if label_column and label_column not in ("heavy_chain", "light_chain"):
            for col in columns_info:
                if col.get("name") == label_column or col.get("id") == label_column:
                    label_col_type = col.get("type")
                    break

        vh_parts: list[str] = []
        vl_parts: list[str] = []
        labels: dict[str, Any] = {}

        for entry in entries:
            seq_id = (entry.name or str(entry.id)).replace(" ", "_")

            vh_seq = _entry_value(entry, vh_column, vh_col_id)
            if vh_seq:
                vh_parts.append(f">{seq_id}")
                vh_parts.append(vh_seq)

            if vl_column:
                vl_seq = _entry_value(entry, vl_column, vl_col_id)
                if vl_seq:
                    vl_parts.append(f">{seq_id}")
                    vl_parts.append(vl_seq)

            if label_column:
                col_id_for_label = label_col_id if label_col_id is not None else label_column
                label_val = _entry_value(entry, label_column, col_id_for_label)
                if label_val != "":
                    labels[seq_id] = label_val

        heavy_chain = "\n".join(vh_parts)
        light_chain = "\n".join(vl_parts)
        vh_count = heavy_chain.count(">")
        vl_count = light_chain.count(">")

        await run_ctx.alog(
            f"dataset: {vh_count} VH"
            + (f", {vl_count} VL" if vl_column else "")
            + (f", {len(labels)} labels" if labels else "")
        )

        return {
            "heavy_chain": heavy_chain,
            "light_chain": light_chain,
            "labels": labels,
            "info": {
                "name": dataset.name,
                "description": dataset.description or "",
                "entry_count": len(entries),
                "vh_count": vh_count,
                "vl_count": vl_count,
                "vh_column": vh_column,
                "vl_column": vl_column,
                "label_column": label_column or None,
                "label_column_type": label_col_type,
                "columns": columns_info,
            },
        }
