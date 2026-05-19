"""RCC-MLDE: Rank-Conditioned Committee for ML-Assisted Directed Evolution.

Reads JSON from stdin, writes JSON to stdout.
Progress lines go to stderr (forwarded live by subprocess_runner).

Algorithm (Presnyakov et al. 2025, arXiv:2510.24974):
  1. For each rank r, train M committee members on bootstrap resamples of D^(r)_n
  2. Predict μ̂_r(x) and σ²_epi,r(x) (within-rank variance) per candidate
  3. Rank-weighted aggregation:
       μ̄(x)      = Σ_r w_r · μ̂_r(x)
       σ²_epi(x)  = Σ_r w_r · σ²_epi,r(x)
       σ²_conf(x) = Σ_r w_r · (μ̂_r(x) − μ̄(x))²
  4. Acquisition: α(x) = μ̄ + κ_epi·σ_epi − κ_conf·σ_conf
"""
from __future__ import annotations

import base64
import json
import pickle
import sys
from typing import Any

import numpy as np


# ── Model builders ────────────────────────────────────────────────────────────

def _build_model(model_type: str, task: str):
    from sklearn.linear_model import Ridge, LogisticRegression
    from sklearn.neural_network import MLPRegressor, MLPClassifier
    from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline

    if task == "binary_classification":
        base = {
            "ridge": LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs"),
            "dnn":   MLPClassifier(hidden_layer_sizes=(128, 64), max_iter=400, random_state=0),
            "gbm":   HistGradientBoostingClassifier(max_iter=200, random_state=0),
        }[model_type]
    else:
        base = {
            "ridge": Ridge(alpha=1.0),
            "dnn":   MLPRegressor(hidden_layer_sizes=(128, 64), max_iter=400, random_state=0),
            "gbm":   HistGradientBoostingRegressor(max_iter=200, random_state=0),
        }[model_type]

    if model_type != "gbm":
        return Pipeline([("scaler", StandardScaler()), ("model", base)])
    return base


# ── Committee training for one rank ───────────────────────────────────────────

def _train_committee(
    X: np.ndarray,
    y: np.ndarray,
    n_committee: int,
    model_type: str,
    task: str,
    rng: np.random.RandomState,
) -> list[Any]:
    """Bootstrap M committee members for one rank."""
    n = len(X)
    members = []
    for _ in range(n_committee):
        idx = rng.choice(n, size=n, replace=True)
        X_b, y_b = X[idx], y[idx]
        clf = _build_model(model_type, task)
        clf.fit(X_b, y_b)
        members.append(clf)
    return members


