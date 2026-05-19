"""ML Analysis API — PCA, t-SNE, K-means, clustering on run outputs (embeddings, predictions)."""
from __future__ import annotations

import json
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import RunRow
from app.db.session import AsyncSessionLocal
from app.models.run import Run

router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────────

class MLVectors(BaseModel):
    """Raw vectors + optional labels for analysis."""
    vectors: list[list[float]]           # shape [N, D]
    ids: list[str]                       # sequence ids, length N
    labels: list[float | None] | None = None  # optional numeric labels


class PCARequest(MLVectors):
    n_components: int = 2


class TSNERequest(MLVectors):
    n_components: int = 2
    perplexity: float = 5.0
    max_iter: int = 300


class KMeansRequest(MLVectors):
    n_clusters: int = 3
    n_init: int = 10


class StatsRequest(BaseModel):
    """Multi-run stats: flat list of (run_id, value) pairs."""
    values: list[float]
    labels: list[str] | None = None     # optional per-value names


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_from_row(row: RunRow) -> Run:
    return Run.model_validate_json(row.data)


async def _load_run(run_id: str) -> Run:
    async with AsyncSessionLocal() as db:
        row = await db.get(RunRow, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
    return _run_from_row(row)


def _extract_embeddings(run: Run) -> tuple[list[str], list[list[float]]]:
    """Pull all embedding vectors from a run's succeeded nodes.

    ESM/AbMAP tools emit:
      • 'embeddings': [[float...], ...]  — batch (N vectors, preferred)
      • 'embedding':  [float...]         — single mean-pool vector
    We prefer the batch form so we can show N individual points.
    """
    ids: list[str] = []
    vecs: list[list[float]] = []
    for node_id, nr in run.nodes.items():
        if nr.status != "succeeded":
            continue
        # Prefer batch form ('embeddings') over single ('embedding')
        batch = nr.outputs.get("embeddings")
        single = nr.outputs.get("embedding")

        if isinstance(batch, list) and batch and isinstance(batch[0], list):
            for i, vec in enumerate(batch):
                ids.append(f"{node_id}[{i}]")
                vecs.append(vec)
        elif isinstance(single, dict) and single:
            # {seq_id: [float...]} dict form (from DNN embedding_input)
            for seq_id, vec in single.items():
                if isinstance(vec, list) and vec:
                    ids.append(f"{node_id}·{seq_id}")
                    vecs.append(vec)
        elif isinstance(single, list) and single and isinstance(single[0], (int, float)):
            ids.append(node_id)
            vecs.append(single)
    return ids, vecs


def _extract_predictions(run: Run) -> tuple[list[str], list[float]]:
    """Pull predictions from DNN/predictor nodes."""
    ids: list[str] = []
    vals: list[float] = []
    for node_id, nr in run.nodes.items():
        if nr.status != "succeeded":
            continue
        preds = nr.outputs.get("predictions")
        if not preds:
            continue
        if isinstance(preds, list):
            for p in preds:
                if isinstance(p, dict) and "value" in p:
                    ids.append(str(p.get("id", node_id)))
                    vals.append(float(p["value"]))
                elif isinstance(p, (int, float)):
                    ids.append(f"{node_id}[{len(ids)}]")
                    vals.append(float(p))
        elif isinstance(preds, dict):
            for k, v in preds.items():
                ids.append(str(k))
                vals.append(float(v))
    return ids, vals


def _extract_training_history(run: Run) -> dict[str, Any]:
    """Extract DNN training curves from a run."""
    for node_id, nr in run.nodes.items():
        if nr.status != "succeeded":
            continue
        metrics = nr.outputs.get("metrics")
        if not metrics:
            continue
        history = metrics.get("history")
        if history:
            return {
                "node_id": node_id,
                "history": history,
                "final_train_loss": metrics.get("train_loss"),
                "final_val_loss": metrics.get("val_loss"),
                "final_val_rmse": metrics.get("val_rmse"),
                "epochs": metrics.get("epoch"),
            }
    return {}


# ── Compute endpoints ─────────────────────────────────────────────────────────

def _check_uniform_dim(vectors: list[list[float]]) -> None:
    if not vectors:
        return
    dims = {len(v) for v in vectors}
    if len(dims) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"Embedding dimensions are mixed: {sorted(dims)}. "
                   "Select runs that used the same embedding model (e.g. all ESM-8M = 320d)."
        )


