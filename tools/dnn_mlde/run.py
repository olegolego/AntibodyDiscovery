"""DNN-MLDE: Visual-architecture committee for ML-Assisted Directed Evolution.

Uses the DynamicDNN class from custom_dnn — the same architecture that the
DNN Designer produces — as the committee member backbone.

Each of the M committee members is a fresh DynamicDNN instance trained on a
bootstrap resample of the combined dataset. The uncertainty structure and
acquisition function are identical to RCC-MLDE:
  α(x) = μ̄ + κ_epi·σ_epi − κ_conf·σ_conf

Data priority (lowest to highest, later overwrites for same seq_id):
  pretrain_dataset  (AL_results pre-loaded by adapter)
  accumulated_dataset (previous loop iterations)
  current round     (embeddings + scores_rank_1..4)
"""
from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

# ── Import DynamicDNN from custom_dnn (sibling tool, same venv) ───────────────
_CUSTOM_DNN_DIR = Path(__file__).resolve().parent.parent / "custom_dnn"
if str(_CUSTOM_DNN_DIR) not in sys.path:
    sys.path.insert(0, str(_CUSTOM_DNN_DIR))

from run import DynamicDNN  # type: ignore[import]  # custom_dnn/run.py

# ── Default architecture spec (used if no architecture_spec provided) ─────────
# Input(512) → Linear(256) + ReLU + Dropout(0.2) → Linear(128) + ReLU + Dropout(0.2)
# → Linear(64) + ReLU → Output(1, regression)
_DEFAULT_SPEC: dict = {
    "version": "1.0",
    "nodes": [
        {"id": "input_0",  "type": "Input",   "params": {"features": 512},                          "position": {"x": 0,   "y": 0}},
        {"id": "linear_0", "type": "Linear",  "params": {"in_features": 512, "out_features": 256},  "position": {"x": 200, "y": 0}},
        {"id": "relu_0",   "type": "ReLU",    "params": {},                                          "position": {"x": 350, "y": 0}},
        {"id": "drop_0",   "type": "Dropout", "params": {"p": 0.2},                                  "position": {"x": 450, "y": 0}},
        {"id": "linear_1", "type": "Linear",  "params": {"in_features": 256, "out_features": 128},  "position": {"x": 600, "y": 0}},
        {"id": "relu_1",   "type": "ReLU",    "params": {},                                          "position": {"x": 750, "y": 0}},
        {"id": "drop_1",   "type": "Dropout", "params": {"p": 0.2},                                  "position": {"x": 850, "y": 0}},
        {"id": "linear_2", "type": "Linear",  "params": {"in_features": 128, "out_features": 64},   "position": {"x": 1000, "y": 0}},
        {"id": "relu_2",   "type": "ReLU",    "params": {},                                          "position": {"x": 1150, "y": 0}},
        {"id": "output_0", "type": "Output",  "params": {"out_features": 1, "task": "regression"},  "position": {"x": 1300, "y": 0}},
    ],
    "edges": [
        {"id": "e0", "source": "input_0",  "target": "linear_0"},
        {"id": "e1", "source": "linear_0", "target": "relu_0"},
        {"id": "e2", "source": "relu_0",   "target": "drop_0"},
        {"id": "e3", "source": "drop_0",   "target": "linear_1"},
        {"id": "e4", "source": "linear_1", "target": "relu_1"},
        {"id": "e5", "source": "relu_1",   "target": "drop_1"},
        {"id": "e6", "source": "drop_1",   "target": "linear_2"},
        {"id": "e7", "source": "linear_2", "target": "relu_2"},
        {"id": "e8", "source": "relu_2",   "target": "output_0"},
    ],
}


def _patch_input_dim(spec: dict, in_dim: int) -> dict:
    """Adjust Input node features to match actual embedding dimension."""
    import copy
    spec = copy.deepcopy(spec)
    for node in spec.get("nodes", []):
        if node.get("type") in ("Input", "Input3D"):
            node.setdefault("params", {})["features"] = in_dim
            # Also fix first Linear's in_features if it was auto-derived
        if node.get("type") == "Linear":
            ups = [e["source"] for e in spec.get("edges", []) if e["target"] == node["id"]]
            if ups:
                up_type = next((n["type"] for n in spec["nodes"] if n["id"] == ups[0]), "")
                if up_type in ("Input", "Input3D", "UpstreamInput"):
                    node.setdefault("params", {})["in_features"] = in_dim
    return spec


# ── Committee training ────────────────────────────────────────────────────────

