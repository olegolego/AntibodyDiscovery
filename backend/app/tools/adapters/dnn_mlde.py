"""DNN-MLDE adapter — runs tools/dnn_mlde/run.py via the custom_dnn venv (PyTorch).

On top of the RCC-MLDE interface, this adapter optionally pre-loads a labelled
dataset from the platform library and AbMAP-embeds its sequences, injecting the
result as `pretrain_dataset` into the runner payload.

Embedding lookup order:
  1. abmap_embeddings DB cache (cached from prior runs)
  2. AbMAP HTTP endpoint (fallback for uncached sequences)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.config import settings
from app.models.tool_spec import ToolSpec
from app.tools.abmap_db import abmap_cache
from app.tools.base import RunContext
from app.tools.http_tool import post_with_retry
from app.tools.subprocess_runner import run_tool_subprocess

_CUSTOM_DNN_VENV = Path(__file__).resolve().parents[4] / "tools" / "custom_dnn" / ".venv" / "bin" / "python"
_BACKEND_VENV    = Path(__file__).resolve().parents[3] / ".venv" / "bin" / "python"

# Prefer the custom_dnn venv (has PyTorch); fall back to backend venv (has sklearn but not torch)
_DNN_MLDE_PYTHON = Path(
    os.getenv("DNN_MLDE_PYTHON", str(_CUSTOM_DNN_VENV if _CUSTOM_DNN_VENV.exists() else _BACKEND_VENV))
)

# AL_results column UUIDs → rank name (score_mean_rank0 → scores_rank_1, etc.)
_SCORE_COL_IDS = {
    "9de945fa-58f0-42dd-a9c9-0e07510e2171": "scores_rank_1",  # score_mean_rank0 → rank 1
    "e40ad664-92a5-4594-87f2-f4938a0cfd14": "scores_rank_2",
    "e7774a55-0a08-45eb-af82-eceab8ce8080": "scores_rank_3",
    "686ee1a5-f721-4c7d-bdfc-bdf0fa783ed8": "scores_rank_4",
}

# Fallback: column names (case-insensitive) to rank index
_SCORE_COL_NAMES = {
    "score_mean_rank0": "scores_rank_1",
    "score_mean_rank1": "scores_rank_2",
    "score_mean_rank2": "scores_rank_3",
    "score_mean_rank3": "scores_rank_4",
}

# VH column UUID for AL_results
_VH_COL_ID = "adcdd7d4-612b-4c11-a68b-4f4d8be0d308"


def _coerce_scores(raw: Any) -> dict[str, float] | None:
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        return {"seq_0": float(raw)}
    if not isinstance(raw, dict):
        return None
    if "score" in raw and isinstance(raw["score"], (int, float)):
        return {"seq_0": float(raw["score"])}
    out: dict[str, float] = {}
    for k, v in raw.items():
        if isinstance(v, (int, float)):
            out[str(k)] = float(v)
        elif isinstance(v, dict):
            score = v.get("score") or v.get("binding_energy") or v.get("total_energy")
            if score is not None:
                out[str(k)] = float(score)
    return out or None


def _coerce_embeddings(raw: Any) -> dict[str, list[float]] | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        result: dict[str, list[float]] = {}
        for k, v in raw.items():
            if isinstance(v, list) and v and isinstance(v[0], (int, float)):
                result[str(k)] = v
        return result or None
    if isinstance(raw, list) and raw:
        if isinstance(raw[0], (int, float)):
            return {"seq_0": raw}
        if isinstance(raw[0], list) and raw[0] and isinstance(raw[0][0], (int, float)):
            return {f"seq_{i}": v for i, v in enumerate(raw)}
    return None


async def _load_pretrain_dataset(
    dataset_id: str,
    run_ctx: RunContext,
) -> dict[str, Any] | None:
    """Load dataset from DB, AbMAP-embed sequences, return pretrain_dataset dict."""
    from sqlalchemy import select, text
    from app.db.session import AsyncSessionLocal

    await run_ctx.alog(f"DNN-MLDE: loading pretrain dataset {dataset_id[:8]}…")

    # ── Read dataset schema (columns) ─────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        ds_row = (await db.execute(
            text("SELECT id, name, columns FROM datasets WHERE id = :did"),
            {"did": dataset_id},
        )).fetchone()

    if ds_row is None:
        await run_ctx.alog(f"DNN-MLDE: dataset {dataset_id[:8]} not found — skipping pretrain")
        return None

    ds_name = ds_row[1]
    columns_raw = ds_row[2]
    try:
        columns: list[dict] = json.loads(columns_raw) if isinstance(columns_raw, str) else (columns_raw or [])
    except Exception:
        columns = []

    # Build column_id → name map and find score columns
    col_id_to_name = {c["id"]: c["name"] for c in columns if isinstance(c, dict)}
    col_name_to_id = {c["name"].lower(): c["id"] for c in columns if isinstance(c, dict)}

    # Determine VH column id: prefer known AL_results UUID, else look for "VH" column
    vh_col_id = _VH_COL_ID if _VH_COL_ID in col_id_to_name else col_name_to_id.get("vh")

    # Determine score column ids → rank name mapping
    score_col_map: dict[str, str] = {}
    for cid, rank_key in _SCORE_COL_IDS.items():
        if cid in col_id_to_name:
            score_col_map[cid] = rank_key
    if not score_col_map:
        # Fall back to name-based matching
        for name_lower, rank_key in _SCORE_COL_NAMES.items():
            cid = col_name_to_id.get(name_lower)
            if cid:
                score_col_map[cid] = rank_key

    if not score_col_map:
        await run_ctx.alog(f"DNN-MLDE: no score columns found in {ds_name} — skipping pretrain")
        return None

    await run_ctx.alog(f"DNN-MLDE: {ds_name} — found {len(score_col_map)} score columns")

    # ── Read all entries ──────────────────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            text("SELECT id, heavy_chain, data FROM dataset_entries WHERE dataset_id = :did"),
            {"did": dataset_id},
        )).fetchall()

    await run_ctx.alog(f"DNN-MLDE: {len(rows)} entries in {ds_name}")

    # Parse sequences and scores
    seq_map: dict[str, str] = {}    # entry_id → VH sequence
    score_by_rank: dict[str, dict[str, float]] = {v: {} for v in score_col_map.values()}

    for row in rows:
        entry_id = row[0]
        heavy_chain_col = row[1] or ""
        data_raw = row[2] or "{}"
        try:
            data: dict = json.loads(data_raw) if isinstance(data_raw, str) else (data_raw or {})
        except Exception:
            data = {}

        # Resolve VH sequence
        vh_seq = heavy_chain_col.strip()
        if not vh_seq and vh_col_id:
            vh_seq = str(data.get(vh_col_id, "")).strip()
        if not vh_seq:
            continue

        seq_map[entry_id] = vh_seq

        # Extract scores
        for col_id, rank_key in score_col_map.items():
            raw_val = data.get(col_id)
            if raw_val is not None:
                try:
                    score_by_rank[rank_key][entry_id] = float(raw_val)
                except (ValueError, TypeError):
                    pass

    if not seq_map:
        await run_ctx.alog(f"DNN-MLDE: no valid sequences in {ds_name} — skipping pretrain")
        return None

    await run_ctx.alog(f"DNN-MLDE: {len(seq_map)} sequences to embed")

    # ── AbMAP embed ──────────────────────────────────────────────────────────
    embeddings: dict[str, list[float]] = {}
    n_cached = 0
    n_fetched = 0
    n_failed = 0
    total = len(seq_map)

    for i, (entry_id, vh_seq) in enumerate(seq_map.items(), 1):
        # Try cache first
        cached = await abmap_cache.get(vh_seq, "", chain_type="H", task="structure", embedding_type="fixed", num_mutations=10)
        if cached is not None:
            emb = cached.get("embedding", [])
            if emb:
                embeddings[entry_id] = emb
                n_cached += 1
                continue

        # Call AbMAP endpoint
        try:
            data_resp = await post_with_retry(
                settings.abmap_url,
                "/embed",
                {"sequence": vh_seq, "chain_type": "H", "task": "structure", "embedding_type": "fixed", "num_mutations": 10},
                tool_name="AbMAP",
                timeout=120,
                on_log=None,
            )
        except Exception as exc:
            n_failed += 1
            if n_failed <= 3:
                await run_ctx.alog(f"  AbMAP failed for entry {entry_id}: {exc}")
            continue

        emb = data_resp.get("embedding", [])
        if emb:
            embeddings[entry_id] = emb
            n_fetched += 1
            # Cache for future
            try:
                await abmap_cache.put(
                    vh_seq, "",
                    chain_type="H", task="structure", embedding_type="fixed", num_mutations=10,
                    result=data_resp,
                    run_id=run_ctx.run_id,
                    node_id=run_ctx.node_id,
                )
            except Exception:
                pass

        if i % 100 == 0 or i == total:
            await run_ctx.alog(f"  Embedded {i}/{total} (cached={n_cached}, fetched={n_fetched}, failed={n_failed})")

    await run_ctx.alog(
        f"DNN-MLDE: pretrain embeddings ready — {len(embeddings)}/{total} "
        f"(cached={n_cached}, fetched={n_fetched}, failed={n_failed})"
    )

    if not embeddings:
        return None

    # Only keep scores where we have embeddings
    pretrain: dict[str, Any] = {"embeddings": embeddings}
    for rank_key, scores in score_by_rank.items():
        filtered = {eid: v for eid, v in scores.items() if eid in embeddings}
        if filtered:
            pretrain[rank_key] = filtered

    return pretrain


class DNNMLDEAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        candidate_sequence = str(inputs.get("candidate_sequence") or "").strip() or None
        embeddings         = _coerce_embeddings(inputs.get("embeddings"))
        candidate_emb      = _coerce_embeddings(inputs.get("candidate_embeddings"))

        if candidate_sequence and candidate_emb and list(candidate_emb.keys()) == ["seq_0"]:
            candidate_emb = {candidate_sequence: candidate_emb["seq_0"]}

        scores_rank_1 = _coerce_scores(inputs.get("scores_rank_1"))
        scores_rank_2 = _coerce_scores(inputs.get("scores_rank_2"))
        scores_rank_3 = _coerce_scores(inputs.get("scores_rank_3"))
        scores_rank_4 = _coerce_scores(inputs.get("scores_rank_4"))
        model_artifact_in = inputs.get("model_artifact")
        accumulated = inputs.get("accumulated_dataset")

        n_ranks = sum(1 for s in [scores_rank_1, scores_rank_2, scores_rank_3, scores_rank_4] if s)
        explicit_mode = str(inputs.get("mode") or "").strip().lower()
        if explicit_mode == "train":
            mode = "train+score"
        elif explicit_mode == "score" and model_artifact_in is not None:
            mode = "inference"
        elif explicit_mode == "score" and model_artifact_in is None:
            # No artifact yet (e.g. first iteration or standalone use) — train first
            mode = "train+score"
            await run_ctx.alog("DNN-MLDE: mode=score but no model_artifact — falling back to train+score")
        else:
            mode = "inference" if model_artifact_in and not scores_rank_1 else "train+score"
        await run_ctx.alog(
            f"DNN-MLDE: mode={mode}, ranks={n_ranks}, "
            f"n_train={len(embeddings) if embeddings else 0}, "
            f"n_candidates={len(candidate_emb) if candidate_emb else (len(embeddings) if embeddings else 0)}"
        )

        # ── Pre-load pretrain dataset if requested ────────────────────────────
        pretrain_dataset_id = str(inputs.get("pretrain_dataset_id") or "").strip() or None
        pretrain_dataset: dict | None = None
        if pretrain_dataset_id and mode == "train+score":
            try:
                pretrain_dataset = await _load_pretrain_dataset(pretrain_dataset_id, run_ctx)
                n_pre = len((pretrain_dataset or {}).get("embeddings") or {})
                await run_ctx.alog(f"DNN-MLDE: pretrain_dataset ready — {n_pre} sequences")
            except Exception as exc:
                await run_ctx.alog(f"DNN-MLDE: pretrain load failed ({exc}) — continuing without")
                pretrain_dataset = None

        payload: dict[str, Any] = {
            "n_committee":    int(inputs.get("n_committee", 5)),
            "epochs":         int(inputs.get("epochs", 150)),
            "lr":             float(inputs.get("lr", 5e-4)),
            "batch_size":     int(inputs.get("batch_size", 128)),
            "kappa_epi":      float(inputs.get("kappa_epi", 2.0)),
            "kappa_conf":     float(inputs.get("kappa_conf", 0.5)),
            "top_k":          int(inputs.get("top_k", 20)),
            "lower_is_better": bool(inputs.get("lower_is_better", True)),
        }

        # Pass architecture_spec from the DNN Designer if present
        arch_spec = inputs.get("architecture_spec")
        if arch_spec:
            payload["architecture_spec"] = arch_spec

        if pretrain_dataset:
            payload["pretrain_dataset"] = pretrain_dataset
        if accumulated:
            payload["accumulated_dataset"] = accumulated
        if embeddings:
            payload["embeddings"] = embeddings
        if candidate_emb:
            payload["candidate_embeddings"] = candidate_emb
        if scores_rank_1:
            payload["scores_rank_1"] = scores_rank_1
        if scores_rank_2:
            payload["scores_rank_2"] = scores_rank_2
        if scores_rank_3:
            payload["scores_rank_3"] = scores_rank_3
        if scores_rank_4:
            payload["scores_rank_4"] = scores_rank_4
        if model_artifact_in:
            payload["model_artifact"] = model_artifact_in
        rank_weights = inputs.get("rank_weights")
        if rank_weights:
            payload["rank_weights"] = rank_weights

        outputs = await run_tool_subprocess(
            tool_id="dnn_mlde",
            inputs=payload,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=str(_DNN_MLDE_PYTHON),
        )

        top = outputs.get("top_sequences", [])
        metrics = outputs.get("metrics", {})
        await run_ctx.alog(
            f"Done — {metrics.get('n_candidates', 0)} scored, "
            f"pretrain={metrics.get('n_pretrain', 0)}, "
            f"accum={metrics.get('n_accumulated', 0)}, "
            f"top-{len(top)}: {top[:3]}"
        )
        return outputs
