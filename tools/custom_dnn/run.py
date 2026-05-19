"""Custom DNN runner.

Reads inputs from stdin as JSON, builds a PyTorch model from architecture_spec
(produced by the DNN Designer), embeds sequences with ESM-2, trains on
sequences + labels, and returns predictions and metrics.

ESM-2 model sizes and embedding dimensions:
  8M  → 320-dim   (fastest, weights ~32 MB)
  35M → 480-dim
  150M → 640-dim
  650M → 1280-dim  (best quality, weights ~2.5 GB)
"""
from __future__ import annotations

import base64
import copy
import io
import json
import math
import random
import re
import sys
from typing import Any

import os
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

# ─── ESM-2 model name map ─────────────────────────────────────────────────────

_ESM2_MODELS = {
    "8M":   ("facebook/esm2_t6_8M_UR50D",   320),
    "35M":  ("facebook/esm2_t12_35M_UR50D",  480),
    "150M": ("facebook/esm2_t30_150M_UR50D", 640),
    "650M": ("facebook/esm2_t33_650M_UR50D", 1280),
}

# ─── Sequence helpers ─────────────────────────────────────────────────────────

_CANONICAL = set("ACDEFGHIKLMNPQRSTVWY")


def parse_fasta(text: str) -> list[tuple[str, str]]:
    seqs: list[tuple[str, str]] = []
    header, buf = "", []
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith(">"):
            if buf:
                seqs.append((header, "".join(buf)))
            header, buf = line[1:].split()[0] if line[1:].split() else ["seq"], []
        elif line:
            buf.append(line.upper())
    if buf:
        seqs.append((header, "".join(buf)))
    # Accept raw sequence with no FASTA header
    if not seqs and text.strip():
        raw = re.sub(r"[^A-Za-z]", "", text).upper()
        if raw:
            seqs.append(("seq_0", raw))
    return seqs


def clean_seq(seq: str) -> str:
    return "".join(aa if aa in _CANONICAL else "A" for aa in seq)


# ─── Embedding ────────────────────────────────────────────────────────────────

def embed_sequences(sequences: list[str], model_size: str) -> torch.Tensor:
    """Return mean-pooled ESM-2 embeddings: tensor of shape [N, embed_dim]."""
    model_name, embed_dim = _ESM2_MODELS[model_size]
    from transformers import EsmModel, EsmTokenizer  # type: ignore
    print(f"Loading ESM-2 {model_size} ({embed_dim}-dim)…", file=sys.stderr, flush=True)
    tokenizer = EsmTokenizer.from_pretrained(model_name)
    esm = EsmModel.from_pretrained(model_name)
    esm.eval()
    embeddings: list[torch.Tensor] = []
    with torch.no_grad():
        for i, seq in enumerate(sequences):
            tok = tokenizer(seq, return_tensors="pt", add_special_tokens=True)
            out = esm(**tok)
            # last_hidden_state: [1, L+2, dim] → strip CLS/EOS → mean pool
            hidden = out.last_hidden_state[0, 1:-1, :]   # [L, dim]
            embeddings.append(hidden.mean(dim=0))         # [dim]
            if (i + 1) % 10 == 0:
                print(f"  embedded {i+1}/{len(sequences)}", file=sys.stderr, flush=True)
    return torch.stack(embeddings)  # [N, embed_dim]


# ─── DynamicDNN: builds nn.Module from architecture_spec ─────────────────────

