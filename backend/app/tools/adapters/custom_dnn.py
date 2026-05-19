"""Custom DNN adapter — dispatches to tools/custom_dnn/run.py."""
import json
import re
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess


async def _resolve_model_artifact(artifact: Any) -> dict | None:
    """If artifact is a {__model_id__: uuid} reference, load full weights from DB."""
    if not isinstance(artifact, dict) or "__model_id__" not in artifact:
        return artifact
    model_id = artifact["__model_id__"]
    from app.db.models import TrainedModelRow
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        row = await db.get(TrainedModelRow, model_id)
    if row is None:
        raise ValueError(f"custom_dnn: saved model '{model_id}' not found in registry")
    arch_spec = None
    if row.architecture_spec:
        try:
            arch_spec = json.loads(row.architecture_spec)
        except Exception:
            arch_spec = row.architecture_spec
    return {
        "architecture_spec": arch_spec,
        "embedding_model": row.embedding_model,
        "task": row.task,
        "weights_b64": row.weights_b64,
    }


def _parse_fasta_ids(fasta: str) -> list[tuple[str, str]]:
    """Return [(seq_id, sequence)] from a FASTA string."""
    pairs: list[tuple[str, str]] = []
    header, buf = "", []
    for line in fasta.strip().splitlines():
        line = line.strip()
        if line.startswith(">"):
            if buf:
                pairs.append((header, "".join(buf)))
            parts = line[1:].split()
            header = parts[0] if parts else "seq"
            buf = []
        elif line:
            buf.append(line.upper())
    if buf:
        pairs.append((header, "".join(buf)))
    if not pairs and fasta.strip():
        raw = re.sub(r"[^A-Za-z]", "", fasta).upper()
        if raw:
            pairs.append(("seq_0", raw))
    return pairs


async def _fetch_cached_embeddings(
    fasta: str,
    chain_type: str = "H",
    run_ctx: RunContext | None = None,
) -> dict[str, list[float]]:
    """Look up AbMAP cached embeddings for sequences in the FASTA.

    Returns {seq_id: embedding_vector} for every sequence that has a cached hit.
    Sequences without a cache entry are omitted — run.py will re-embed those via ESM-2.
    """
    from app.tools.abmap_db import AbMAPCache
    cache = AbMAPCache()
    pairs = _parse_fasta_ids(fasta)
    result: dict[str, list[float]] = {}
    for seq_id, seq in pairs:
        hit = await cache.get(seq, chain_type=chain_type)
        if hit and hit.get("embedding"):
            result[seq_id] = hit["embedding"]
    if result and run_ctx:
        await run_ctx.alog(
            f"Loaded {len(result)}/{len(pairs)} embeddings from AbMAP cache"
        )
    return result