@router.post("/pca")
async def run_pca(req: PCARequest) -> dict[str, Any]:
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    _check_uniform_dim(req.vectors)
    X = np.array(req.vectors, dtype=float)
    if X.shape[0] < 2:
        raise HTTPException(status_code=400, detail="PCA needs at least 2 samples")

    n_comp = min(req.n_components, X.shape[0], X.shape[1])
    scaler = StandardScaler()
    X_sc = scaler.fit_transform(X)
    pca = PCA(n_components=n_comp)
    coords = pca.fit_transform(X_sc)

    return {
        "method": "pca",
        "n_components": n_comp,
        "points": [
            {"id": sid, "x": float(coords[i, 0]), "y": float(coords[i, 1]),
             "label": req.labels[i] if req.labels else None}
            for i, sid in enumerate(req.ids)
        ],
        "explained_variance": pca.explained_variance_ratio_.tolist(),
        "explained_variance_cumulative": float(pca.explained_variance_ratio_[:n_comp].sum()),
    }


@router.post("/tsne")
async def run_tsne(req: TSNERequest) -> dict[str, Any]:
    from sklearn.manifold import TSNE
    from sklearn.preprocessing import StandardScaler

    _check_uniform_dim(req.vectors)
    X = np.array(req.vectors, dtype=float)
    if X.shape[0] < 3:
        raise HTTPException(status_code=400, detail="t-SNE needs at least 3 samples")

    perp = min(req.perplexity, X.shape[0] - 1)
    scaler = StandardScaler()
    X_sc = scaler.fit_transform(X)
    tsne = TSNE(n_components=2, perplexity=perp, max_iter=req.max_iter, random_state=42)
    coords = tsne.fit_transform(X_sc)

    return {
        "method": "tsne",
        "perplexity": perp,
        "kl_divergence": float(tsne.kl_divergence_),
        "points": [
            {"id": sid, "x": float(coords[i, 0]), "y": float(coords[i, 1]),
             "label": req.labels[i] if req.labels else None}
            for i, sid in enumerate(req.ids)
        ],
    }


@router.post("/kmeans")
async def run_kmeans(req: KMeansRequest) -> dict[str, Any]:
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    _check_uniform_dim(req.vectors)
    X = np.array(req.vectors, dtype=float)
    k = min(req.n_clusters, X.shape[0])
    if k < 2:
        raise HTTPException(status_code=400, detail="K-means needs at least 2 samples")

    scaler = StandardScaler()
    X_sc = scaler.fit_transform(X)
    km = KMeans(n_clusters=k, n_init=req.n_init, random_state=42)
    labels = km.fit_predict(X_sc)
    sil = float(silhouette_score(X_sc, labels)) if k < X.shape[0] else 0.0
    inertia = float(km.inertia_)

    cluster_sizes = {int(c): int((labels == c).sum()) for c in range(k)}

    return {
        "method": "kmeans",
        "n_clusters": k,
        "silhouette_score": sil,
        "inertia": inertia,
        "assignments": [
            {"id": sid, "cluster": int(labels[i]),
             "label": req.labels[i] if req.labels else None}
            for i, sid in enumerate(req.ids)
        ],
        "cluster_sizes": cluster_sizes,
        "cluster_centers": km.cluster_centers_.tolist(),
    }