class DynamicDNN(nn.Module):
    def __init__(self, spec: dict[str, Any]) -> None:
        super().__init__()
        nodes: list[dict] = spec.get("nodes", [])
        edges: list[dict] = spec.get("edges", [])

        # Build adjacency structures
        self._in_adj: dict[str, list[str]] = {n["id"]: [] for n in nodes}
        out_adj: dict[str, list[str]] = {n["id"]: [] for n in nodes}
        in_deg: dict[str, int] = {n["id"]: 0 for n in nodes}

        for e in edges:
            src, tgt = e["source"], e["target"]
            if src in out_adj and tgt in in_deg:
                out_adj[src].append(tgt)
                self._in_adj[tgt].append(src)
                in_deg[tgt] += 1

        # Topological sort (Kahn)
        queue = [n["id"] for n in nodes if in_deg[n["id"]] == 0]
        self._order: list[str] = []
        deg = dict(in_deg)
        while queue:
            nid = queue.pop(0)
            self._order.append(nid)
            for nxt in out_adj[nid]:
                deg[nxt] -= 1
                if deg[nxt] == 0:
                    queue.append(nxt)

        self._node_map: dict[str, dict] = {n["id"]: n for n in nodes}

        # Instantiate parametric layers and register as submodules
        for nid in self._order:
            layer = self._make_layer(self._node_map[nid])
            if layer is not None:
                # Sanitise id for valid Python attribute name
                setattr(self, self._attr(nid), layer)

    @staticmethod
    def _attr(nid: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "_", nid)

    def _make_layer(self, node: dict) -> nn.Module | None:
        t = node["type"]
        p = node.get("params", {})

        # Functional layers — no nn.Module
        if t in ("Input", "Input3D", "UpstreamInput", "GlobalAvgPool", "GlobalMaxPool", "Residual"):
            return None

        if t == "Linear":
            return nn.Linear(int(p["in_features"]), int(p["out_features"]),
                             bias=bool(p.get("bias", True)))

        if t == "Output":
            # Infer in_features from the upstream node output shape
            in_f = self._upstream_out_dim(node)
            return nn.Linear(in_f, int(p.get("out_features", 1)))

        if t == "Conv1d":
            return nn.Conv1d(int(p["in_channels"]), int(p["out_channels"]),
                             kernel_size=int(p.get("kernel_size", 3)),
                             stride=int(p.get("stride", 1)),
                             padding=int(p.get("padding", 0)))

        if t == "LSTM":
            return nn.LSTM(int(p["input_size"]), int(p["hidden_size"]),
                           num_layers=int(p.get("num_layers", 1)),
                           bidirectional=bool(p.get("bidirectional", False)),
                           dropout=float(p.get("dropout", 0.0)),
                           batch_first=True)

        if t == "GRU":
            return nn.GRU(int(p["input_size"]), int(p["hidden_size"]),
                          num_layers=int(p.get("num_layers", 1)),
                          bidirectional=bool(p.get("bidirectional", False)),
                          dropout=float(p.get("dropout", 0.0)),
                          batch_first=True)

        if t == "MultiheadAttention":
            return nn.MultiheadAttention(int(p["embed_dim"]), int(p["num_heads"]),
                                         dropout=float(p.get("dropout", 0.0)),
                                         batch_first=True)

        if t == "TransformerEncoder":
            enc = nn.TransformerEncoderLayer(
                d_model=int(p["d_model"]), nhead=int(p["nhead"]),
                dim_feedforward=int(p.get("dim_feedforward", 256)),
                dropout=float(p.get("dropout", 0.1)), batch_first=True)
            return nn.TransformerEncoder(enc, num_layers=int(p.get("num_layers", 1)))

        if t == "ReLU":        return nn.ReLU()
        if t == "GELU":        return nn.GELU()
        if t == "Sigmoid":     return nn.Sigmoid()
        if t == "Tanh":        return nn.Tanh()
        if t == "Softmax":     return nn.Softmax(dim=int(p.get("dim", -1)))
        if t == "BatchNorm1d": return nn.BatchNorm1d(int(p["num_features"]),
                                                     eps=float(p.get("eps", 1e-5)),
                                                     momentum=float(p.get("momentum", 0.1)))
        if t == "LayerNorm":   return nn.LayerNorm(int(p["normalized_shape"]))
        if t == "Dropout":     return nn.Dropout(p=float(p.get("p", 0.5)))
        if t == "Flatten":     return nn.Flatten()
        return None

    def _upstream_out_dim(self, node: dict) -> int:
        """Walk upstream to find the last feature dimension for the Output linear layer."""
        def _dim_of(nid: str) -> int:
            n = self._node_map.get(nid, {})
            t = n.get("type", "")
            p = n.get("params", {})
            if t == "Linear":        return int(p.get("out_features", 1))
            if t in ("LSTM", "GRU"):
                dirs = 2 if p.get("bidirectional") else 1
                return int(p.get("hidden_size", 1)) * dirs
            if t in ("Input", "Input3D"):     return int(p.get("features", 320))
            if t in ("GlobalAvgPool", "GlobalMaxPool"):
                ups = self._in_adj.get(nid, [])
                return _dim_of(ups[0]) if ups else 320
            if t == "BatchNorm1d": return int(p.get("num_features", 1))
            if t == "LayerNorm":   return int(p.get("normalized_shape", 1))
            # Passthrough (activations, dropout, etc.) — recurse
            ups = self._in_adj.get(nid, [])
            return _dim_of(ups[0]) if ups else 320
        ups = self._in_adj.get(node["id"], [])
        return _dim_of(ups[0]) if ups else 320

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        vals: dict[str, torch.Tensor] = {}

        for nid in self._order:
            node = self._node_map[nid]
            t = node["type"]
            p = node.get("params", {})
            ups = self._in_adj.get(nid, [])

            if t in ("Input", "Input3D"):
                vals[nid] = x
                continue

            if t == "UpstreamInput":
                start = int(p.get("slice_start", 0))
                end   = int(p.get("slice_end", x.shape[-1]))
                vals[nid] = x[:, start:end]
                continue

            # Gather inputs from upstream
            available = [vals[u] for u in ups if u in vals]
            if not available:
                continue  # disconnected

            if t == "Residual":
                inp = sum(available) if len(available) > 1 else available[0]  # type: ignore[arg-type]
            elif len(available) > 1:
                inp = torch.cat(available, dim=-1)
            else:
                inp = available[0]

            attr = self._attr(nid)
            layer: nn.Module | None = getattr(self, attr, None)

            if t == "GlobalAvgPool":
                out = inp.mean(dim=1)
            elif t == "GlobalMaxPool":
                out = inp.max(dim=1).values
            elif t == "Residual":
                out = inp
            elif t in ("LSTM", "GRU") and layer is not None:
                raw, _ = layer(inp)
                out = raw[:, -1, :] if p.get("return_last") else raw
            elif t == "MultiheadAttention" and layer is not None:
                out, _ = layer(inp, inp, inp)
            elif layer is not None:
                out = layer(inp)
            else:
                out = inp

            vals[nid] = out

        # Return the last computed value in topological order
        for nid in reversed(self._order):
            if nid in vals and self._node_map[nid]["type"] not in ("Input", "Input3D"):
                return vals[nid]
        return x