def _committee_predict(members: list[Any], X: np.ndarray, task: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (mean, std) across committee for each sample."""
    if task == "binary_classification":
        preds = np.array([m.predict_proba(X)[:, 1] for m in members])
    else:
        preds = np.array([m.predict(X) for m in members])
    return preds.mean(axis=0), preds.std(axis=0)


# ── Cross-val RMSE helper ─────────────────────────────────────────────────────

def _cv_rmse(X: np.ndarray, y: np.ndarray, model_type: str, task: str) -> float | None:
    n = len(X)
    if n < 4:
        return None
    from sklearn.model_selection import cross_val_score
    model = _build_model(model_type, task)
    if task == "binary_classification":
        scores = cross_val_score(model, X, y, cv=min(3, n), scoring="roc_auc", error_score=0.0)
        return float(scores.mean())
    scores = cross_val_score(model, X, y, cv=min(3, n), scoring="neg_root_mean_squared_error", error_score=0.0)
    return float(-scores.mean())


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    inp = json.loads(sys.stdin.read())

    embeddings: dict[str, list[float]] = inp.get("embeddings") or {}
    candidate_emb: dict[str, list[float]] = inp.get("candidate_embeddings") or {}
    model_artifact_in: dict | None = inp.get("model_artifact")
    accumulated: dict = inp.get("accumulated_dataset") or {}

    # ── Merge accumulated dataset from previous loop iterations ──────────────
    # accumulated_dataset = {"embeddings": {seq_id: vec}, "scores_rank_1": {seq_id: float}, ...}
    if accumulated:
        acc_emb = accumulated.get("embeddings") or {}
        # Previous rounds go first; current round overwrites if same seq_id
        merged_emb: dict[str, list[float]] = {**acc_emb}
        merged_emb.update(embeddings)
        embeddings = merged_emb
        n_acc = len(acc_emb)
        n_cur = len(inp.get("embeddings") or {})
        print(f"Dataset: {n_acc} accumulated + {n_cur} current = {len(embeddings)} total sequences", file=sys.stderr)

    scores_by_rank: dict[str, dict[str, float]] = {}
    for k in ["scores_rank_1", "scores_rank_2", "scores_rank_3", "scores_rank_4"]:
        # Merge accumulated scores for this rank
        acc_scores: dict[str, float] = accumulated.get(f"scores_{k.replace('scores_', '')}") or {}
        raw = inp.get(k)
        cur_scores: dict[str, float] = {}
        if raw:
            if isinstance(raw, dict):
                cur_scores = raw
            else:
                print(f"Warning: {k} is not a dict, skipping", file=sys.stderr)
        merged = {**acc_scores, **cur_scores}  # current overwrites accumulated for same seq
        if merged:
            scores_by_rank[k] = merged

    n_committee   = int(inp.get("n_committee", 5))
    model_type    = str(inp.get("model_type", "ridge"))
    kappa_epi     = float(inp.get("kappa_epi", 2.0))
    kappa_conf    = float(inp.get("kappa_conf", 0.5))
    top_k         = int(inp.get("top_k", 20))
    lower_is_better = bool(inp.get("lower_is_better", True))
    task          = str(inp.get("task", "regression"))
    rank_weights_raw = inp.get("rank_weights")

    if not embeddings and model_artifact_in is None:
        print(json.dumps({"error": "embeddings (or model_artifact) is required"}))
        sys.exit(1)

    if not scores_by_rank and model_artifact_in is None:
        print(json.dumps({"error": "scores_rank_1 is required for training"}))
        sys.exit(1)

    rng = np.random.RandomState(42)

    # ── Determine candidate set ───────────────────────────────────────────────
    if candidate_emb:
        score_ids = list(candidate_emb.keys())
        eval_emb = candidate_emb
    elif embeddings:
        score_ids = list(embeddings.keys())
        eval_emb = embeddings
    else:
        print(json.dumps({"error": "No embeddings or candidate_embeddings provided"}))
        sys.exit(1)

    rank_names = list(scores_by_rank.keys())
    n_ranks = len(rank_names)

    # ── Rank weights ─────────────────────────────────────────────────────────
    if rank_weights_raw and len(rank_weights_raw) >= n_ranks:
        w = np.array(rank_weights_raw[:n_ranks], dtype=float)
    else:
        w = np.ones(n_ranks, dtype=float)
    w = w / w.sum()

    # ── INFERENCE from saved artifact (skip training) ─────────────────────────
    if model_artifact_in is not None:
        print("Loading pre-trained committee artifact…", file=sys.stderr)
        committees = {}
        for rname, b64 in model_artifact_in.get("committees", {}).items():
            committees[rname] = pickle.loads(base64.b64decode(b64))
        rank_names = list(committees.keys())
        n_ranks = len(rank_names)
        w = np.ones(n_ranks) / n_ranks
        kappa_epi  = float(model_artifact_in.get("kappa_epi",  kappa_epi))
        kappa_conf = float(model_artifact_in.get("kappa_conf", kappa_conf))
    else:
        # ── Build training matrix ─────────────────────────────────────────────
        print(f"RCC-MLDE: {n_ranks} rank(s), {n_committee} committee members, model={model_type}", file=sys.stderr)

        committees: dict[str, list] = {}
        metrics_per_rank: dict[str, Any] = {}

        for rname in rank_names:
            scores = scores_by_rank[rname]
            common_ids = [sid for sid in embeddings if sid in scores]
            if not common_ids:
                print(f"  Rank {rname}: no overlapping sequences between embeddings and scores — skipping", file=sys.stderr)
                continue

            X = np.array([embeddings[sid] for sid in common_ids], dtype=float)
            y_raw = np.array([scores[sid] for sid in common_ids], dtype=float)
            y = -y_raw if lower_is_better else y_raw

            print(f"  Training rank {rname}: n={len(common_ids)}, dim={X.shape[1]}", file=sys.stderr)
            cv_metric = _cv_rmse(X, y, model_type, task)
            members = _train_committee(X, y, n_committee, model_type, task, rng)
            committees[rname] = members
            metrics_per_rank[rname] = {
                "n_train": len(common_ids),
                "cv_metric": cv_metric,
            }
            print(f"  Rank {rname}: done (cv={cv_metric:.4f})" if cv_metric else f"  Rank {rname}: done", file=sys.stderr)

        rank_names = list(committees.keys())
        n_ranks = len(rank_names)
        if n_ranks == 0:
            print(json.dumps({"error": "No valid ranks could be trained (check embeddings/scores overlap)"}))
            sys.exit(1)
        # recompute weights for actually-trained ranks
        w = np.ones(n_ranks) / n_ranks

    # ── Scoring candidates ───────────────────────────────────────────────────
    print(f"Scoring {len(score_ids)} candidates…", file=sys.stderr)
    X_cand = np.array([eval_emb[sid] for sid in score_ids], dtype=float)

    per_rank_mean = {}
    per_rank_std  = {}
    for rname in rank_names:
        mu, sigma = _committee_predict(committees[rname], X_cand, task)
        per_rank_mean[rname] = mu
        per_rank_std[rname]  = sigma

    # ── RCC aggregation ───────────────────────────────────────────────────────
    mu_bar   = sum(w[i] * per_rank_mean[rname] for i, rname in enumerate(rank_names))
    sigma_epi  = np.sqrt(sum(w[i] * per_rank_std[rname]**2 for i, rname in enumerate(rank_names)))
    sigma_conf = np.sqrt(sum(w[i] * (per_rank_mean[rname] - mu_bar)**2 for i, rname in enumerate(rank_names)))

    alpha = mu_bar + kappa_epi * sigma_epi - kappa_conf * sigma_conf

    # ── Build outputs ─────────────────────────────────────────────────────────
    acquisition_scores = {sid: float(alpha[i]) for i, sid in enumerate(score_ids)}
    mean_predictions   = {sid: float(mu_bar[i]) for i, sid in enumerate(score_ids)}
    epis_unc   = {sid: float(sigma_epi[i])  for i, sid in enumerate(score_ids)}
    conf_unc   = {sid: float(sigma_conf[i]) for i, sid in enumerate(score_ids)}

    top_k_actual = min(top_k, len(score_ids))
    top_sequences = sorted(acquisition_scores, key=lambda x: acquisition_scores[x], reverse=True)[:top_k_actual]

    rank_predictions = {}
    for rname in rank_names:
        rank_predictions[rname] = {
            sid: {"mean": float(per_rank_mean[rname][i]), "std": float(per_rank_std[rname][i])}
            for i, sid in enumerate(score_ids)
        }

    # Serialize committees
    committees_b64 = {
        rname: base64.b64encode(pickle.dumps(members)).decode()
        for rname, members in committees.items()
    }
    artifact = {
        "committees": committees_b64,
        "rank_names": rank_names,
        "kappa_epi":  kappa_epi,
        "kappa_conf": kappa_conf,
        "model_type": model_type,
        "task":       task,
    }

    summary_metrics: dict[str, Any] = {
        "n_ranks": n_ranks,
        "rank_names": rank_names,
        "n_committee": n_committee,
        "model_type": model_type,
        "kappa_epi": kappa_epi,
        "kappa_conf": kappa_conf,
        "n_candidates": len(score_ids),
        "top_k": top_k_actual,
    }
    if not model_artifact_in:
        summary_metrics["per_rank"] = metrics_per_rank

    best = top_sequences[0] if top_sequences else None
    print(f"Done — top candidate: {best} (α={acquisition_scores.get(best, 0):.4f})", file=sys.stderr)

    print(json.dumps({
        "acquisition_scores":       acquisition_scores,
        "top_sequences":            top_sequences,
        "mean_predictions":         mean_predictions,
        "epistemic_uncertainty":    epis_unc,
        "conformational_uncertainty": conf_unc,
        "rank_predictions":         rank_predictions,
        "model_artifact":           artifact,
        "metrics":                  summary_metrics,
    }))


if __name__ == "__main__":
    main()
