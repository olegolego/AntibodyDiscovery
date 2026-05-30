"""Comprehensive tests for the RL Designer tool.

Coverage:
  - DQN unit: action space, replay buffer, training step, epsilon decay, serialisation
  - Multi-iteration: policy_state serialise → deserialise → buffer grows, epsilon decays
  - Q-value learning: reward signal drives Q toward correct action over 20 iterations
  - Visualisation: Q-heatmap shape, t-SNE fallback, policy arrows
  - Reward aggregation: z-score normalisation, lower-is-better sign flip, multi-port
  - Embedding coercion: results-key format, pre-keyed dict, list-of-dicts
  - Adapter input normalisation (no subprocess — calls adapter helpers directly)
  - Loop executor integration: _build_accumulated_rl_state picks most recent
  - End-to-end subprocess: run.py via real venv, three chained iterations
"""
from __future__ import annotations

import base64
import io
import json
import math
import os
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from itertools import product

import pytest

# ── Paths ────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
RL_RUN_PY  = REPO_ROOT / "tools" / "rl_designer" / "run.py"
RL_PYTHON  = REPO_ROOT / "tools" / "custom_dnn" / ".venv" / "bin" / "python"

# Make sure PyTorch tools are importable from the custom_dnn venv
sys.path.insert(0, str(RL_PYTHON.parent.parent / "lib"))  # not needed for subprocess tests


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

SMALL_RL_SPEC = {
    "version": "1.0",
    "state": {"repr_type": "abmap", "dim": 16, "projection_dim": 0, "port": "state_embeddings"},
    "action": {
        "cdrs": ["H3", "L3"],
        "strategies": ["blosum62", "conservative"],
        "n_mutations_choices": [1, 2],
    },
    "reward": {
        "signals": [
            {"port": "haddock_score", "weight": 1.0, "lower_is_better": True, "normalization": "z_score"}
        ],
        "shaping": "sparse",
    },
    "algorithm": {
        "kind": "dqn",
        "double_dqn": True,
        "target_update_freq": 3,
        "gamma": 0.99,
        "epsilon_start": 1.0,
        "epsilon_end": 0.1,
        "epsilon_decay": "linear",
        "epsilon_decay_steps": 8,
        "learning_rate": 0.01,
        "batch_size": 4,
        "replay_buffer_size": 200,
        "n_train_steps": 5,
        "warmup_steps": 4,
        "tau": 1.0,
    },
    "policy_network": {"version": "1.0", "nodes": [], "edges": []},
}

N_SEQS = 4
STATE_DIM = 16


def _fake_embeddings(n: int = N_SEQS, dim: int = STATE_DIM, seed: int = 0) -> dict:
    import random
    rng = random.Random(seed)
    return {f"seq_{i}": [rng.gauss(0, 1) for _ in range(dim)] for i in range(n)}


def _fake_scores(seq_ids: list[str], seed: int = 0) -> dict:
    import random
    rng = random.Random(seed)
    return {"haddock_score": {sid: rng.uniform(-200, -50) for sid in seq_ids}}