# ─── Committee / ML-DE mode ──────────────────────────────────────────────────

def _patch_input_dim(spec: dict, in_dim: int) -> dict:
    spec = copy.deepcopy(spec)
    for node in spec.get("nodes", []):
        if node.get("type") in ("Input", "Input3D"):
            node.setdefault("params", {})["features"] = in_dim
        if node.get("type") == "Linear":
            ups = [e["source"] for e in spec.get("edges", []) if e["target"] == node["id"]]
            if ups:
                up_type = next((n["type"] for n in spec["nodes"] if n["id"] == ups[0]), "")
                if up_type in ("Input", "Input3D", "UpstreamInput"):
                    node.setdefault("params", {})["in_features"] = in_dim
    return spec


def _train_committee_member(
    spec: dict, X: torch.Tensor, y: torch.Tensor,
    epochs: int, lr: float, batch_size: int, seed: int,
) -> "DynamicDNN":
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
            loss = criterion(model(X[b]).squeeze(-1), y[b])
            loss.backward()
            optimizer.step()
    model.eval()
    return model


@torch.no_grad()
def _committee_predict(members: list, X_np: np.ndarray) -> tuple:
    Xt = torch.tensor(X_np, dtype=torch.float32)
    preds = np.array([m(Xt).squeeze(-1).numpy() for m in members])
    return preds.mean(axis=0), preds.std(axis=0)