@router.post("/stats")
async def run_stats(req: StatsRequest) -> dict[str, Any]:
    vals = np.array(req.values, dtype=float)
    if len(vals) == 0:
        raise HTTPException(status_code=400, detail="No values provided")

    hist, bin_edges = np.histogram(vals, bins=min(20, max(5, len(vals) // 2)))
    percentiles = np.percentile(vals, [10, 25, 50, 75, 90]).tolist()

    return {
        "count": int(len(vals)),
        "mean": float(np.mean(vals)),
        "std": float(np.std(vals)),
        "min": float(np.min(vals)),
        "max": float(np.max(vals)),
        "percentiles": {"p10": percentiles[0], "p25": percentiles[1], "p50": percentiles[2],
                        "p75": percentiles[3], "p90": percentiles[4]},
        "histogram": {
            "counts": hist.tolist(),
            "bin_edges": bin_edges.tolist(),
        },
        "items": [{"id": req.labels[i] if req.labels else str(i), "value": float(v)}
                  for i, v in enumerate(vals)],
    }


# ── Run-level helpers (fetch + auto-analyze) ──────────────────────────────────

@router.get("/runs/{run_id}/embeddings")
async def get_run_embeddings(run_id: str) -> dict[str, Any]:
    """Return all embedding vectors from a run (for client-side PCA/t-SNE)."""
    run = await _load_run(run_id)
    ids, vecs = _extract_embeddings(run)
    return {"run_id": run_id, "count": len(vecs), "ids": ids, "vectors": vecs}


@router.get("/runs/{run_id}/predictions")
async def get_run_predictions(run_id: str) -> dict[str, Any]:
    """Return all predictions from DNN / property predictor nodes in a run."""
    run = await _load_run(run_id)
    ids, vals = _extract_predictions(run)
    _, all_vals = _extract_predictions(run)
    stats: dict[str, Any] = {}
    if all_vals:
        arr = np.array(all_vals)
        stats = {"mean": float(arr.mean()), "std": float(arr.std()),
                 "min": float(arr.min()), "max": float(arr.max())}
    return {
        "run_id": run_id,
        "count": len(vals),
        "predictions": [{"id": ids[i], "value": vals[i]} for i in range(len(ids))],
        "stats": stats,
    }


@router.get("/runs/{run_id}/training")
async def get_run_training(run_id: str) -> dict[str, Any]:
    """Return DNN training history (loss curves) from a run."""
    run = await _load_run(run_id)
    result = _extract_training_history(run)
    if not result:
        raise HTTPException(status_code=404, detail="No training history in this run")
    return {"run_id": run_id, **result}


@router.get("/runs/{run_id}/summary")
async def get_run_summary(run_id: str) -> dict[str, Any]:
    """Full analysis summary for a run: nodes, embeddings count, predictions, training."""
    run = await _load_run(run_id)
    ids, vecs = _extract_embeddings(run)
    pred_ids, pred_vals = _extract_predictions(run)
    training = _extract_training_history(run)

    node_tools = {
        node_id: (run.pipeline_snapshot.get("nodes", []) or [])
        for node_id in run.nodes
    }
    # simpler: just read the tool from pipeline_snapshot
    snap_nodes = {n["id"]: n["tool"] for n in run.pipeline_snapshot.get("nodes", [])}

    return {
        "run_id": run_id,
        "status": run.status,
        "pipeline_name": run.pipeline_snapshot.get("name", "—"),
        "nodes": [
            {
                "node_id": nid,
                "tool": snap_nodes.get(nid, "?"),
                "status": nr.status,
                "has_embedding": bool(nr.outputs.get("embedding") or nr.outputs.get("embeddings")),
                "has_predictions": bool(nr.outputs.get("predictions")),
                "has_training": bool(nr.outputs.get("metrics", {}).get("history")),
                "error": nr.error,
            }
            for nid, nr in run.nodes.items()
        ],
        "embeddings": {"count": len(vecs), "dim": len(vecs[0]) if vecs else 0, "ids": ids},
        "predictions": {"count": len(pred_vals),
                        "values": [{"id": pred_ids[i], "value": pred_vals[i]} for i in range(len(pred_ids))]},
        "training": training,
    }


@router.post("/runs/compare")
async def compare_runs(run_ids: list[str]) -> dict[str, Any]:
    """Compare predictions and metrics across multiple runs."""
    results = []
    for rid in run_ids[:10]:   # cap at 10 to avoid overload
        try:
            run = await _load_run(rid)
        except HTTPException:
            continue
        pred_ids, pred_vals = _extract_predictions(run)
        training = _extract_training_history(run)
        results.append({
            "run_id": rid,
            "pipeline_name": run.pipeline_snapshot.get("name", "—"),
            "status": run.status,
            "prediction_count": len(pred_vals),
            "prediction_mean": float(np.mean(pred_vals)) if pred_vals else None,
            "prediction_std": float(np.std(pred_vals)) if pred_vals else None,
            "final_train_loss": training.get("final_train_loss"),
            "final_val_rmse": training.get("final_val_rmse"),
            "epochs": training.get("epochs"),
        })
    return {"runs": results}
