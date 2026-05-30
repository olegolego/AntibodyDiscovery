"""RL Designer adapter — runs tools/rl_designer/run.py using the custom_dnn venv
(PyTorch + scikit-learn are already installed there).
"""
import json
import os
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess

# Re-use the custom_dnn venv which already has torch + sklearn
_CUSTOM_DNN_VENV = Path(__file__).resolve().parents[4] / "tools" / "custom_dnn" / ".venv" / "bin" / "python"
_RL_PYTHON = Path(os.getenv("RL_DESIGNER_PYTHON", str(_CUSTOM_DNN_VENV)))


def _coerce_embeddings(raw: Any) -> dict[str, list[float]] | None:
    """Accept any embedding format → {seq_id: [float, ...]}.

    Mirrors the same helper in rcc_mlde.py to handle all upstream embedding
    tool output formats (new standard, pre-keyed dict, list variants).
    """
    if not raw:
        return None
    if isinstance(raw, dict) and "results" in raw:
        out: dict[str, list[float]] = {}
        for i, entry in enumerate(raw["results"]):
            emb = entry.get("emb_vh") or entry.get("emb_vl")
            if emb and isinstance(emb, list):
                sid = entry.get("vh") or f"seq_{i}"
                out[str(sid)] = emb
        return out or None
    if isinstance(raw, dict):
        result: dict[str, list[float]] = {}
        for k, v in raw.items():
            if isinstance(v, list) and v and isinstance(v[0], (int, float)):
                result[str(k)] = v
        return result or None
    if isinstance(raw, list) and raw:
        if isinstance(raw[0], (int, float)):
            return {"seq_0": raw}
        if isinstance(raw[0], list):
            return {f"seq_{i}": v for i, v in enumerate(raw)}
        if isinstance(raw[0], dict):
            # e.g. AbMAP results list: [{vh: str, emb_vh: [float...], ...}, ...]
            out2: dict[str, list[float]] = {}
            for i, entry in enumerate(raw):
                emb = entry.get("emb_vh") or entry.get("emb_vl") or entry.get("embedding")
                if emb and isinstance(emb, list) and emb and isinstance(emb[0], (int, float)):
                    sid = entry.get("vh") or entry.get("vl") or f"seq_{i}"
                    out2[str(sid)] = emb
            return out2 or None
    return None


def _coerce_scores(raw: Any) -> dict[str, float] | None:
    """Accept {seq_id: float} or HADDOCK-style score dicts."""
    if raw is None:
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
            s = v.get("score") or v.get("binding_energy") or v.get("total_energy")
            if s is not None:
                out[str(k)] = float(s)
    return out or None


# Score port names we'll try to collect as reward signals automatically
_REWARD_PORTS = (
    "haddock_score", "docking_score", "score", "plddt", "mean_plddt",
    "solubility_score", "acquisition_score", "sap_score",
    "heavy_solubility", "light_solubility",
)


class RLDesignerAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        # ── Parse rl_spec ──────────────────────────────────────────────────────
        rl_spec = inputs.get("rl_spec")
        if isinstance(rl_spec, str):
            rl_spec = json.loads(rl_spec)
        if not rl_spec:
            raise ValueError("rl_designer: rl_spec is required")

        # ── Normalise state_embeddings ─────────────────────────────────────────
        state_embeddings = _coerce_embeddings(inputs.get("state_embeddings"))
        if not state_embeddings:
            raise ValueError("rl_designer: state_embeddings is empty or unrecognised format")

        # ── Collect reward signals ────────────────────────────────────────────
        reward_signals: dict[str, dict[str, float]] = {}
        # Explicit reward_signals port
        raw_rs = inputs.get("reward_signals")
        if isinstance(raw_rs, dict):
            for port, scores in raw_rs.items():
                coerced = _coerce_scores(scores)
                if coerced:
                    reward_signals[port] = coerced
        # Auto-detect common score ports from merged inputs
        for port in _REWARD_PORTS:
            if port in inputs and port not in reward_signals:
                coerced = _coerce_scores(inputs[port])
                if coerced:
                    reward_signals[port] = coerced

        # ── Log summary ───────────────────────────────────────────────────────
        ac = rl_spec.get("action", {})
        n_cdrs = len(ac.get("cdrs") or ["H1", "H2", "H3", "L1", "L2", "L3"])
        n_strats = len(ac.get("strategies") or ["random", "blosum62", "conservative", "sapiens"])
        n_muts = len(ac.get("n_mutations_choices") or [1, 2, 3])
        n_actions = n_cdrs * n_strats * n_muts
        await run_ctx.alog(
            f"RL Designer: |A|={n_actions}, N={len(state_embeddings)} sequences, "
            f"reward_ports={list(reward_signals.keys())}, "
            f"mode={inputs.get('mode', 'train_and_act')}"
        )

        payload: dict[str, Any] = {
            "rl_spec":          rl_spec,
            "state_embeddings": state_embeddings,
            "mode":             str(inputs.get("mode", "train_and_act")),
            "top_k":            int(inputs.get("top_k", 4)),
        }
        if reward_signals:
            payload["reward_signals"] = reward_signals
        policy_state = inputs.get("policy_state")
        if policy_state:
            payload["policy_state"] = policy_state

        outputs = await run_tool_subprocess(
            tool_id="rl_designer",
            inputs=payload,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=str(_RL_PYTHON),
        )

        actions = outputs.get("recommended_actions", [])
        metrics = outputs.get("metrics", {})
        top = actions[0] if actions else {}
        await run_ctx.alog(
            f"RL Done — ε={metrics.get('epsilon', 0):.3f}, "
            f"buffer={metrics.get('buffer_size', 0)}, "
            f"loss={metrics.get('mean_loss', 0):.4f}, "
            f"top: {top.get('cdr', '?')}/{top.get('strategy', '?')} "
            f"({'explore' if top.get('exploratory') else 'exploit'})"
        )
        return outputs