async def _build_upstream_inputs(
    upstream_nodes: list[dict],
    spec: dict,
    inputs: dict,
    sequences_raw: str,
    run_ctx: "RunContext",
) -> "tuple[dict[str, list[float]] | None, dict]":
    """Resolve UpstreamInput nodes → combined {seq_id: concat_vec}, updated spec with slices.

    Each UpstreamInput node references a specific pipeline port (embedding_input,
    embedding_input_2, etc.).  The adapter normalizes each port's value, concatenates
    the vectors per sequence in node order, and injects slice_start / slice_end into
    each node's params so run.py can slice the concatenated tensor correctly.
    """
    # Gather (node_id, port, normalized_embedding) in the order nodes appear in the spec
    gathered: list[tuple[str, dict[str, list[float]]]] = []
    for unode in upstream_nodes:
        port = str(unode.get("params", {}).get("port", "embedding_input"))
        raw  = inputs.get(port)
        emb  = _normalize_embedding_input(raw, sequences_raw)
        if emb:
            gathered.append((unode["id"], emb))
        else:
            await run_ctx.alog(
                f"UpstreamInput '{unode['id']}' (port={port}): no embedding found — will be skipped"
            )

    if not gathered:
        return None, spec

    if len(gathered) == 1:
        nid, emb = gathered[0]
        dim = len(next(iter(emb.values())))
        new_nodes = [
            {**n, "params": {**n.get("params", {}), "slice_start": 0, "slice_end": dim}}
            if n["id"] == nid else n
            for n in spec.get("nodes", [])
        ]
        await run_ctx.alog(f"UpstreamInput '{nid}': {dim}d — single input")
        return emb, {**spec, "nodes": new_nodes}

    # Multiple sources → intersect seq_ids, concatenate vectors
    common_ids: set[str] = set(gathered[0][1].keys())
    for _, emb in gathered[1:]:
        common_ids &= set(emb.keys())
    if not common_ids:
        await run_ctx.alog("UpstreamInput: no overlapping seq IDs across sources — using first only")
        nid, emb = gathered[0]
        dim = len(next(iter(emb.values())))
        new_nodes = [
            {**n, "params": {**n.get("params", {}), "slice_start": 0, "slice_end": dim}}
            if n["id"] == nid else n
            for n in spec.get("nodes", [])
        ]
        return emb, {**spec, "nodes": new_nodes}

    ordered_ids = sorted(common_ids)
    combined: dict[str, list[float]] = {sid: [] for sid in ordered_ids}
    offset = 0
    slice_map: dict[str, tuple[int, int]] = {}
    for nid, emb in gathered:
        dim = len(next(iter(emb.values())))
        slice_map[nid] = (offset, offset + dim)
        for sid in ordered_ids:
            combined[sid].extend(emb[sid])
        offset += dim

    dims_str = " + ".join(f"{s[1]-s[0]}d" for s in slice_map.values())
    await run_ctx.alog(
        f"Concatenating {len(gathered)} upstream inputs: {dims_str} = {offset}d "
        f"({len(ordered_ids)} sequences)"
    )

    new_nodes = []
    for node in spec.get("nodes", []):
        if node.get("type") == "UpstreamInput" and node["id"] in slice_map:
            start, end = slice_map[node["id"]]
            node = {**node, "params": {**node.get("params", {}), "slice_start": start, "slice_end": end}}
        new_nodes.append(node)

    return combined, {**spec, "nodes": new_nodes}


def _normalize_embedding_input(
    raw: Any,
    sequences_raw: str = "",
) -> "dict[str, list[float]] | None":
    """Normalize any embedding format coming from upstream tools to {seq_id: [float...]} dict.

    Embedding tools output either:
      • {seq_id: [float...]}  — already correct (AbMAP cache, etc.)
      • [[float...], ...]     — batch list from abmap/esm/cheap
      • [float...]            — single-sequence flat list
    """
    if not raw:
        return None

    if isinstance(raw, dict):
        if any(isinstance(v, list) for v in raw.values()):
            return raw  # type: ignore[return-value]
        return None

    if not isinstance(raw, list) or len(raw) == 0:
        return None

    pairs = _parse_fasta_ids(sequences_raw) if sequences_raw else []

    # 2D: list of vectors [[float...], ...]
    if isinstance(raw[0], list):
        result: dict[str, list[float]] = {}
        for i, vec in enumerate(raw):
            sid = pairs[i][0] if i < len(pairs) else f"seq_{i}"
            result[sid] = vec
        return result

    # 1D: single vector [float...]
    if isinstance(raw[0], (int, float)):
        sid = pairs[0][0] if pairs else "seq_0"
        return {sid: raw}

    return None


class CustomDNNAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        architecture_spec = inputs.get("architecture_spec")
        labels = inputs.get("labels")
        model_artifact = await _resolve_model_artifact(inputs.get("model_artifact"))
        sequences_raw: str = str(inputs.get("sequences") or "")
        # Normalize embedding_input(s): upstream tools emit lists; run.py expects {seq_id: [...]}
        emb1 = _normalize_embedding_input(inputs.get("embedding_input"), sequences_raw)
        emb2 = _normalize_embedding_input(inputs.get("embedding_input_2"), sequences_raw)

        if emb1 and emb2:
            common_ids = set(emb1.keys()) & set(emb2.keys())
            if common_ids:
                embedding_input: dict | None = {sid: emb1[sid] + emb2[sid] for sid in common_ids}
                dim1 = len(next(iter(emb1.values())))
                dim2 = len(next(iter(emb2.values())))
                await run_ctx.alog(
                    f"Concatenating embeddings: {dim1}d + {dim2}d = {dim1 + dim2}d "
                    f"({len(common_ids)} sequences)"
                )
            else:
                embedding_input = emb1
                await run_ctx.alog("embedding_input_2 has no overlapping seq IDs with embedding_input — using embedding_input only")
        else:
            embedding_input = emb1 or emb2

        effective_spec: dict | None = architecture_spec or (model_artifact.get("architecture_spec") if model_artifact else None)

        # Resolve UpstreamInput nodes: build combined embedding + inject slice params
        if effective_spec:
            upstream_nodes = [n for n in effective_spec.get("nodes", []) if n.get("type") == "UpstreamInput"]
            if upstream_nodes:
                upstream_emb, effective_spec = await _build_upstream_inputs(
                    upstream_nodes, effective_spec, inputs, sequences_raw, run_ctx
                )
                if upstream_emb:
                    embedding_input = upstream_emb  # overrides any normalized embedding_input

        if effective_spec:
            nodes = effective_spec.get("nodes", [])
            layer_types = [n.get("type") for n in nodes]
            has_transformer = any(t in ("TransformerEncoder", "MultiheadAttention") for t in layer_types)
            has_recurrent = any(t in ("LSTM", "GRU") for t in layer_types)
            arch_label = "Transformer" if has_transformer else "Recurrent" if has_recurrent else "MLP"
            await run_ctx.alog(f"Custom DNN · {arch_label} · {len(nodes)} layers")
        else:
            await run_ctx.alog("Custom DNN")

        if inputs.get("committee_mode"):
            n_ranks = sum(1 for k in ("scores_rank_1","scores_rank_2","scores_rank_3","scores_rank_4") if inputs.get(k))
            await run_ctx.alog(f"Custom DNN · committee mode · M={inputs.get('n_committee',5)} · ranks={n_ranks}")
        else:
            has_labels = bool(labels) and (
                (isinstance(labels, dict) and len(labels) > 0)
                or (isinstance(labels, list) and len(labels) > 0)
            )
            mode = "inference" if (model_artifact is not None and not has_labels) else "training"
            await run_ctx.alog(f"Mode: {mode}")

        # ── Resolve embeddings ─────────────────────────────────────────────────
        if embedding_input and isinstance(embedding_input, dict) and len(embedding_input) > 0:
            # Direct embedding_input wired from upstream tool — use as-is
            await run_ctx.alog(
                f"Using {len(embedding_input)} pre-computed embeddings from upstream node"
            )
        elif sequences_raw:
            # Try AbMAP cache before falling back to ESM-2
            cached = await _fetch_cached_embeddings(sequences_raw, run_ctx=run_ctx)
            if cached:
                embedding_input = cached
            else:
                emb_model = str(inputs.get("embedding_model", "8M"))
                await run_ctx.alog(
                    f"No cached embeddings found — embedding with ESM-2 {emb_model} "
                    f"(first run downloads weights)…"
                )

        _PASS_THROUGH = {
            "sequences", "labels",
            "epochs", "learning_rate", "task", "num_classes",
            "embedding_model", "loss_fn",
            # committee / ML-DE
            "committee_mode", "n_committee", "kappa_epi", "kappa_conf",
            "lower_is_better", "top_k", "batch_size",
            "scores_rank_1", "scores_rank_2", "scores_rank_3", "scores_rank_4",
            "accumulated_dataset",
        }
        runner_inputs: dict[str, Any] = {k: v for k, v in inputs.items() if k in _PASS_THROUGH}

        # Forward pre-computed embedding dicts for committee mode
        for port in ("embeddings", "candidate_embeddings"):
            raw = inputs.get(port)
            if raw:
                norm = _normalize_embedding_input(raw, sequences_raw)
                if norm:
                    runner_inputs[port] = norm
        # Use effective_spec (may have UpstreamInput slices injected)
        if effective_spec:
            runner_inputs["architecture_spec"] = effective_spec
        if model_artifact is not None:
            runner_inputs["model_artifact"] = model_artifact
            # Propagate spec/task/embedding_model from saved model when node params are absent
            if not runner_inputs.get("architecture_spec") and model_artifact.get("architecture_spec"):
                runner_inputs["architecture_spec"] = model_artifact["architecture_spec"]
            if not runner_inputs.get("task") and model_artifact.get("task"):
                runner_inputs["task"] = model_artifact["task"]
            if not runner_inputs.get("embedding_model") and model_artifact.get("embedding_model"):
                runner_inputs["embedding_model"] = model_artifact["embedding_model"]
        if embedding_input:
            runner_inputs["embedding_input"] = embedding_input

        outputs = await run_tool_subprocess(
            tool_id="custom_dnn",
            inputs=runner_inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
        )

        n_preds = len(outputs.get("predictions") or [])
        await run_ctx.alog(f"Done — {n_preds} predictions returned")
        return outputs