def _run_committee_mode(inputs: dict[str, Any], arch_spec: dict) -> None:
    """Bootstrap committee ensemble with RCC acquisition — identical to dnn_mlde."""
    n_committee     = int(inputs.get("n_committee", 5))
    epochs          = int(inputs.get("epochs", 150))
    lr              = float(inputs.get("learning_rate", inputs.get("lr", 5e-4)))
    batch_size      = int(inputs.get("batch_size", 128))
    kappa_epi       = float(inputs.get("kappa_epi", 2.0))
    kappa_conf      = float(inputs.get("kappa_conf", 0.5))
    top_k           = int(inputs.get("top_k", 20))
    lower_is_better = bool(inputs.get("lower_is_better", True))

    # ── Merge training data ───────────────────────────────────────────────────
    embeddings: dict[str, list[float]] = {}
    scores_by_rank: dict[str, dict[str, float]] = {}
    _rank_keys = ["scores_rank_1", "scores_rank_2", "scores_rank_3", "scores_rank_4"]

    for src in [
        inputs.get("accumulated_dataset") or {},
        {
            "embeddings": inputs.get("embeddings") or {},
            **{k: inputs[k] for k in _rank_keys if inputs.get(k)},
        },
    ]:
        embeddings.update(src.get("embeddings") or {})
        for rk in _rank_keys:
            if src.get(rk):
                scores_by_rank.setdefault(rk, {}).update(src[rk])

    # ── Candidate set ─────────────────────────────────────────────────────────
    cand_emb = inputs.get("candidate_embeddings")
    if cand_emb and isinstance(cand_emb, dict) and cand_emb:
        score_ids = list(cand_emb.keys())
        eval_emb  = cand_emb
    elif embeddings:
        score_ids = list(embeddings.keys())
        eval_emb  = embeddings
    else:
        print(json.dumps({"error": "committee_mode requires embeddings or candidate_embeddings"}))
        sys.exit(1)

    rank_names = list(scores_by_rank.keys())
    n_ranks    = len(rank_names)

    # ── Load artifact (inference) OR train ────────────────────────────────────
    model_artifact_in = inputs.get("model_artifact")
    committees: dict[str, list] = {}
    in_dim_used = 512

    if model_artifact_in and model_artifact_in.get("committees"):
        print("Loading committee from model_artifact…", file=sys.stderr)
        in_dim_used = int(model_artifact_in.get("in_dim", 512))
        kappa_epi   = float(model_artifact_in.get("kappa_epi", kappa_epi))
        kappa_conf  = float(model_artifact_in.get("kappa_conf", kappa_conf))
        saved_spec  = _patch_input_dim(arch_spec, in_dim_used)
        for rname, sds_b64 in model_artifact_in["committees"].items():
            members = []
            for sd_b64 in sds_b64:
                m = DynamicDNN(saved_spec)
                buf = io.BytesIO(base64.b64decode(sd_b64))
                m.load_state_dict(torch.load(buf, map_location="cpu", weights_only=True), strict=False)
                m.eval()
                members.append(m)
            committees[rname] = members
        rank_names = list(committees.keys())
        n_ranks    = len(rank_names)
    else:
        if not embeddings:
            print(json.dumps({"error": "committee_mode: embeddings required for training"}))
            sys.exit(1)
        if not scores_by_rank:
            print(json.dumps({"error": "committee_mode: scores_rank_1 required for training"}))
            sys.exit(1)

        in_dim_used  = len(next(iter(embeddings.values())))
        patched_spec = _patch_input_dim(arch_spec, in_dim_used)
        n_params = sum(p.numel() for p in DynamicDNN(patched_spec).parameters() if p.requires_grad)
        print(
            f"Committee DNN: M={n_committee}, ranks={n_ranks}, in_dim={in_dim_used}, "
            f"params={n_params:,}, epochs={epochs}",
            file=sys.stderr,
        )
        rng = np.random.RandomState(42)
        for rname in rank_names:
            scores = scores_by_rank[rname]
            common = [sid for sid in embeddings if sid in scores]
            if not common:
                print(f"  {rname}: no overlap — skipping", file=sys.stderr)
                continue
            X_arr = np.array([embeddings[sid] for sid in common], dtype=float)
            y_raw = np.array([scores[sid] for sid in common], dtype=float)
            y_arr = -y_raw if lower_is_better else y_raw
            print(f"  Training {rname}: n={len(common)}", file=sys.stderr)
            members = []
            for m_idx in range(n_committee):
                boot = rng.choice(len(X_arr), size=len(X_arr), replace=True)
                member = _train_committee_member(
                    patched_spec,
                    torch.tensor(X_arr[boot], dtype=torch.float32),
                    torch.tensor(y_arr[boot], dtype=torch.float32),
                    epochs, lr, batch_size, seed=m_idx * 31 + 7,
                )
                members.append(member)
            committees[rname] = members
            print(f"  {rname}: done", file=sys.stderr)

        rank_names = list(committees.keys())
        n_ranks    = len(rank_names)
        if n_ranks == 0:
            print(json.dumps({"error": "No valid ranks — check embeddings/scores overlap"}))
            sys.exit(1)

    # ── Score candidates via RCC aggregation ──────────────────────────────────
    print(f"Scoring {len(score_ids)} candidates…", file=sys.stderr)
    X_cand = np.array([eval_emb[sid] for sid in score_ids], dtype=float)
    w = np.ones(n_ranks) / n_ranks

    rank_mu:  dict[str, np.ndarray] = {}
    rank_std: dict[str, np.ndarray] = {}
    for rn in rank_names:
        mu, sigma = _committee_predict(committees[rn], X_cand)
        rank_mu[rn]  = mu
        rank_std[rn] = sigma

    mu_bar     = sum(w[i] * rank_mu[rn]  for i, rn in enumerate(rank_names))
    sigma_epi  = np.sqrt(sum(w[i] * rank_std[rn] ** 2 for i, rn in enumerate(rank_names)))
    sigma_conf = np.sqrt(sum(w[i] * (rank_mu[rn] - mu_bar) ** 2 for i, rn in enumerate(rank_names)))
    alpha      = mu_bar + kappa_epi * sigma_epi - kappa_conf * sigma_conf

    acquisition_scores = {sid: float(alpha[i])      for i, sid in enumerate(score_ids)}
    mean_preds         = {sid: float(mu_bar[i])     for i, sid in enumerate(score_ids)}
    epi_unc            = {sid: float(sigma_epi[i])  for i, sid in enumerate(score_ids)}
    conf_unc           = {sid: float(sigma_conf[i]) for i, sid in enumerate(score_ids)}
    top_sequences      = sorted(acquisition_scores, key=lambda x: acquisition_scores[x], reverse=True)[:min(top_k, len(score_ids))]

    # ── Serialize committees ──────────────────────────────────────────────────
    committees_serial: dict[str, list[str]] = {}
    for rn, mlist in committees.items():
        sds = []
        for m in mlist:
            buf = io.BytesIO()
            torch.save(m.state_dict(), buf)
            sds.append(base64.b64encode(buf.getvalue()).decode())
        committees_serial[rn] = sds

    best = top_sequences[0] if top_sequences else None
    print(f"Done — top: {best} (α={acquisition_scores.get(best, 0):.4f})", file=sys.stderr)

    json.dump({
        "acquisition_scores":         acquisition_scores,
        "top_sequences":              top_sequences,
        "mean_predictions":           mean_preds,
        "epistemic_uncertainty":      epi_unc,
        "conformational_uncertainty": conf_unc,
        "model_artifact": {
            "architecture_spec": arch_spec,
            "committees":        committees_serial,
            "rank_names":        rank_names,
            "in_dim":            in_dim_used,
            "kappa_epi":         kappa_epi,
            "kappa_conf":        kappa_conf,
        },
        "predictions": [],
        "metrics": {
            "n_ranks": n_ranks, "rank_names": rank_names,
            "n_committee": n_committee,
            "n_candidates": len(score_ids),
            "kappa_epi": kappa_epi, "kappa_conf": kappa_conf,
            "in_dim": in_dim_used,
        },
    }, sys.stdout)