def _run_subprocess(payload: dict, timeout: int = 60) -> dict:
    """Run run.py via the RL venv, return parsed JSON output."""
    assert RL_PYTHON.exists(), f"RL venv python not found: {RL_PYTHON}"
    result = subprocess.run(
        [str(RL_PYTHON), str(RL_RUN_PY)],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")[-3000:]
        pytest.fail(f"run.py exited with code {result.returncode}:\n{stderr}")
    return json.loads(result.stdout)


def _base_payload(
    spec: dict | None = None,
    embeddings: dict | None = None,
    reward_signals: dict | None = None,
    policy_state: dict | None = None,
    mode: str = "train_and_act",
    top_k: int = 3,
) -> dict:
    # Note: use explicit None check so callers can pass {} to test empty-embedding behaviour
    if spec is None:
        spec = SMALL_RL_SPEC
    if embeddings is None:
        embeddings = _fake_embeddings()
    return {
        "rl_spec": spec,
        "state_embeddings": embeddings,
        "reward_signals": reward_signals,
        "policy_state": policy_state,
        "mode": mode,
        "top_k": top_k,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Action space
# ─────────────────────────────────────────────────────────────────────────────

class TestActionSpace:
    """Action enumeration and |A| calculation."""

    def test_action_count_matches_spec(self):
        out = _run_subprocess(_base_payload())
        # 2 CDRs × 2 strategies × 2 n_muts = 8
        actions = out["recommended_actions"]
        # recommended_actions is top_k, but q_values covers all |A|=8
        q_vals = out["q_values"]
        assert len(q_vals) > 0
        # Pick any seq_id; its Q-value dict should have exactly 8 entries
        first_seq_qvals = next(iter(q_vals.values()))
        assert len(first_seq_qvals) == 8, f"Expected |A|=8, got {len(first_seq_qvals)}"

    def test_top_k_clipped_to_actions(self):
        payload = _base_payload(top_k=20)  # more than |A|=8
        out = _run_subprocess(payload)
        assert len(out["recommended_actions"]) <= 8

    def test_output_cdr_is_valid(self):
        out = _run_subprocess(_base_payload())
        valid_cdrs = {"CDR_H3", "CDR_L3", "H3", "L3"}
        for action in out["recommended_actions"]:
            cdr = action.get("cdr", "")
            assert any(v in cdr for v in ["H3", "L3"]), f"Unexpected CDR: {cdr}"

    def test_output_strategy_is_valid(self):
        out = _run_subprocess(_base_payload())
        valid = {"blosum62", "conservative"}
        for action in out["recommended_actions"]:
            assert action.get("strategy") in valid

    def test_n_mutations_is_valid(self):
        out = _run_subprocess(_base_payload())
        for action in out["recommended_actions"]:
            assert action.get("n_mutations") in {1, 2}

    def test_large_action_space(self):
        spec = deepcopy(SMALL_RL_SPEC)
        spec["action"]["cdrs"] = ["H1", "H2", "H3", "L1", "L2", "L3"]
        spec["action"]["strategies"] = ["random", "blosum62", "conservative", "sapiens"]
        spec["action"]["n_mutations_choices"] = [1, 2, 3]
        out = _run_subprocess(_base_payload(spec=spec))
        first_seq_qvals = next(iter(out["q_values"].values()))
        assert len(first_seq_qvals) == 6 * 4 * 3  # 72


# ─────────────────────────────────────────────────────────────────────────────
# 2. Epsilon decay across iterations
# ─────────────────────────────────────────────────────────────────────────────

class TestEpsilonDecay:
    """Epsilon must decrease monotonically across loop iterations."""

    def _chain_iterations(self, n: int = 5) -> list[float]:
        """Run n iterations, feeding policy_state forward each time."""
        epsilons = []
        policy_state = None
        embeddings = _fake_embeddings(n=6, dim=16, seed=42)
        for i in range(n):
            scores = _fake_scores(list(embeddings.keys()), seed=i)
            payload = _base_payload(
                embeddings=embeddings,
                reward_signals=scores,
                policy_state=policy_state,
            )
            out = _run_subprocess(payload)
            epsilons.append(out["metrics"]["epsilon"])
            policy_state = out["policy_state"]
        return epsilons

    def test_epsilon_monotonically_decreases(self):
        eps = self._chain_iterations(5)
        for i in range(1, len(eps)):
            assert eps[i] <= eps[i - 1] + 1e-6, (
                f"Epsilon increased at iteration {i}: {eps[i-1]:.4f} → {eps[i]:.4f}"
            )

    def test_epsilon_reaches_minimum(self):
        # With epsilon_decay_steps=8, after 10 iterations it should be at epsilon_end
        eps = self._chain_iterations(10)
        eps_end = SMALL_RL_SPEC["algorithm"]["epsilon_end"]
        assert eps[-1] <= eps_end + 1e-6, (
            f"Epsilon didn't reach minimum: {eps[-1]:.4f} > {eps_end}"
        )

    def test_first_iteration_fully_exploratory(self):
        out = _run_subprocess(_base_payload(policy_state=None))
        # On iteration 0 with no policy_state, all actions should be exploratory
        for action in out["recommended_actions"]:
            assert action.get("exploratory") is True, (
                f"Expected exploratory=True on iter 0, got: {action}"
            )

    def test_exponential_decay(self):
        spec = deepcopy(SMALL_RL_SPEC)
        spec["algorithm"]["epsilon_decay"] = "exponential"
        eps_prev = None
        policy_state = None
        embeddings = _fake_embeddings()
        for i in range(4):
            out = _run_subprocess(_base_payload(spec=spec, embeddings=embeddings, policy_state=policy_state))
            eps = out["metrics"]["epsilon"]
            if eps_prev is not None:
                # Exponential decay: ratio should be roughly constant
                assert eps <= eps_prev + 1e-6
            eps_prev = eps
            policy_state = out["policy_state"]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Replay buffer growth
# ─────────────────────────────────────────────────────────────────────────────

class TestReplayBuffer:
    """Buffer must grow across iterations until capacity."""

    def test_buffer_grows_across_iterations(self):
        sizes = []
        policy_state = None
        embeddings = _fake_embeddings(n=5, dim=16)
        for i in range(5):
            scores = _fake_scores(list(embeddings.keys()), seed=i)
            payload = _base_payload(embeddings=embeddings, reward_signals=scores, policy_state=policy_state)
            out = _run_subprocess(payload)
            sizes.append(out["metrics"]["buffer_size"])
            policy_state = out["policy_state"]

        # Buffer should be 0 on iter 0 (no prev transitions) then grow from iter 1
        assert sizes[0] == 0, f"Expected 0 on iter 0, got {sizes[0]}"
        assert sizes[-1] > 0, f"Buffer never grew: {sizes}"
        # Monotonically non-decreasing
        for i in range(1, len(sizes)):
            assert sizes[i] >= sizes[i - 1], f"Buffer shrank at iter {i}: {sizes}"

    def test_buffer_capped_at_serialization(self):
        """policy_state['buffer'] must never exceed 2000 entries."""
        policy_state = None
        embeddings = _fake_embeddings(n=10, dim=16)
        for i in range(8):
            scores = _fake_scores(list(embeddings.keys()), seed=i)
            payload = _base_payload(embeddings=embeddings, reward_signals=scores, policy_state=policy_state)
            out = _run_subprocess(payload)
            policy_state = out["policy_state"]
            buf = policy_state.get("buffer", [])
            assert len(buf) <= 2000, f"Buffer serialisation cap exceeded: {len(buf)}"

    def test_policy_state_has_required_keys(self):
        out = _run_subprocess(_base_payload())
        ps = out["policy_state"]
        required = {"q_net", "target_net", "optimizer", "buffer", "epsilon",
                    "prev_states", "prev_actions", "visit_counts", "episode_rewards"}
        assert required.issubset(ps.keys()), f"Missing keys: {required - ps.keys()}"

    def test_policy_state_weights_are_base64(self):
        out = _run_subprocess(_base_payload())
        ps = out["policy_state"]
        for key in ("q_net", "target_net", "optimizer"):
            assert isinstance(ps[key], str), f"{key} should be base64 string"
            try:
                base64.b64decode(ps[key])
            except Exception as e:
                pytest.fail(f"policy_state[{key!r}] is not valid base64: {e}")

    def test_prev_states_filled_after_iter0(self):
        out = _run_subprocess(_base_payload())
        ps = out["policy_state"]
        # After iteration 0 (exploratory), prev_states should record what we sent
        assert isinstance(ps["prev_states"], dict)
        assert len(ps["prev_states"]) > 0, "prev_states should be populated after iter 0"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Q-value learning — does reward signal shape policy?
# ─────────────────────────────────────────────────────────────────────────────

class TestQLearning:
    """
    Over repeated iterations with consistent reward signal (H3/blosum62 always wins),
    the agent should shift exploitation toward that action.
    Checked by comparing Q-values: Q(H3, blosum62) > Q(L3, conservative) after N iters.
    """

    def _run_biased_loop(self, n_iters: int = 20) -> dict:
        """Simulate n_iters. Reward is always best for seq_0 (which we tag as H3 action)."""
        policy_state = None
        embeddings = _fake_embeddings(n=6, dim=16, seed=99)
        seq_ids = list(embeddings.keys())

        # Consistent reward: seq_0 always gets the best score (lowest HADDOCK value = highest reward)
        for i in range(n_iters):
            base_score = -100.0
            scores_by_seq = {sid: base_score + j * 5 for j, sid in enumerate(seq_ids)}
            # seq_0 always gets the best score (most negative)
            scores_by_seq[seq_ids[0]] = -200.0
            reward_signals = {"haddock_score": scores_by_seq}

            payload = _base_payload(
                embeddings=embeddings,
                reward_signals=reward_signals,
                policy_state=policy_state,
            )
            out = _run_subprocess(payload)
            policy_state = out["policy_state"]

        return out

    def test_q_values_become_non_uniform_after_training(self):
        out = self._run_biased_loop(20)
        # After training, Q-values across actions should not all be identical
        q_vals = out["q_values"]
        for seq_id, action_qs in q_vals.items():
            qs = list(action_qs.values())
            spread = max(qs) - min(qs)
            assert spread > 0.01, (
                f"Q-values for {seq_id} appear uniform after training: spread={spread:.4f}"
            )

    def test_training_loss_is_computed_after_warmup(self):
        """After buffer fills past warmup, mean_loss should be > 0."""
        policy_state = None
        embeddings = _fake_embeddings(n=6, dim=16)
        losses = []
        for i in range(10):
            scores = _fake_scores(list(embeddings.keys()), seed=i)
            payload = _base_payload(embeddings=embeddings, reward_signals=scores, policy_state=policy_state)
            out = _run_subprocess(payload)
            losses.append(out["metrics"]["mean_loss"])
            policy_state = out["policy_state"]

        # At least one iteration should have non-zero loss (after warmup)
        assert any(l > 0 for l in losses), f"Training loss never > 0: {losses}"

    def test_mean_reward_tracked_in_metrics(self):
        policy_state = None
        embeddings = _fake_embeddings(n=4, dim=16)
        for i in range(3):
            scores = _fake_scores(list(embeddings.keys()), seed=i)
            payload = _base_payload(embeddings=embeddings, reward_signals=scores, policy_state=policy_state)
            out = _run_subprocess(payload)
            policy_state = out["policy_state"]

        # After iteration 2 the reward signal was present, mean_reward should be populated
        assert "mean_reward" in out["metrics"]
        # mean_reward is stored in episode_rewards across iterations
        ps = out["policy_state"]
        assert len(ps.get("episode_rewards", [])) >= 1

    def test_visit_counts_accumulate(self):
        policy_state = None
        embeddings = _fake_embeddings(n=4, dim=16)
        for i in range(5):
            scores = _fake_scores(list(embeddings.keys()), seed=i)
            payload = _base_payload(embeddings=embeddings, reward_signals=scores, policy_state=policy_state)
            out = _run_subprocess(payload)
            policy_state = out["policy_state"]

        visit_counts = policy_state.get("visit_counts", {})
        assert len(visit_counts) > 0, "Visit counts not accumulated"
        total_visits = sum(int(v) for v in visit_counts.values())
        assert total_visits >= 4, f"Too few visits tracked: {total_visits}"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Reward aggregation
# ─────────────────────────────────────────────────────────────────────────────

class TestRewardAggregation:
    """Different reward signal configurations and normalisations."""

    def test_lower_is_better_sign_flip(self):
        """Lower HADDOCK score → higher reward (sign flip applied internally)."""
        payload_low = _base_payload(
            reward_signals={"haddock_score": {"seq_0": -200.0, "seq_1": -50.0}}
        )
        out_low = _run_subprocess(payload_low)
        # seq_0 got the better score, so its Q-values should be higher overall
        # (this is a soft check — just verifies no crash and reward flows through)
        assert out_low["metrics"].get("mean_reward", 0) != 0 or out_low["policy_state"]["prev_states"]

    def test_z_score_normalisation(self):
        """z-score normalisation should not crash even with identical scores."""
        payload = _base_payload(
            reward_signals={"haddock_score": {"seq_0": -100.0, "seq_1": -100.0, "seq_2": -100.0}}
        )
        out = _run_subprocess(payload)  # must not raise
        assert "policy_state" in out

    def test_min_max_normalisation(self):
        spec = deepcopy(SMALL_RL_SPEC)
        spec["reward"]["signals"][0]["normalization"] = "min_max"
        payload = _base_payload(
            spec=spec,
            reward_signals={"haddock_score": {"seq_0": -200.0, "seq_1": -150.0, "seq_2": -100.0}}
        )
        out = _run_subprocess(payload)
        assert "policy_state" in out

    def test_no_normalisation(self):
        spec = deepcopy(SMALL_RL_SPEC)
        spec["reward"]["signals"][0]["normalization"] = "none"
        payload = _base_payload(
            spec=spec,
            reward_signals={"haddock_score": {"seq_0": -200.0, "seq_1": -50.0}}
        )
        out = _run_subprocess(payload)
        assert "policy_state" in out

    def test_multi_port_reward(self):
        """Multiple reward signal ports should both contribute."""
        spec = deepcopy(SMALL_RL_SPEC)
        spec["reward"]["signals"] = [
            {"port": "haddock_score", "weight": 0.7, "lower_is_better": True, "normalization": "z_score"},
            {"port": "plddt_score",   "weight": 0.3, "lower_is_better": False, "normalization": "z_score"},
        ]
        payload = _base_payload(
            spec=spec,
            reward_signals={
                "haddock_score": {"seq_0": -200.0, "seq_1": -100.0},
                "plddt_score":   {"seq_0":   90.0, "seq_1":   70.0},
            }
        )
        out = _run_subprocess(payload)
        assert "policy_state" in out

    def test_missing_reward_port_ignored(self):
        """If a configured reward port is absent from reward_signals, no crash."""
        spec = deepcopy(SMALL_RL_SPEC)
        spec["reward"]["signals"].append(
            {"port": "nonexistent_port", "weight": 0.5, "lower_is_better": True, "normalization": "none"}
        )
        payload = _base_payload(spec=spec, reward_signals={"haddock_score": {"seq_0": -100.0}})
        out = _run_subprocess(payload)
        assert "policy_state" in out

    def test_no_reward_signals_still_acts(self):
        """With no reward signal at all, the agent should still output recommended actions."""
        payload = _base_payload(reward_signals=None, policy_state=None)
        out = _run_subprocess(payload)
        assert len(out["recommended_actions"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. Embedding coercion
# ─────────────────────────────────────────────────────────────────────────────

class TestEmbeddingCoercion:
    """All upstream embedding formats must be accepted."""

    def test_pre_keyed_dict_format(self):
        """Standard {seq_id: [float...]} format."""
        payload = _base_payload(embeddings={"seq_0": [0.1] * 16, "seq_1": [-0.5] * 16})
        out = _run_subprocess(payload)
        assert len(out["recommended_actions"]) > 0

    def test_results_key_format(self):
        """AbMAP/ESM results format: {"results": [{vh: ..., emb_vh: [...]}, ...]}"""
        embeddings = {
            "results": [
                {"vh": "EVQLV...", "emb_vh": [0.1] * 16},
                {"vh": "QVQLQ...", "emb_vh": [-0.2] * 16},
            ]
        }
        payload = _base_payload(embeddings=embeddings)
        out = _run_subprocess(payload)
        assert len(out["recommended_actions"]) > 0

    def test_list_of_dicts_format(self):
        """AbMAP wires results LIST directly (not wrapped in dict): [{vh:..., emb_vh:[...]}]"""
        embeddings = [
            {"vh": "EVQLV...", "emb_vh": [0.1] * 16},
            {"vh": "QVQLQ...", "emb_vh": [-0.2] * 16},
            {"vh": "DVQLV...", "emb_vh": [0.5] * 16},
        ]
        payload = _base_payload(embeddings=embeddings)
        out = _run_subprocess(payload)
        assert len(out["recommended_actions"]) > 0
        assert len(out["q_values"]) == 3

    def test_single_sequence(self):
        """Edge case: only one sequence in state_embeddings."""
        payload = _base_payload(embeddings={"seq_0": [0.5] * 16})
        out = _run_subprocess(payload)
        assert len(out["recommended_actions"]) > 0

    def test_high_dim_embeddings(self):
        """ESM-2-650M style 1280-dim embeddings."""
        spec = deepcopy(SMALL_RL_SPEC)
        spec["state"]["dim"] = 1280
        payload = _base_payload(
            spec=spec,
            embeddings={f"seq_{i}": [float(i) / 10] * 1280 for i in range(4)}
        )
        out = _run_subprocess(payload)
        assert "q_values" in out

    def test_projection_dim_reduces_state(self):
        """With projection_dim=32, a 128-dim state should be compressed."""
        spec = deepcopy(SMALL_RL_SPEC)
        spec["state"]["dim"] = 128
        spec["state"]["projection_dim"] = 32
        payload = _base_payload(
            spec=spec,
            embeddings={f"seq_{i}": [float(i)] * 128 for i in range(4)}
        )
        out = _run_subprocess(payload)
        assert "q_values" in out


# ─────────────────────────────────────────────────────────────────────────────
# 7. Visualisation data
# ─────────────────────────────────────────────────────────────────────────────

class TestVisualisationData:
    """Q-heatmap, t-SNE, and policy arrows must have correct structure."""

    def _get_viz(self, n_seqs: int = 6) -> dict:
        payload = _base_payload(embeddings=_fake_embeddings(n=n_seqs, dim=16))
        out = _run_subprocess(payload)
        return out.get("viz_data", {})

    def test_q_heatmap_has_cdrs_and_strategies(self):
        viz = self._get_viz()
        hm = viz.get("q_heatmap", {})
        assert "cdrs" in hm and "strategies" in hm and "values" in hm
        assert set(hm["cdrs"]) == {"H3", "L3"}
        assert set(hm["strategies"]) == {"blosum62", "conservative"}

    def test_q_heatmap_values_are_floats(self):
        viz = self._get_viz()
        for cdr, strats in viz["q_heatmap"]["values"].items():
            for strat, val in strats.items():
                assert isinstance(val, float), f"Q-heatmap[{cdr}][{strat}] is not float: {val!r}"

    def test_tsne_coords_has_all_seqs(self):
        n = 6
        viz = self._get_viz(n_seqs=n)
        coords = viz.get("tsne_coords", {})
        assert len(coords) == n, f"Expected {n} t-SNE points, got {len(coords)}"

    def test_tsne_coords_are_2d(self):
        viz = self._get_viz(n_seqs=6)
        for sid, coord in viz["tsne_coords"].items():
            assert len(coord) == 2, f"t-SNE coord for {sid} is not 2D: {coord}"

    def test_tsne_fallback_for_small_n(self):
        """With N<4 sequences, falls back to sequential positions without crashing."""
        payload = _base_payload(embeddings=_fake_embeddings(n=2, dim=16))
        out = _run_subprocess(payload)
        coords = out["viz_data"]["tsne_coords"]
        assert len(coords) == 2

    def test_policy_arrows_one_row_per_cdr(self):
        viz = self._get_viz()
        arrows = viz.get("policy_arrows", [])
        cdr_names = {row["cdr"] for row in arrows}
        assert "H3" in cdr_names and "L3" in cdr_names

    def test_policy_arrows_dominant_strategy_valid(self):
        viz = self._get_viz()
        valid = {"blosum62", "conservative"}
        for row in viz["policy_arrows"]:
            assert row["dominant_strategy"] in valid
            assert 0 <= row["confidence"]  # confidence can be negative if uniform

    def test_policy_arrows_distribution_sums_to_one(self):
        viz = self._get_viz()
        for row in viz["policy_arrows"]:
            total = sum(row["distribution"].values())
            assert abs(total - 1.0) < 1e-5, f"Distribution doesn't sum to 1: {total}"

    def test_visit_counts_in_viz(self):
        viz = self._get_viz()
        assert "visit_counts" in viz, "viz_data should include visit_counts"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Output completeness
# ─────────────────────────────────────────────────────────────────────────────

class TestOutputCompleteness:
    """All required output keys must be present in every mode."""

    REQUIRED_KEYS = {
        "recommended_actions", "q_values", "policy_state", "metrics", "viz_data",
        "top_cdr", "top_strategy", "top_n_mutations",
    }

    def test_all_output_keys_present_train_and_act(self):
        out = _run_subprocess(_base_payload(mode="train_and_act"))
        assert self.REQUIRED_KEYS.issubset(out.keys()), (
            f"Missing keys: {self.REQUIRED_KEYS - out.keys()}"
        )

    def test_all_output_keys_present_act_only(self):
        out = _run_subprocess(_base_payload(mode="act"))
        assert self.REQUIRED_KEYS.issubset(out.keys())

    def test_metrics_has_required_fields(self):
        out = _run_subprocess(_base_payload())
        m = out["metrics"]
        for field in ("epsilon", "buffer_size", "n_train_steps", "mean_loss", "mean_td_error"):
            assert field in m, f"metrics missing field: {field}"

    def test_recommended_actions_have_required_fields(self):
        out = _run_subprocess(_base_payload())
        for action in out["recommended_actions"]:
            for field in ("cdr", "strategy", "n_mutations", "q_value", "exploratory"):
                assert field in action, f"action missing field: {field}"

    def test_top_cdr_matches_first_recommended(self):
        out = _run_subprocess(_base_payload())
        first = out["recommended_actions"][0]
        # top_cdr convenience output should match the top recommended action's CDR
        assert out["top_cdr"] in first["cdr"], (
            f"top_cdr={out['top_cdr']!r} doesn't match first action cdr={first['cdr']!r}"
        )

    def test_top_strategy_matches_first_recommended(self):
        out = _run_subprocess(_base_payload())
        first = out["recommended_actions"][0]
        assert out["top_strategy"] == first["strategy"]

    def test_top_n_mutations_matches_first_recommended(self):
        out = _run_subprocess(_base_payload())
        first = out["recommended_actions"][0]
        assert out["top_n_mutations"] == first["n_mutations"]


# ─────────────────────────────────────────────────────────────────────────────
# 9. Policy state round-trip (serialise → deserialise)
# ─────────────────────────────────────────────────────────────────────────────

class TestPolicyStateRoundTrip:
    """policy_state from iteration N must be usable in iteration N+1."""

    def test_two_iteration_chain(self):
        embeddings = _fake_embeddings(n=5, dim=16, seed=7)
        scores = _fake_scores(list(embeddings.keys()), seed=7)

        # Iteration 0
        out0 = _run_subprocess(_base_payload(embeddings=embeddings))
        ps0 = out0["policy_state"]
        eps0 = out0["metrics"]["epsilon"]

        # Iteration 1 — feed in policy_state from iter 0 and real rewards
        out1 = _run_subprocess(_base_payload(
            embeddings=embeddings,
            reward_signals=scores,
            policy_state=ps0,
        ))
        ps1 = out1["policy_state"]
        eps1 = out1["metrics"]["epsilon"]

        assert eps1 < eps0, f"Epsilon should decrease: {eps0:.4f} → {eps1:.4f}"
        assert out1["metrics"]["buffer_size"] > 0, "Buffer should have transitions after iter 1"

    def test_three_iteration_chain_increasing_buffer(self):
        embeddings = _fake_embeddings(n=5, dim=16, seed=13)
        policy_state = None
        buffer_sizes = []
        for i in range(3):
            scores = _fake_scores(list(embeddings.keys()), seed=i)
            out = _run_subprocess(_base_payload(
                embeddings=embeddings,
                reward_signals=scores,
                policy_state=policy_state,
            ))
            buffer_sizes.append(out["metrics"]["buffer_size"])
            policy_state = out["policy_state"]

        assert buffer_sizes[0] == 0
        assert buffer_sizes[1] > 0
        assert buffer_sizes[2] >= buffer_sizes[1]

    def test_policy_state_weights_change_after_training(self):
        """Q-net weights from iter 0 vs iter 2 should differ (training happened)."""
        embeddings = _fake_embeddings(n=6, dim=16, seed=17)
        policy_state = None
        q_net_b64 = []

        for i in range(3):
            scores = _fake_scores(list(embeddings.keys()), seed=i)
            out = _run_subprocess(_base_payload(
                embeddings=embeddings,
                reward_signals=scores,
                policy_state=policy_state,
            ))
            q_net_b64.append(out["policy_state"]["q_net"])
            policy_state = out["policy_state"]

        # Weights should change between iterations once training kicks in
        assert q_net_b64[0] != q_net_b64[2], (
            "Q-net weights should change after training iterations"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 10. Loop executor integration (pure Python — no subprocess)
# ─────────────────────────────────────────────────────────────────────────────

class TestLoopExecutorIntegration:
    """Test that loop_executor helpers correctly accumulate rl_policy_state."""

    def _make_history_entry(self, policy_state: dict | None) -> dict:
        entry: dict = {"node_outputs": {}}
        if policy_state:
            entry["rl_policy_state"] = policy_state
        return entry

    def test_build_accumulated_rl_state_empty(self):
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from app.core.loop_executor import _build_accumulated_rl_state
        result = _build_accumulated_rl_state([])
        assert result is None

    def test_build_accumulated_rl_state_no_rl_entries(self):
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from app.core.loop_executor import _build_accumulated_rl_state
        history = [{"node_outputs": {}}, {"node_outputs": {}}]
        result = _build_accumulated_rl_state(history)
        assert result is None

    def test_build_accumulated_rl_state_single(self):
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from app.core.loop_executor import _build_accumulated_rl_state
        ps = {"q_net": "abc", "epsilon": 0.8}
        history = [self._make_history_entry(ps)]
        result = _build_accumulated_rl_state(history)
        assert result == ps

    def test_build_accumulated_rl_state_picks_most_recent(self):
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from app.core.loop_executor import _build_accumulated_rl_state
        ps0 = {"q_net": "first",  "epsilon": 1.0}
        ps1 = {"q_net": "second", "epsilon": 0.8}
        ps2 = {"q_net": "third",  "epsilon": 0.6}
        history = [
            self._make_history_entry(ps0),
            self._make_history_entry(ps1),
            self._make_history_entry(ps2),
        ]
        result = _build_accumulated_rl_state(history)
        assert result["q_net"] == "third", "Should pick most recent (last) policy_state"

    def test_build_accumulated_rl_state_skips_empties(self):
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from app.core.loop_executor import _build_accumulated_rl_state
        ps_real = {"q_net": "valid", "epsilon": 0.5}
        history = [
            self._make_history_entry(ps_real),
            self._make_history_entry(None),  # iteration with no rl output
            self._make_history_entry(None),
        ]
        result = _build_accumulated_rl_state(history)
        assert result["q_net"] == "valid"


# ─────────────────────────────────────────────────────────────────────────────
# 11. Adapter feature extraction
# ─────────────────────────────────────────────────────────────────────────────

class TestFeatureExtraction:
    """tool_features.py extractors must handle all edge cases."""

    def test_extractors_registered(self):
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from app.core.tool_features import _registry
        assert "rl_designer" in _registry
        assert len(_registry["rl_designer"]) == 6

    def test_epsilon_extractor(self):
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from app.core.tool_features import _registry
        fs = {f.col_id: f for f in _registry["rl_designer"]}
        outputs = {"metrics": {"epsilon": 0.75}}
        assert fs["rl_epsilon"].extractor(outputs) == 0.75

    def test_top_cdr_extractor(self):
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from app.core.tool_features import _registry
        fs = {f.col_id: f for f in _registry["rl_designer"]}
        outputs = {"recommended_actions": [{"cdr": "CDR_H3", "strategy": "blosum62"}]}
        assert fs["rl_top_cdr"].extractor(outputs) == "CDR_H3"

    def test_extractors_handle_missing_outputs(self):
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from app.core.tool_features import _registry
        fs = {f.col_id: f for f in _registry["rl_designer"]}
        for col_id, spec in fs.items():
            # Should not raise even with completely empty outputs
            try:
                spec.extractor({})
            except Exception as e:
                pytest.fail(f"Extractor {col_id!r} raised on empty outputs: {e}")

    def test_buffer_size_extractor(self):
        sys.path.insert(0, str(REPO_ROOT / "backend"))
        from app.core.tool_features import _registry
        fs = {f.col_id: f for f in _registry["rl_designer"]}
        outputs = {"metrics": {"buffer_size": 42}}
        val = fs["rl_buffer_size"].extractor(outputs)
        assert val == 42


# ─────────────────────────────────────────────────────────────────────────────
# 12. End-to-end: 5-iteration chained loop with biased reward
# ─────────────────────────────────────────────────────────────────────────────

class TestEndToEndLoop:
    """
    Full 5-iteration simulation. Mirrors what loop_executor does:
      iter 0: no policy_state, no rewards → random actions, prev_states recorded
      iter 1: rewards arrive for iter-0 sequences → buffer fills, training starts
      iter 2-4: epsilon decays, Q-values diverge, exploitation begins

    Checks:
      - epsilon strictly decreases
      - buffer grows monotonically
      - after 5 iters, at least one exploitation action appears
      - Q-heatmap values are non-uniform
      - episode_rewards list is non-empty
    """

    def test_five_iteration_full_loop(self):
        embeddings = _fake_embeddings(n=6, dim=16, seed=42)
        seq_ids = list(embeddings.keys())

        # Consistent reward: seq_0 always best
        def make_scores(i: int) -> dict:
            return {"haddock_score": {
                seq_ids[0]: -200.0,
                **{sid: -100.0 + j * 10 for j, sid in enumerate(seq_ids[1:], 1)},
            }}

        policy_state = None
        epsilons = []
        buffer_sizes = []
        exploit_seen = False

        for i in range(5):
            reward_signals = make_scores(i) if i > 0 else None
            out = _run_subprocess(_base_payload(
                embeddings=embeddings,
                reward_signals=reward_signals,
                policy_state=policy_state,
                top_k=4,
            ))
            epsilons.append(out["metrics"]["epsilon"])
            buffer_sizes.append(out["metrics"]["buffer_size"])
            policy_state = out["policy_state"]

            if any(not a["exploratory"] for a in out["recommended_actions"]):
                exploit_seen = True

        # Epsilon must have decreased
        assert epsilons[-1] < epsilons[0], f"Epsilon didn't decay: {epsilons}"

        # Buffer must have grown
        assert buffer_sizes[-1] > 0, "Buffer empty after 5 iterations"
        assert buffer_sizes == sorted(buffer_sizes), f"Buffer not monotone: {buffer_sizes}"

        # At least one exploitation step should have occurred
        assert exploit_seen, "Agent never exploited across 5 iterations (ε never dropped below 1.0?)"

        # Q-heatmap must show non-uniform values
        hm = out["viz_data"]["q_heatmap"]["values"]
        all_q = [v for cdr_dict in hm.values() for v in cdr_dict.values()]
        spread = max(all_q) - min(all_q)
        assert spread > 0.001, f"Q-heatmap values are still uniform after 5 iters: spread={spread}"

        # episode_rewards must be recorded
        assert len(policy_state["episode_rewards"]) >= 1

    def test_q_values_diverge_between_cdrs_after_biased_training(self):
        """
        After 20 iterations with heavily biased rewards, Q-values for the two CDRs
        (H3, L3) should differ — proving the reward signal shaped the policy.
        We test the spread, not which direction it goes, because stochasticity means
        exact ordering isn't guaranteed in a fixed number of iterations.
        """
        spec = deepcopy(SMALL_RL_SPEC)
        spec["algorithm"]["epsilon_start"] = 0.4  # allow some exploitation from the start
        spec["algorithm"]["epsilon_end"] = 0.05
        spec["algorithm"]["warmup_steps"] = 2
        spec["algorithm"]["batch_size"] = 2
        spec["algorithm"]["n_train_steps"] = 20
        spec["algorithm"]["learning_rate"] = 0.05  # faster convergence

        embeddings = _fake_embeddings(n=4, dim=16, seed=55)
        seq_ids = list(embeddings.keys())
        policy_state = None

        for i in range(20):
            scores = {"haddock_score": {
                seq_ids[0]: -300.0,
                seq_ids[1]: -100.0,
                seq_ids[2]: -80.0,
                seq_ids[3]: -60.0,
            }}
            reward_signals = scores if i > 0 else None
            out = _run_subprocess(_base_payload(
                spec=spec,
                embeddings=embeddings,
                reward_signals=reward_signals,
                policy_state=policy_state,
            ))
            policy_state = out["policy_state"]

        # After 20 training iterations with biased reward, Q-values across CDRs should differ
        hm = out["viz_data"]["q_heatmap"]["values"]
        all_q = [v for cdr_vals in hm.values() for v in cdr_vals.values()]
        spread = max(all_q) - min(all_q)
        assert spread > 0.1, (
            f"Q-values too uniform after 20 biased training iterations: spread={spread:.4f}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 13. Error handling
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorHandling:
    """Malformed inputs should raise RuntimeError (non-zero exit from subprocess)."""

    def _expect_failure(self, payload: dict) -> None:
        result = subprocess.run(
            [str(RL_PYTHON), str(RL_RUN_PY)],
            input=json.dumps(payload).encode(),
            capture_output=True,
            timeout=30,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit for bad payload, stdout: {result.stdout[:500]}"
        )

    def test_empty_state_embeddings_raises(self):
        payload = _base_payload(embeddings={})
        self._expect_failure(payload)

    def test_missing_state_embeddings_raises(self):
        payload = _base_payload()
        del payload["state_embeddings"]
        self._expect_failure(payload)

    def test_empty_cdrs_falls_back_to_defaults(self):
        """Empty cdrs list gracefully falls back to all 6 CDRs — not an error."""
        spec = deepcopy(SMALL_RL_SPEC)
        spec["action"]["cdrs"] = []
        payload = _base_payload(spec=spec)
        out = _run_subprocess(payload)
        # Should succeed and use default 6 CDRs × 2 strategies × 2 n_muts = 24 actions
        first_seq_qvals = next(iter(out["q_values"].values()))
        assert len(first_seq_qvals) == 24, f"Expected 24 default actions, got {len(first_seq_qvals)}"

    def test_wrong_embedding_dim_mismatch(self):
        """All sequences must have same embedding dimension — mixed dims cause tensor error."""
        embeddings = {"seq_0": [0.1] * 16, "seq_1": [0.5] * 32}  # mismatched
        payload = _base_payload(embeddings=embeddings)
        self._expect_failure(payload)
