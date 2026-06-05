"""RL Designer — Deep Q-Network engine for informed CDR mutation selection.

State  : protein embedding (AbMAP / ESM-2 / AbLang / CHEAP)
Action : (CDR region, mutation strategy, n_mutations) — discrete triple
Reward : weighted combination of evaluation scores from downstream tools
Policy : Double DQN with experience replay and ε-greedy exploration

Integrates with the loop executor via policy_state (serialised weights +
replay buffer) which accumulates across loop iterations, mirroring the
accumulated_dataset pattern used by custom_dnn and rcc_mlde.
"""
from __future__ import annotations

import base64
import collections
import importlib.util
import io
import json
import random
import sys
from copy import deepcopy
from itertools import product
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

# ── Import DynamicDNN from custom_dnn (don't duplicate) ──────────────────────
_CUSTOM_DNN_PATH = Path(__file__).parent.parent / "custom_dnn" / "run.py"
_spec = importlib.util.spec_from_file_location("custom_dnn_run", _CUSTOM_DNN_PATH)
_cdmod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_cdmod)  # type: ignore[union-attr]
DynamicDNN = _cdmod.DynamicDNN


# ─────────────────────────────────────────────────────────────────────────────
# Action space helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_actions(spec: dict) -> list[dict]:
    """Enumerate all (cdr, strategy, n_mutations) triples from the action config."""
    ac = spec.get("action", {})
    cdrs = ac.get("cdrs") or ["H1", "H2", "H3", "L1", "L2", "L3"]
    strategies = ac.get("strategies") or ["random", "blosum62", "conservative", "sapiens"]
    n_muts = ac.get("n_mutations_choices") or [1, 2, 3]
    return [
        {"cdr": c, "strategy": s, "n_mutations": n}
        for c, s, n in product(cdrs, strategies, n_muts)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Q-Network
# ─────────────────────────────────────────────────────────────────────────────

class QNetwork(nn.Module):
    """Backbone (DynamicDNN from designer) + linear Q-head outputting |A| values."""

    def __init__(self, policy_spec: dict, state_dim: int, n_actions: int) -> None:
        super().__init__()
        self.backbone = DynamicDNN(policy_spec) if policy_spec.get("nodes") else _default_backbone(state_dim)
        hidden_dim = _infer_backbone_out_dim(policy_spec, state_dim)
        self.q_head = nn.Linear(hidden_dim, n_actions)

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # [B, D] → [B, A]
        h = self.backbone(x)
        if isinstance(h, tuple):  # LSTM/GRU return (out, hidden)
            h = h[0][:, -1, :] if h[0].dim() == 3 else h[0]
        if h.dim() == 3:
            h = h.mean(dim=1)
        return self.q_head(h)


def _default_backbone(state_dim: int) -> nn.Module:
    """Two-layer MLP used when no policy network is designed yet."""
    hidden = min(256, max(64, state_dim // 2))
    return nn.Sequential(
        nn.Linear(state_dim, hidden),
        nn.ReLU(),
        nn.Linear(hidden, hidden // 2),
        nn.ReLU(),
    )


def _infer_backbone_out_dim(policy_spec: dict, state_dim: int) -> int:
    """Walk the policy node graph to find the final output dimension."""
    nodes = policy_spec.get("nodes", [])
    if not nodes:
        return min(256, max(64, state_dim // 2)) // 2

    node_map = {n["id"]: n for n in nodes}
    # Find nodes with no outgoing edge (candidates for output)
    srcs = {e["source"] for e in policy_spec.get("edges", [])}
    terminals = [n for n in nodes if n["id"] not in srcs and n["type"] not in ("Input", "UpstreamInput", "Input3D")]
    if not terminals:
        terminals = nodes[-1:]

    def _dim(nid: str) -> int:
        n = node_map.get(nid, {})
        t = n.get("type", "")
        p = n.get("params", {})
        if t == "Linear":     return int(p.get("out_features", 128))
        if t in ("LSTM", "GRU"):
            dirs = 2 if p.get("bidirectional") else 1
            return int(p.get("hidden_size", 64)) * dirs
        if t in ("Input", "UpstreamInput"): return int(p.get("features", state_dim))
        return state_dim

    return _dim(terminals[0]["id"])


# ─────────────────────────────────────────────────────────────────────────────
# Projection MLP (optional state compression before Q-net)
# ─────────────────────────────────────────────────────────────────────────────

def _make_projection(state_dim: int, proj_dim: int) -> nn.Module | None:
    if proj_dim > 0 and proj_dim != state_dim:
        return nn.Sequential(nn.Linear(state_dim, proj_dim), nn.ReLU())
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Replay Buffer
# ─────────────────────────────────────────────────────────────────────────────

Transition = tuple[list[float], int, float, list[float], bool]


class ReplayBuffer:
    def __init__(self, capacity: int) -> None:
        self.buf: collections.deque[Transition] = collections.deque(maxlen=capacity)

    def push(self, state: list[float], action: int, reward: float,
             next_state: list[float], done: bool) -> None:
        self.buf.append((state, action, reward, next_state, done))

    def sample(self, batch_size: int) -> tuple[torch.Tensor, ...]:
        batch = random.sample(self.buf, batch_size)
        states   = torch.tensor([b[0] for b in batch], dtype=torch.float32)
        actions  = torch.tensor([b[1] for b in batch], dtype=torch.long)
        rewards  = torch.tensor([b[2] for b in batch], dtype=torch.float32)
        n_states = torch.tensor([b[3] for b in batch], dtype=torch.float32)
        dones    = torch.tensor([b[4] for b in batch], dtype=torch.float32)
        return states, actions, rewards, n_states, dones

    def __len__(self) -> int:
        return len(self.buf)

    def to_list(self) -> list[Transition]:
        return list(self.buf)

    def from_list(self, data: list[Transition]) -> None:
        self.buf.clear()
        self.buf.extend(data)


# ─────────────────────────────────────────────────────────────────────────────
# Serialisation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _weights_to_b64(state_dict: dict) -> str:
    buf = io.BytesIO()
    torch.save(state_dict, buf)
    return base64.b64encode(buf.getvalue()).decode()


def _b64_to_weights(s: str) -> dict:
    buf = io.BytesIO(base64.b64decode(s))
    return torch.load(buf, map_location="cpu", weights_only=True)


def _serialize_policy_state(
    q_net: QNetwork,
    target_net: QNetwork,
    optimizer: optim.Optimizer,
    buffer: ReplayBuffer,
    epsilon: float,
    prev_states: dict[str, list[float]],
    prev_actions: dict[str, int],
    visit_counts: dict[str, int],
    episode_rewards: list[float],
    cap: int = 2000,
) -> dict:
    # Cap replay buffer to avoid JSON bloat — keep the most recent transitions
    buf_list = buffer.to_list()[-cap:]
    return {
        "q_net":          _weights_to_b64(q_net.state_dict()),
        "target_net":     _weights_to_b64(target_net.state_dict()),
        "optimizer":      _weights_to_b64(optimizer.state_dict()),
        "buffer":         buf_list,
        "epsilon":        epsilon,
        "prev_states":    prev_states,
        "prev_actions":   prev_actions,
        "visit_counts":   visit_counts,
        "episode_rewards": episode_rewards,
    }


def _restore_policy_state(
    ps: dict,
    q_net: QNetwork,
    target_net: QNetwork,
    optimizer: optim.Optimizer,
    buffer: ReplayBuffer,
) -> tuple[float, dict[str, list[float]], dict[str, int], dict[str, int], list[float]]:
    q_net.load_state_dict(_b64_to_weights(ps["q_net"]))
    target_net.load_state_dict(_b64_to_weights(ps["target_net"]))
    try:
        optimizer.load_state_dict(_b64_to_weights(ps["optimizer"]))
    except Exception:
        pass  # optimizer state mismatch (e.g. first real load) — reset silently
    buffer.from_list(ps.get("buffer", []))
    return (
        float(ps.get("epsilon", 1.0)),
        ps.get("prev_states", {}),
        ps.get("prev_actions", {}),
        ps.get("visit_counts", {}),
        ps.get("episode_rewards", []),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Reward aggregation
# ─────────────────────────────────────────────────────────────────────────────

def _aggregate_rewards(reward_signals: dict | None, reward_cfg: dict) -> dict[str, float]:
    """Combine multiple reward signal ports into a single scalar per seq_id."""
    if not reward_signals:
        return {}
    signals_cfg = reward_cfg.get("signals", [])
    if not signals_cfg:
        # Flat default: average all available score dicts
        combined: dict[str, list[float]] = {}
        for port_scores in reward_signals.values():
            if isinstance(port_scores, dict):
                for sid, v in port_scores.items():
                    if isinstance(v, (int, float)):
                        combined.setdefault(str(sid), []).append(float(v))
        return {sid: sum(vs) / len(vs) for sid, vs in combined.items()}

    per_seq: dict[str, float] = {}
    for cfg in signals_cfg:
        port = cfg.get("port", "")
        weight = float(cfg.get("weight", 1.0))
        lower_is_better = bool(cfg.get("lower_is_better", True))
        norm = cfg.get("normalization", "none")

        scores_raw = reward_signals.get(port)
        if not isinstance(scores_raw, dict):
            continue
        scores = {str(k): float(v) for k, v in scores_raw.items() if isinstance(v, (int, float))}
        if not scores:
            continue

        if norm == "z_score":
            vals = list(scores.values())
            mu, sigma = sum(vals) / len(vals), (sum((v - sum(vals) / len(vals)) ** 2 for v in vals) / len(vals)) ** 0.5
            scores = {k: (v - mu) / (sigma + 1e-8) for k, v in scores.items()}
        elif norm == "min_max":
            lo, hi = min(scores.values()), max(scores.values())
            scores = {k: (v - lo) / (hi - lo + 1e-8) for k, v in scores.items()}

        for sid, v in scores.items():
            r = -v if lower_is_better else v
            per_seq[sid] = per_seq.get(sid, 0.0) + weight * r

    return per_seq


# ─────────────────────────────────────────────────────────────────────────────
# ε decay
# ─────────────────────────────────────────────────────────────────────────────

def _decay_epsilon(epsilon: float, algo_cfg: dict) -> float:
    eps_end = float(algo_cfg.get("epsilon_end", 0.05))
    eps_start = float(algo_cfg.get("epsilon_start", 1.0))
    decay_steps = int(algo_cfg.get("epsilon_decay_steps", 100))
    decay_type = algo_cfg.get("epsilon_decay", "linear")

    if decay_type == "exponential":
        factor = (eps_end / max(eps_start, 1e-8)) ** (1.0 / max(decay_steps, 1))
        return max(eps_end, epsilon * factor)
    else:  # linear
        step = (eps_start - eps_end) / max(decay_steps, 1)
        return max(eps_end, epsilon - step)


# ─────────────────────────────────────────────────────────────────────────────
# Training step (Double DQN)
# ─────────────────────────────────────────────────────────────────────────────

def _train_step(
    q_net: QNetwork,
    target_net: QNetwork,
    optimizer: optim.Optimizer,
    buffer: ReplayBuffer,
    batch_size: int,
    gamma: float,
) -> float:
    if len(buffer) < batch_size:
        return 0.0

    states, actions, rewards, next_states, dones = buffer.sample(batch_size)

    q_vals = q_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)  # [B]

    with torch.no_grad():
        next_a = q_net(next_states).argmax(1)                          # online selects
        next_q = target_net(next_states).gather(1, next_a.unsqueeze(1)).squeeze(1)  # target evaluates
        targets = rewards + gamma * next_q * (1.0 - dones)

    loss = F.smooth_l1_loss(q_vals, targets)
    optimizer.zero_grad()
    loss.backward()
    nn.utils.clip_grad_norm_(q_net.parameters(), max_norm=10.0)
    optimizer.step()
    return float(loss.item())


def _soft_update(target: QNetwork, online: QNetwork, tau: float) -> None:
    for tp, op in zip(target.parameters(), online.parameters()):
        tp.data.copy_(tau * op.data + (1.0 - tau) * tp.data)


# ─────────────────────────────────────────────────────────────────────────────
# Visualisation data builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_q_heatmap(q_all: torch.Tensor, seq_ids: list[str], actions: list[dict]) -> dict:
    """For each (cdr, strategy) pair — report max Q over all sequences and n_mutations."""
    # Collect unique CDRs and strategies
    cdrs = list(dict.fromkeys(a["cdr"] for a in actions))
    strategies = list(dict.fromkeys(a["strategy"] for a in actions))
    heatmap: dict[str, dict[str, float]] = {c: {} for c in cdrs}

    q_np = q_all.detach().numpy()  # [N, A]
    for ci, cdr in enumerate(cdrs):
        for si, strat in enumerate(strategies):
            indices = [i for i, a in enumerate(actions) if a["cdr"] == cdr and a["strategy"] == strat]
            if indices:
                heatmap[cdr][strat] = float(q_np[:, indices].max())

    return {"cdrs": cdrs, "strategies": strategies, "values": heatmap}


def _build_tsne_coords(states: torch.Tensor, seq_ids: list[str]) -> dict[str, list[float]]:
    """2-D t-SNE projection of state embeddings; falls back to PCA for small N."""
    n = states.shape[0]
    if n < 4:
        return {sid: [float(i), 0.0] for i, sid in enumerate(seq_ids)}
    arr = states.detach().numpy()
    try:
        from sklearn.manifold import TSNE
        perp = min(30, n - 1)
        coords = TSNE(n_components=2, perplexity=perp, random_state=42).fit_transform(arr)
    except Exception:
        try:
            from sklearn.decomposition import PCA
            coords = PCA(n_components=2).fit_transform(arr)
        except Exception:
            coords = [[float(i), 0.0] for i in range(n)]
    return {sid: [float(coords[i, 0]), float(coords[i, 1])] for i, sid in enumerate(seq_ids)}


def _build_policy_arrows(q_all: torch.Tensor, actions: list[dict]) -> list[dict]:
    """Per-CDR dominant strategy + softmax distribution for PolicyArrows panel."""
    cdrs = list(dict.fromkeys(a["cdr"] for a in actions))
    strategies = list(dict.fromkeys(a["strategy"] for a in actions))
    q_mean = q_all.mean(dim=0)  # [A] — average over sequences

    rows = []
    for cdr in cdrs:
        strat_q: dict[str, float] = {}
        for strat in strategies:
            idxs = [i for i, a in enumerate(actions) if a["cdr"] == cdr and a["strategy"] == strat]
            if idxs:
                strat_q[strat] = float(q_mean[idxs].max().item())
        if not strat_q:
            continue
        # Softmax over strategy Q-values → probability distribution
        vals_t = torch.tensor(list(strat_q.values()))
        probs = F.softmax(vals_t, dim=0).tolist()
        best_strat = max(strat_q, key=strat_q.__getitem__)
        best_val = strat_q[best_strat]
        uniform_val = sum(strat_q.values()) / len(strat_q)
        rows.append({
            "cdr": cdr,
            "dominant_strategy": best_strat,
            "distribution": {s: float(p) for s, p in zip(strat_q.keys(), probs)},
            "confidence": float(best_val - uniform_val),
        })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Embedding normalisation (mirrors rcc_mlde adapter's _coerce_embeddings)
# ─────────────────────────────────────────────────────────────────────────────

def _coerce_embeddings(raw: Any) -> dict[str, list[float]]:
    if isinstance(raw, dict) and "results" in raw:
        out: dict[str, list[float]] = {}
        for i, entry in enumerate(raw["results"]):
            emb = entry.get("emb_vh") or entry.get("emb_vl") or entry.get("embedding")
            if emb and isinstance(emb, list) and emb and isinstance(emb[0], (int, float)):
                sid = entry.get("vh") or entry.get("vl") or f"seq_{i}"
                out[str(sid)] = emb
        return out
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items()
                if isinstance(v, list) and v and isinstance(v[0], (int, float))}
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        # AbMAP results list passed directly: [{vh: str, emb_vh: [float...], ...}, ...]
        out2: dict[str, list[float]] = {}
        for i, entry in enumerate(raw):
            emb = entry.get("emb_vh") or entry.get("emb_vl") or entry.get("embedding")
            if emb and isinstance(emb, list) and emb and isinstance(emb[0], (int, float)):
                sid = entry.get("vh") or entry.get("vl") or f"seq_{i}"
                out2[str(sid)] = emb
        return out2
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def _run(inputs: dict) -> dict:
    rl_spec = inputs.get("rl_spec") or {}
    if isinstance(rl_spec, str):
        rl_spec = json.loads(rl_spec)

    mode = str(inputs.get("mode", "train_and_act"))
    top_k = int(inputs.get("top_k", 4))

    # ── State config ──────────────────────────────────────────────────────────
    state_cfg = rl_spec.get("state", {})
    proj_dim  = int(state_cfg.get("projection_dim", 0))

    raw_emb = inputs.get("state_embeddings")
    state_embeddings = _coerce_embeddings(raw_emb)
    if not state_embeddings:
        raise ValueError("rl_designer: state_embeddings is empty or invalid")

    seq_ids = sorted(state_embeddings.keys())
    state_dim = len(next(iter(state_embeddings.values())))
    effective_dim = proj_dim if proj_dim > 0 else state_dim

    # ── Action space ──────────────────────────────────────────────────────────
    actions = _build_actions(rl_spec)
    n_actions = len(actions)
    if n_actions == 0:
        raise ValueError("rl_designer: action space is empty")

    # ── Algorithm config ──────────────────────────────────────────────────────
    algo = rl_spec.get("algorithm", {})
    gamma        = float(algo.get("gamma", 0.99))
    lr           = float(algo.get("learning_rate", 1e-3))
    batch_size   = int(algo.get("batch_size", 32))
    buf_cap      = int(algo.get("replay_buffer_size", 5000))
    n_train      = int(algo.get("n_train_steps", 20))
    target_freq  = int(algo.get("target_update_freq", 10))
    tau          = float(algo.get("tau", 1.0))
    warmup       = int(algo.get("warmup_steps", batch_size))
    eps_start    = float(algo.get("epsilon_start", 1.0))

    policy_spec  = rl_spec.get("policy_network", {})

    # ── Build networks + optimizer + buffer ───────────────────────────────────
    projection = _make_projection(state_dim, proj_dim)
    q_net      = QNetwork(policy_spec, effective_dim, n_actions)
    target_net = QNetwork(policy_spec, effective_dim, n_actions)
    target_net.load_state_dict(q_net.state_dict())
    target_net.eval()

    optimizer = optim.Adam(
        list(q_net.parameters()) + (list(projection.parameters()) if projection else []),
        lr=lr,
    )
    buffer = ReplayBuffer(buf_cap)

    # ── Restore or initialise policy state ───────────────────────────────────
    ps_raw = inputs.get("policy_state")
    if isinstance(ps_raw, str):
        ps_raw = json.loads(ps_raw)

    epsilon      = eps_start
    prev_states: dict[str, list[float]] = {}
    prev_actions: dict[str, int] = {}
    visit_counts: dict[str, int] = {}
    episode_rewards: list[float] = []

    if ps_raw and isinstance(ps_raw, dict):
        epsilon, prev_states, prev_actions, visit_counts, episode_rewards = _restore_policy_state(
            ps_raw, q_net, target_net, optimizer, buffer
        )

    # ── Build state tensors ───────────────────────────────────────────────────
    raw_states_list = [state_embeddings[sid] for sid in seq_ids]
    states_t = torch.tensor(raw_states_list, dtype=torch.float32)  # [N, D]
    if projection is not None:
        with torch.no_grad():
            states_t = projection(states_t)

    # ── Fill replay buffer with (prev_state, prev_action, reward, curr_state) ─
    reward_cfg = rl_spec.get("reward", {})
    raw_reward_signals = inputs.get("reward_signals") or {}
    rewards_map = _aggregate_rewards(raw_reward_signals, reward_cfg)

    # Also try top-level flattened score ports (e.g. haddock_score, plddt, ...)
    _SCORE_KEYS = ("haddock_score", "docking_score", "score", "plddt", "solubility_score",
                   "acquisition_score", "mean_prediction")
    for k, v in inputs.items():
        if k in _SCORE_KEYS and isinstance(v, (int, float)):
            for sid in seq_ids:
                rewards_map.setdefault(sid, float(v))

    if prev_states and rewards_map:
        iter_mean_reward = 0.0
        count = 0
        # Iterate over prev_states keys (previous iteration's seq_ids) — NOT current seq_ids.
        # After CDR mutation + hill-climbing selection the current sequence usually differs from
        # the previous one, so matching on seq_ids would always miss.
        for prev_sid, ps_vec in prev_states.items():
            if prev_sid not in prev_actions:
                continue
            pa_idx = prev_actions[prev_sid]
            reward = float(rewards_map.get(prev_sid, 0.0))
            # next_state: use the current embedding for this prev_sid if it still exists
            # (rejection case), otherwise fall back to the first current state (accept case).
            if prev_sid in seq_ids:
                curr_vec = states_t[seq_ids.index(prev_sid)].tolist()
            else:
                curr_vec = states_t[0].tolist()
            buffer.push(ps_vec, pa_idx, reward, curr_vec, done=False)
            iter_mean_reward += reward
            count += 1
        if count > 0:
            episode_rewards.append(iter_mean_reward / count)
        if len(episode_rewards) > 200:
            episode_rewards = episode_rewards[-200:]

    # ── Training ──────────────────────────────────────────────────────────────
    losses: list[float] = []
    if mode in ("train", "train_and_act"):
        for step in range(n_train):
            if len(buffer) >= max(warmup, batch_size):
                loss = _train_step(q_net, target_net, optimizer, buffer, batch_size, gamma)
                losses.append(loss)
                if (step + 1) % target_freq == 0:
                    _soft_update(target_net, q_net, tau)

    # ── Action selection ──────────────────────────────────────────────────────
    # NOTE: epsilon is decayed AFTER acting so the current epsilon applies to this
    # iteration's actions, and the decayed value is stored for the next iteration.
    q_all = torch.zeros(len(seq_ids), n_actions)
    recommended_actions: list[dict] = []
    new_prev_states: dict[str, list[float]] = {}
    new_prev_actions: dict[str, int] = {}

    if mode in ("act", "train_and_act"):
        q_net.eval()
        with torch.no_grad():
            q_all = q_net(states_t)  # [N, A]
        q_net.train()

        for i, sid in enumerate(seq_ids):
            q_row = q_all[i]
            exploratory = random.random() < epsilon
            if exploratory:
                a_idx = random.randint(0, n_actions - 1)
            else:
                a_idx = int(q_row.argmax().item())

            act = actions[a_idx]
            visit_counts[str(a_idx)] = visit_counts.get(str(a_idx), 0) + 1
            new_prev_states[sid] = states_t[i].tolist()
            new_prev_actions[sid] = a_idx

            recommended_actions.append({
                "seq_id":      sid,
                "action_idx":  a_idx,
                "cdr":         f"CDR_{act['cdr']}",
                "strategy":    act["strategy"],
                "n_mutations": act["n_mutations"],
                "q_value":     float(q_row[a_idx].item()),
                "exploratory": exploratory,
            })

        # Sort by Q-value descending and cap at top_k
        recommended_actions.sort(key=lambda x: x["q_value"], reverse=True)
        recommended_actions = recommended_actions[:top_k]

        # Decay epsilon after acting so the current iteration uses the pre-decay value
        if mode in ("train", "train_and_act"):
            epsilon = _decay_epsilon(epsilon, algo)

    # ── Q-values dict (all sequences × all actions) ───────────────────────────
    q_values_out: dict[str, dict[str, float]] = {}
    if mode in ("act", "train_and_act"):
        for i, sid in enumerate(seq_ids):
            q_values_out[sid] = {str(j): float(q_all[i, j].item()) for j in range(n_actions)}

    # ── Convenience scalar outputs for direct wiring ─────────────────────────
    top_cdr = top_strategy = ""
    top_n_mutations = 1
    if recommended_actions:
        top = recommended_actions[0]
        top_cdr        = top["cdr"]
        top_strategy   = top["strategy"]
        top_n_mutations = top["n_mutations"]

    # ── Visualisation data ────────────────────────────────────────────────────
    viz_data: dict = {
        "q_heatmap":      _build_q_heatmap(q_all, seq_ids, actions) if mode in ("act", "train_and_act") else {},
        "tsne_coords":    _build_tsne_coords(states_t, seq_ids),
        "visit_counts":   visit_counts,
        "episode_rewards": episode_rewards,
        "policy_arrows":  _build_policy_arrows(q_all, actions) if mode in ("act", "train_and_act") else [],
    }

    # ── Metrics ───────────────────────────────────────────────────────────────
    mean_loss = float(sum(losses) / len(losses)) if losses else 0.0
    metrics = {
        "epsilon":       round(epsilon, 6),
        "buffer_size":   len(buffer),
        "n_train_steps": len(losses),
        "mean_loss":     round(mean_loss, 6),
        "mean_td_error": round(mean_loss, 6),  # same as Huber loss for reporting
        "mean_reward":   round(episode_rewards[-1] if episode_rewards else 0.0, 6),
    }

    # ── Serialise updated policy state ───────────────────────────────────────
    new_policy_state = _serialize_policy_state(
        q_net=q_net,
        target_net=target_net,
        optimizer=optimizer,
        buffer=buffer,
        epsilon=epsilon,
        prev_states=new_prev_states or prev_states,
        prev_actions=new_prev_actions or prev_actions,
        visit_counts=visit_counts,
        episode_rewards=episode_rewards,
    )

    return {
        "recommended_actions": recommended_actions,
        "top_cdr":             top_cdr,
        "top_strategy":        top_strategy,
        "top_n_mutations":     top_n_mutations,
        "q_values":            q_values_out,
        "policy_state":        new_policy_state,
        "metrics":             metrics,
        "viz_data":            viz_data,
    }


if __name__ == "__main__":
    inputs = json.load(sys.stdin)
    try:
        outputs = _run(inputs)
    except Exception as exc:
        import traceback
        json.dump({"error": str(exc), "traceback": traceback.format_exc()}, sys.stdout)
        sys.stdout.flush()
        sys.exit(1)
    json.dump(outputs, sys.stdout)
    sys.stdout.flush()