def _train_member(
    spec: dict,
    X: torch.Tensor,
    y: torch.Tensor,
    epochs: int,
    lr: float,
    batch_size: int,
    seed: int,
) -> DynamicDNN:
    torch.manual_seed(seed)
    model = DynamicDNN(spec)
    optimizer = optim.Adam(model.parameters(), lr=lr)
    criterion = nn.MSELoss()
    n = len(X)
    model.train()
    for _ in range(epochs):
        idx = torch.randperm(n)
        for start in range(0, n, batch_size):
            b = idx[start : start + batch_size]
            optimizer.zero_grad()
            out = model(X[b])
            loss = criterion(out.squeeze(-1), y[b])
            loss.backward()
            optimizer.step()
    model.eval()
    return model


def _train_committee(
    spec: dict,
    X: np.ndarray,
    y: np.ndarray,
    n_committee: int,
    epochs: int,
    lr: float,
    batch_size: int,
    rng: np.random.RandomState,
) -> list[DynamicDNN]:
    n = len(X)
    members: list[DynamicDNN] = []
    for m in range(n_committee):
        boot_idx = rng.choice(n, size=n, replace=True)
        X_b = torch.tensor(X[boot_idx], dtype=torch.float32)
        y_b = torch.tensor(y[boot_idx], dtype=torch.float32)
        member = _train_member(spec, X_b, y_b, epochs, lr, batch_size, seed=m * 31 + 7)
        members.append(member)
    return members