# ─── Training loop ────────────────────────────────────────────────────────────

class FocalLoss(nn.Module):
    def __init__(self, gamma: float = 2.0) -> None:
        super().__init__()
        self.gamma = gamma

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        bce = nn.functional.binary_cross_entropy_with_logits(logits, targets, reduction="none")
        pt = torch.exp(-bce)
        return ((1 - pt) ** self.gamma * bce).mean()


def build_criterion(task: str, loss_fn: str) -> nn.Module:
    if loss_fn == "auto":
        if task == "regression":
            return nn.MSELoss()
        elif task == "binary_classification":
            return nn.BCEWithLogitsLoss()
        else:
            return nn.CrossEntropyLoss()
    if loss_fn == "mse":
        return nn.MSELoss()
    if loss_fn == "huber":
        return nn.HuberLoss()
    if loss_fn == "mae":
        return nn.L1Loss()
    if loss_fn == "bce":
        return nn.BCEWithLogitsLoss()
    if loss_fn == "focal":
        return FocalLoss()
    if loss_fn == "label_smoothing":
        return nn.CrossEntropyLoss(label_smoothing=0.1)
    return nn.CrossEntropyLoss()


def train_model(
    model: nn.Module,
    X: torch.Tensor,
    y: torch.Tensor,
    task: str,
    epochs: int,
    lr: float,
    loss_fn: str = "auto",
) -> list[dict]:
    criterion: nn.Module = build_criterion(task, loss_fn)

    optimizer = optim.Adam(model.parameters(), lr=lr)

    n = len(X)
    idx = list(range(n))
    random.shuffle(idx)
    split = max(1, int(0.8 * n))
    tr_idx, val_idx = idx[:split], idx[split:]
    X_tr, y_tr = X[tr_idx], y[tr_idx]
    X_val, y_val = X[val_idx], y[val_idx]

    history: list[dict] = []

    for epoch in range(1, epochs + 1):
        model.train()
        optimizer.zero_grad()
        out = model(X_tr)

        if task == "multiclass":
            loss = criterion(out, y_tr.long())
        else:
            loss = criterion(out.squeeze(-1), y_tr.float())

        loss.backward()
        optimizer.step()

        model.eval()
        with torch.no_grad():
            val_out = model(X_val)
            if task == "multiclass":
                val_loss = criterion(val_out, y_val.long()).item()
                preds = val_out.argmax(dim=-1).float()
                acc = (preds == y_val.float()).float().mean().item()
                entry: dict = {"epoch": epoch, "train_loss": round(loss.item(), 6),
                               "val_loss": round(val_loss, 6), "val_acc": round(acc, 4)}
            elif task == "binary_classification":
                val_loss = criterion(val_out.squeeze(-1), y_val.float()).item()
                preds = (val_out.squeeze(-1).sigmoid() > 0.5).float()
                acc = (preds == y_val.float()).float().mean().item()
                entry = {"epoch": epoch, "train_loss": round(loss.item(), 6),
                         "val_loss": round(val_loss, 6), "val_acc": round(acc, 4)}
            else:
                val_loss = criterion(val_out.squeeze(-1), y_val.float()).item()
                rmse = math.sqrt(max(0.0, ((val_out.squeeze(-1) - y_val.float()) ** 2).mean().item()))
                entry = {"epoch": epoch, "train_loss": round(loss.item(), 6),
                         "val_loss": round(val_loss, 6), "val_rmse": round(rmse, 6)}

        history.append(entry)
        log_every = max(1, epochs // 5)
        if epoch % log_every == 0 or epoch == epochs:
            summary = " ".join(f"{k}={v}" for k, v in entry.items() if k != "epoch")
            print(f"[{epoch}/{epochs}] {summary}", file=sys.stderr, flush=True)

    return history


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    inputs: dict[str, Any] = json.load(sys.stdin)

    # ── Committee / ML-DE branch ─────────────────────────────────────────────
    if inputs.get("committee_mode"):
        architecture_spec_cm = inputs.get("architecture_spec")
        if not architecture_spec_cm and inputs.get("model_artifact"):
            architecture_spec_cm = inputs["model_artifact"].get("architecture_spec")
        if not architecture_spec_cm:
            print(json.dumps({"error": "committee_mode requires architecture_spec. Use the DNN Designer."}))
            sys.exit(1)
        _run_committee_mode(inputs, architecture_spec_cm)
        return

    sequences_raw: str = inputs.get("sequences") or ""
    embedding_input = inputs.get("embedding_input")  # pre-computed {name: [float...]}
    labels_raw = inputs.get("labels")
    model_artifact_in = inputs.get("model_artifact")
    architecture_spec = inputs.get("architecture_spec")
    embedding_model: str = str(inputs.get("embedding_model", "8M")).strip()
    epochs: int = int(inputs.get("epochs", 50))
    lr: float = float(inputs.get("learning_rate", 0.001))
    task: str = str(inputs.get("task", "regression"))
    loss_fn: str = str(inputs.get("loss_fn", "auto")).strip()

    # In inference mode the spec lives inside model_artifact, not in node params
    if not architecture_spec and model_artifact_in:
        architecture_spec = model_artifact_in.get("architecture_spec")
    if not architecture_spec:
        print(json.dumps({"error": "architecture_spec is required. Use the DNN Designer to build one."}))
        sys.exit(1)
    # Pull task / embedding_model from model_artifact when not set at node level
    if model_artifact_in:
        if not inputs.get("task") or task == "regression":
            task = str(model_artifact_in.get("task") or task)
        if not inputs.get("embedding_model") or embedding_model == "8M":
            embedding_model = str(model_artifact_in.get("embedding_model") or embedding_model)

    if embedding_model not in _ESM2_MODELS:
        embedding_model = "8M"

    # ── Normalize embedding_input to {seq_id: [float...]} if it arrived as a list ──
    if isinstance(embedding_input, list) and len(embedding_input) > 0:
        seq_pairs_for_ids = parse_fasta(sequences_raw) if sequences_raw else []
        if isinstance(embedding_input[0], list):
            embedding_input = {
                (seq_pairs_for_ids[i][0] if i < len(seq_pairs_for_ids) else f"seq_{i}"): vec
                for i, vec in enumerate(embedding_input)
            }
        elif isinstance(embedding_input[0], (int, float)):
            sid = seq_pairs_for_ids[0][0] if seq_pairs_for_ids else "seq_0"
            embedding_input = {sid: embedding_input}

    # ── Resolve sequence IDs and embeddings ───────────────────────────────
    if embedding_input and isinstance(embedding_input, dict) and len(embedding_input) > 0:
        # Use pre-computed embeddings — skip ESM-2 entirely
        seq_ids = list(embedding_input.keys())
        vecs = [embedding_input[sid] for sid in seq_ids]
        X = torch.tensor(vecs, dtype=torch.float32)
        print(f"Using pre-computed embeddings: {len(seq_ids)} sequences, dim={X.shape[1]}", file=sys.stderr, flush=True)
    else:
        # Fall back to embedding from sequences FASTA
        seq_pairs = parse_fasta(sequences_raw)
        if not seq_pairs:
            print(json.dumps({"error": "No sequences or embeddings provided. Connect a sequence source or an embedding tool."}))
            sys.exit(1)
        seq_ids  = [p[0] for p in seq_pairs]
        seq_strs = [clean_seq(p[1]) for p in seq_pairs]
        print(f"Sequences: {len(seq_strs)}", file=sys.stderr, flush=True)
        X = embed_sequences(seq_strs, embedding_model)  # [N, dim]
        print(f"Embedding shape: {list(X.shape)}", file=sys.stderr, flush=True)

    n = len(seq_ids)
    has_labels = bool(labels_raw) and (
        (isinstance(labels_raw, dict) and len(labels_raw) > 0)
        or (isinstance(labels_raw, list) and len(labels_raw) > 0)
    )
    inference_only = model_artifact_in is not None and not has_labels

    # ── Build model ────────────────────────────────────────────────────────
    print("Building model from architecture_spec…", file=sys.stderr, flush=True)
    model = DynamicDNN(architecture_spec)

    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"Model parameters: {n_params:,}", file=sys.stderr, flush=True)

    # Load weights if doing inference from a saved artifact
    if model_artifact_in and "weights_b64" in model_artifact_in:
        buf = io.BytesIO(base64.b64decode(model_artifact_in["weights_b64"]))
        state = torch.load(buf, map_location="cpu", weights_only=True)
        model.load_state_dict(state, strict=False)
        print("Loaded weights from model_artifact.", file=sys.stderr, flush=True)

    # ── Train ─────────────────────────────────────────────────────────────
    history: list[dict] = []
    if not inference_only and labels_raw is not None:
        if isinstance(labels_raw, dict):
            y_list = [float(labels_raw.get(sid, 0.0)) for sid in seq_ids]
        else:
            y_list = [float(v) for v in labels_raw]
        if len(y_list) != n:
            print(json.dumps({"error": f"labels length {len(y_list)} != sequences count {n}"}))
            sys.exit(1)
        y = torch.tensor(y_list, dtype=torch.float32)
        print(f"Training: task={task}, loss={loss_fn}, epochs={epochs}, lr={lr}", file=sys.stderr, flush=True)
        history = train_model(model, X, y, task, epochs, lr, loss_fn)
        print("Training complete.", file=sys.stderr, flush=True)

    # ── Inference ─────────────────────────────────────────────────────────
    model.eval()
    with torch.no_grad():
        raw = model(X)  # [N, out] or [N]

    if task == "regression":
        vals = raw.squeeze(-1).tolist()
        predictions = [{"id": sid, "value": round(float(v), 6)} for sid, v in zip(seq_ids, vals)]
    elif task == "binary_classification":
        probs = raw.squeeze(-1).sigmoid().tolist()
        predictions = [{"id": sid, "prob_positive": round(float(p), 6), "label": int(float(p) > 0.5)}
                       for sid, p in zip(seq_ids, probs)]
    else:
        probs_all = raw.softmax(dim=-1).tolist()
        predictions = [
            {"id": sid, "probs": [round(float(v), 6) for v in ps],
             "label": int(max(range(len(ps)), key=lambda i: ps[i]))}
            for sid, ps in zip(seq_ids, probs_all)
        ]

    # ── Serialize weights ──────────────────────────────────────────────────
    buf = io.BytesIO()
    torch.save(model.state_dict(), buf)
    weights_b64 = base64.b64encode(buf.getvalue()).decode()

    artifact_out: dict = {
        "architecture_spec": architecture_spec,
        "embedding_model": embedding_model,
        "task": task,
        "loss_fn": loss_fn,
        "weights_b64": weights_b64,
    }

    final_metrics: dict = {}
    if history:
        final_metrics = {**history[-1], "history": history}

    json.dump({
        "model_artifact": artifact_out,
        "predictions":    predictions,
        "metrics":        final_metrics,
    }, sys.stdout)


if __name__ == "__main__":
    main()
