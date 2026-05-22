"""RCC-MLDE adapter — runs tools/rcc_mlde/run.py using the backend venv (sklearn+numpy).

Uses RCC_MLDE_PYTHON env var or falls back to the backend venv which already
has sklearn 1.8 + numpy 2.4 installed.
"""
import os
import sys
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess

_BACKEND_VENV = Path(__file__).resolve().parents[3] / ".venv" / "bin" / "python"
_RCC_MLDE_PYTHON = Path(
    os.getenv("RCC_MLDE_PYTHON", str(_BACKEND_VENV))
)


def _coerce_scores(raw: Any) -> dict[str, float] | None:
    """Accept {str: float}, HADDOCK3 summary dict, or {str: {"score":float}} dicts.

    Handles:
    - {seq_id: float} — direct mapping
    - {"score": -42.5, "vdw": ..., ...} — HADDOCK3 summary for a single sequence
      → wrapped as {"default": score_value}
    - {seq_id: {"score": float, ...}} — per-sequence HADDOCK3 output
    - float — single scalar → {"default": value}
    """
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        return {"seq_0": float(raw)}
    if not isinstance(raw, dict):
        return None
    # HADDOCK3 summary: top-level "score" key means it's a single-sequence result
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
    """Accept any embedding format and return {seq_id: [float]}.

    Handles:
    - Standard format {n, results: [{vh, vl, emb_vh, emb_vl}]} — new standard
    - dict {seq_id: [float]} — pre-keyed dict
    - list of floats [float, ...] — single vector → {"seq_0": vec}
    - list of lists [[float,...], ...] — batch → {"seq_i": vec}
    """
    if not raw:
        return None

    # New standard embedding format
    if isinstance(raw, dict) and "results" in raw:
        out: dict[str, list[float]] = {}
        for i, entry in enumerate(raw["results"]):
            emb = entry.get("emb_vh") or entry.get("emb_vl")
            if emb:
                seq_id = entry.get("vh") or f"seq_{i}"
                out[str(seq_id)] = emb
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
        if isinstance(raw[0], list) and raw[0] and isinstance(raw[0][0], (int, float)):
            return {f"seq_{i}": v for i, v in enumerate(raw)}
    return None


class RCCMLDEAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        # If a candidate sequence string is provided (wired from cdr_mutator.heavy_chain),
        # re-key candidate_embeddings from the generic "seq_0" to the actual sequence so
        # downstream compute nodes (feasibility_filter) can look up acquisition scores by
        # sequence identity rather than an opaque index.
        candidate_sequence = str(inputs.get("candidate_sequence") or "").strip() or None

        embeddings        = _coerce_embeddings(inputs.get("embeddings"))
        candidate_emb     = _coerce_embeddings(inputs.get("candidate_embeddings"))
        if candidate_sequence and candidate_emb and list(candidate_emb.keys()) == ["seq_0"]:
            candidate_emb = {candidate_sequence: candidate_emb["seq_0"]}

        scores_rank_1     = _coerce_scores(inputs.get("scores_rank_1"))
        scores_rank_2     = _coerce_scores(inputs.get("scores_rank_2"))
        scores_rank_3     = _coerce_scores(inputs.get("scores_rank_3"))
        scores_rank_4     = _coerce_scores(inputs.get("scores_rank_4"))
        model_artifact_in = inputs.get("model_artifact")

        if embeddings is None and model_artifact_in is None:
            raise ValueError("rcc_mlde: embeddings (or model_artifact) is required")
        if scores_rank_1 is None and model_artifact_in is None:
            raise ValueError("rcc_mlde: scores_rank_1 is required for training")

        n_ranks = sum(1 for s in [scores_rank_1, scores_rank_2, scores_rank_3, scores_rank_4] if s)
        # Explicit mode param takes priority; fall back to wiring inference
        explicit_mode = str(inputs.get("mode") or "").strip().lower()
        if explicit_mode == "score":
            mode = "inference"
        elif explicit_mode == "train":
            mode = "train+score"
        else:
            mode = "inference" if model_artifact_in and not scores_rank_1 else "train+score"
        await run_ctx.alog(
            f"RCC-MLDE: mode={mode}, ranks={n_ranks}, "
            f"n_train={len(embeddings) if embeddings else 0}, "
            f"n_candidates={len(candidate_emb) if candidate_emb else (len(embeddings) if embeddings else 0)}"
        )

        accumulated = inputs.get("accumulated_dataset")

        payload: dict[str, Any] = {
            "n_committee":    int(inputs.get("n_committee", 5)),
            "model_type":     str(inputs.get("model_type", "ridge")),
            "kappa_epi":      float(inputs.get("kappa_epi", 2.0)),
            "kappa_conf":     float(inputs.get("kappa_conf", 0.5)),
            "top_k":          int(inputs.get("top_k", 20)),
            "lower_is_better": bool(inputs.get("lower_is_better", True)),
            "task":           str(inputs.get("task", "regression")),
        }
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
            tool_id="rcc_mlde",
            inputs=payload,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=str(_RCC_MLDE_PYTHON),
        )

        top = outputs.get("top_sequences", [])
        metrics = outputs.get("metrics", {})
        await run_ctx.alog(
            f"Done — {metrics.get('n_candidates', 0)} scored, "
            f"top-{len(top)}: {top[:3]}"
        )
        return outputs