@torch.no_grad()
def _committee_predict(members: list[DynamicDNN], X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    Xt = torch.tensor(X, dtype=torch.float32)
    preds = np.array([m(Xt).squeeze(-1).numpy() for m in members])
    return preds.mean(axis=0), preds.std(axis=0)


# ── CV RMSE ───────────────────────────────────────────────────────────────────

def _cv_rmse(spec: dict, X: np.ndarray, y: np.ndarray, epochs: int, lr: float, batch_size: int) -> float | None:
    n = len(X)
    if n < 4:
        return None
    fold = max(2, min(3, n // 2))
    idx = np.arange(n)
    np.random.seed(42)
    np.random.shuffle(idx)
    splits = np.array_split(idx, fold)
    rmses = []
    for i in range(fold):
        val_idx = splits[i]
        tr_idx = np.concatenate([splits[j] for j in range(fold) if j != i])
        X_tr, y_tr = X[tr_idx], y[tr_idx]
        X_val, y_val = X[val_idx], y[val_idx]
        member = _train_member(
            spec,
            torch.tensor(X_tr, dtype=torch.float32),
            torch.tensor(y_tr, dtype=torch.float32),
            max(20, epochs // 3), lr, batch_size, seed=i,
        )
        with torch.no_grad():
            pred = member(torch.tensor(X_val, dtype=torch.float32)).squeeze(-1).numpy()
        rmses.append(float(np.sqrt(np.mean((pred - y_val) ** 2))))
    return float(np.mean(rmses))


# ── Merge helper ──────────────────────────────────────────────────────────────

def _merge_datasets(*sources: dict) -> tuple[dict[str, list[float]], dict[str, dict[str, float]]]:
    """Merge data sources, later sources overwrite earlier for same seq_id."""
    merged_emb: dict[str, list[float]] = {}
    merged_scores: dict[str, dict[str, float]] = {
        k: {} for k in ["scores_rank_1", "scores_rank_2", "scores_rank_3", "scores_rank_4"]
    }
    for src in sources:
        if not src:
            continue
        merged_emb.update(src.get("embeddings") or {})
        for rk in merged_scores:
            merged_scores[rk].update(src.get(rk) or {})
    return merged_emb, merged_scores


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    inp = json.loads(sys.stdin.read())

    # ── Architecture ──────────────────────────────────────────────────────────
    arch_spec = inp.get("architecture_spec") or _DEFAULT_SPEC
    # Pull spec from a saved artifact if in inference mode
    model_artifact_in = inp.get("model_artifact")
    if model_artifact_in and not inp.get("architecture_spec"):
        arch_spec = model_artifact_in.get("architecture_spec") or arch_spec

    # ── Hyperparameters ───────────────────────────────────────────────────────
    n_committee = int(inp.get("n_committee", 5))
    epochs      = int(inp.get("epochs", 150))
    lr          = float(inp.get("lr", 5e-4))
    batch_size  = int(inp.get("batch_size", 128))
    kappa_epi   = float(inp.get("kappa_epi", 2.0))
    kappa_conf  = float(inp.get("kappa_conf", 0.5))
    top_k       = int(inp.get("top_k", 20))
    lower_is_better = bool(inp.get("lower_is_better", True))
    rank_weights_raw = inp.get("rank_weights")

    # ── Merge data sources ────────────────────────────────────────────────────
    pretrain    = inp.get("pretrain_dataset") or {}
    accumulated = inp.get("accumulated_dataset") or {}
    current: dict[str, Any] = {
        "embeddings": inp.get("embeddings") or {},
        **{k: inp[k] for k in ["scores_rank_1","scores_rank_2","scores_rank_3","scores_rank_4"] if inp.get(k)},
    }
    embeddings, scores_by_rank_all = _merge_datasets(pretrain, accumulated, current)
    scores_by_rank = {k: v for k, v in scores_by_rank_all.items() if v}

    n_pretrain = len(pretrain.get("embeddings") or {})
    n_acc      = len(accumulated.get("embeddings") or {})
    n_cur      = len(inp.get("embeddings") or {})
    print(
        f"Dataset: {n_pretrain} pretrain + {n_acc} accumulated + {n_cur} current = {len(embeddings)} total",
        file=sys.stderr,
    )

    # ── Candidate set ─────────────────────────────────────────────────────────
    candidate_emb = inp.get("candidate_embeddings")
    if candidate_emb and isinstance(candidate_emb, dict):
        score_ids = list(candidate_emb.keys())
        eval_emb  = candidate_emb
    elif embeddings:
        score_ids = list(embeddings.keys())
        eval_emb  = embeddings
    else:
        print(json.dumps({"error": "No embeddings or candidate_embeddings provided"}))
        sys.exit(1)

    rank_names = list(scores_by_rank.keys())
    n_ranks    = len(rank_names)
    w = (
        np.array(rank_weights_raw[:n_ranks], dtype=float)
        if rank_weights_raw and len(rank_weights_raw) >= n_ranks
        else np.ones(max(n_ranks, 1), dtype=float)
    )
    w = w / w.sum()

    # ── Load saved artifact (inference only) ──────────────────────────────────
    if model_artifact_in is not None:
        print("Loading pre-trained DNN committee artifact…", file=sys.stderr)
        committees: dict[str, list[DynamicDNN]] = {}
        in_dim_saved = int(model_artifact_in.get("in_dim", 512))
        saved_spec = _patch_input_dim(arch_spec, in_dim_saved)
        kappa_epi  = float(model_artifact_in.get("kappa_epi", kappa_epi))
        kappa_conf = float(model_artifact_in.get("kappa_conf", kappa_conf))

        for rname, state_dicts_b64 in (model_artifact_in.get("committees") or {}).items():
            members: list[DynamicDNN] = []
            for sd_b64 in state_dicts_b64:
                m = DynamicDNN(saved_spec)
                buf = io.BytesIO(base64.b64decode(sd_b64))
                m.load_state_dict(torch.load(buf, map_location="cpu", weights_only=True), strict=False)
                m.eval()
                members.append(m)
            committees[rname] = members

        rank_names = list(committees.keys())
        n_ranks    = len(rank_names)
        w          = np.ones(n_ranks) / n_ranks
        in_dim_used = in_dim_saved

    else:
        # ── Training ──────────────────────────────────────────────────────────
        if not embeddings:
            print(json.dumps({"error": "embeddings (or model_artifact) is required"}))
            sys.exit(1)
        if not scores_by_rank:
            print(json.dumps({"error": "scores_rank_1 is required for training"}))
            sys.exit(1)

        in_dim_used = len(next(iter(embeddings.values())))
        patched_spec = _patch_input_dim(arch_spec, in_dim_used)
        n_params = sum(p.numel() for p in DynamicDNN(patched_spec).parameters() if p.requires_grad)

        print(
            f"DNN-MLDE: {n_ranks} rank(s), M={n_committee}, in_dim={in_dim_used}, "
            f"params={n_params:,}, epochs={epochs}",
            file=sys.stderr,
        )

        rng = np.random.RandomState(42)
        committees = {}
        metrics_per_rank: dict[str, Any] = {}

        for rname in rank_names:
            scores = scores_by_rank[rname]
            common_ids = [sid for sid in embeddings if sid in scores]
            if not common_ids:
                print(f"  {rname}: no overlap — skipping", file=sys.stderr)
                continue

            X = np.array([embeddings[sid] for sid in common_ids], dtype=float)
            y_raw = np.array([scores[sid] for sid in common_ids], dtype=float)
            y = -y_raw if lower_is_better else y_raw

            print(f"  Training {rname}: n={len(common_ids)}", file=sys.stderr)
            cv = _cv_rmse(patched_spec, X, y, epochs, lr, batch_size)
            members = _train_committee(patched_spec, X, y, n_committee, epochs, lr, batch_size, rng)
            committees[rname] = members
            metrics_per_rank[rname] = {"n_train": len(common_ids), "cv_rmse": cv}
            print(f"  {rname}: done (cv_rmse={cv:.4f})" if cv else f"  {rname}: done", file=sys.stderr)

        rank_names = list(committees.keys())
        n_ranks    = len(rank_names)
        if n_ranks == 0:
            print(json.dumps({"error": "No valid ranks trained — check embeddings/scores overlap"}))
            sys.exit(1)
        w = np.ones(n_ranks) / n_ranks

    # ── Score candidates ──────────────────────────────────────────────────────
    print(f"Scoring {len(score_ids)} candidates…", file=sys.stderr)
    X_cand = np.array([eval_emb[sid] for sid in score_ids], dtype=float)

    per_rank_mean: dict[str, np.ndarray] = {}
    per_rank_std:  dict[str, np.ndarray] = {}
    for rname in rank_names:
        mu, sigma = _committee_predict(committees[rname], X_cand)
        per_rank_mean[rname] = mu
        per_rank_std[rname]  = sigma

    # ── RCC aggregation ───────────────────────────────────────────────────────
    mu_bar     = sum(w[i] * per_rank_mean[rn] for i, rn in enumerate(rank_names))
    sigma_epi  = np.sqrt(sum(w[i] * per_rank_std[rn] ** 2 for i, rn in enumerate(rank_names)))
    sigma_conf = np.sqrt(sum(w[i] * (per_rank_mean[rn] - mu_bar) ** 2 for i, rn in enumerate(rank_names)))
    alpha      = mu_bar + kappa_epi * sigma_epi - kappa_conf * sigma_conf

    acquisition_scores = {sid: float(alpha[i])         for i, sid in enumerate(score_ids)}
    mean_predictions   = {sid: float(mu_bar[i])        for i, sid in enumerate(score_ids)}
    epis_unc           = {sid: float(sigma_epi[i])     for i, sid in enumerate(score_ids)}
    conf_unc           = {sid: float(sigma_conf[i])    for i, sid in enumerate(score_ids)}

    top_k_actual  = min(top_k, len(score_ids))
    top_sequences = sorted(acquisition_scores, key=lambda x: acquisition_scores[x], reverse=True)[:top_k_actual]

    rank_predictions = {
        rn: {sid: {"mean": float(per_rank_mean[rn][i]), "std": float(per_rank_std[rn][i])}
             for i, sid in enumerate(score_ids)}
        for rn in rank_names
    }

    # ── Serialize committee state dicts ───────────────────────────────────────
    if model_artifact_in is None:
        committees_serial: dict[str, list[str]] = {}
        for rn, mlist in committees.items():
            sds: list[str] = []
            for m in mlist:
                buf = io.BytesIO()
                torch.save(m.state_dict(), buf)
                sds.append(base64.b64encode(buf.getvalue()).decode())
            committees_serial[rn] = sds
    else:
        committees_serial = model_artifact_in.get("committees") or {}

    artifact: dict[str, Any] = {
        "architecture_spec": arch_spec,
        "committees":        committees_serial,
        "rank_names":        rank_names,
        "in_dim":            in_dim_used,
        "kappa_epi":         kappa_epi,
        "kappa_conf":        kappa_conf,
    }

    summary_metrics: dict[str, Any] = {
        "n_ranks": n_ranks, "rank_names": rank_names,
        "n_committee": n_committee, "model_type": "dnn",
        "epochs": epochs, "lr": lr, "in_dim": in_dim_used,
        "kappa_epi": kappa_epi, "kappa_conf": kappa_conf,
        "n_candidates": len(score_ids), "top_k": top_k_actual,
        "n_pretrain": n_pretrain, "n_accumulated": n_acc, "n_current": n_cur,
    }
    if model_artifact_in is None:
        summary_metrics["per_rank"] = metrics_per_rank

    best = top_sequences[0] if top_sequences else None
    print(f"Done — top: {best} (α={acquisition_scores.get(best, 0):.4f})", file=sys.stderr)

    print(json.dumps({
        "acquisition_scores":         acquisition_scores,
        "top_sequences":              top_sequences,
        "mean_predictions":           mean_predictions,
        "epistemic_uncertainty":      epis_unc,
        "conformational_uncertainty": conf_unc,
        "rank_predictions":           rank_predictions,
        "model_artifact":             artifact,
        "metrics":                    summary_metrics,
    }))


if __name__ == "__main__":
    main()
