"""Shared utilities for all embedding tool adapters.

parse_sequences() normalises any canvas input into the standard
[{"vh": str, "vl": str|None}, ...] format that all embedding tools accept.
"""
from typing import Any

from app.tools.fasta_utils import is_multi_fasta, parse_fasta


def clean_seq(seq: str) -> str:
    """Remove FASTA header, whitespace, and common non-standard residues."""
    if "/" in seq:
        seq = seq.split("/")[0]
    if "X" in seq:
        seq = seq.replace("X", "A")
    lines = [l.strip() for l in seq.splitlines() if not l.startswith(">")]
    return "".join(lines).replace(" ", "").upper().strip()


def parse_sequences(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    """Return list of {vh, vl} dicts from any upstream canvas input.

    Accepted upstream formats:
      • sequences: [{vh, vl}, ...]     — new batch standard (pass-through)
      • sequences: {vh, vl}            — new single standard (wrapped)
      • vh / vl                        — explicit chain fields (single pair)
      • heavy_chain / light_chain      — legacy chain fields (single pair)
      • sequence                       — legacy single string (used as vh)
      • candidate_sequences: [str, ...] — MLDE candidate list (VH only)
      • Multi-FASTA in heavy_chain     — batch of VH sequences

    When VL is absent or empty, the entry's vl is None.
    """
    # --- New standard: sequences list/dict ---
    seqs = inputs.get("sequences")
    if seqs is not None:
        if isinstance(seqs, dict) and "variants" in seqs:
            # Standard batch token {n, variants: [...]} — extract the list
            seqs = seqs["variants"]
        elif isinstance(seqs, dict):
            # Single {vh, vl} dict — wrap
            seqs = [seqs]
        if isinstance(seqs, list) and seqs:
            # Already in the right format; just clean
            result = []
            for entry in seqs:
                if isinstance(entry, str):
                    # Plain string list → treat each as VH
                    vh = clean_seq(entry)
                    result.append({"vh": vh, "vl": None})
                else:
                    vh = clean_seq(str(entry.get("vh") or ""))
                    vl_raw = str(entry.get("vl") or "").strip()
                    result.append({"vh": vh, "vl": clean_seq(vl_raw) if vl_raw else None})
            return [e for e in result if e["vh"]]

    # --- Candidate sequence list (VH only) ---
    candidates = inputs.get("candidate_sequences")
    if isinstance(candidates, list) and candidates:
        return [{"vh": clean_seq(str(s)), "vl": None} for s in candidates if s]

    # --- Explicit chain fields ---
    # vh/heavy_chain may arrive as a list (e.g. wired from cdr_mutator.heavy_chain_variants)
    vh_raw = inputs.get("vh") or inputs.get("heavy_chain") or ""
    if isinstance(vh_raw, list):
        return [{"vh": clean_seq(str(s)), "vl": None} for s in vh_raw if s]
    raw_vh = str(vh_raw).strip()
    raw_vl = str(inputs.get("vl") or inputs.get("light_chain") or "").strip()
    # sequence port may also arrive as a list (wired from e.g. cdr_mutator.heavy_chain_variants)
    seq_raw = inputs.get("sequence") or ""
    if isinstance(seq_raw, list):
        return [{"vh": clean_seq(str(s)), "vl": None} for s in seq_raw if s]
    raw_seq = str(seq_raw).strip()

    # Multi-FASTA heavy chain → batch of VH-only pairs
    if is_multi_fasta(raw_vh):
        entries = parse_fasta(raw_vh)
        vl_entries = parse_fasta(raw_vl) if raw_vl else []
        result = []
        for i, (_, vh_seq) in enumerate(entries):
            vh = clean_seq(vh_seq)
            vl = clean_seq(vl_entries[i][1]) if i < len(vl_entries) else None
            if vh:
                result.append({"vh": vh, "vl": vl or None})
        return result

    # Single pair
    vh = clean_seq(raw_vh or raw_seq)
    vl = clean_seq(raw_vl) if raw_vl else None
    if not vh:
        raise ValueError(
            "Embedding tool requires a sequence. "
            "Provide 'vh', 'heavy_chain', 'sequence', or 'sequences'."
        )
    return [{"vh": vh, "vl": vl}]


def results_to_emb_vh_list(embedding_output: dict[str, Any]) -> list[list[float]]:
    """Extract [emb_vh, ...] from the standard embedding output.

    Convenience helper for downstream tools that only need the VH embedding
    (e.g. rcc_mlde, custom_dnn operating on VH-only pipelines).
    """
    results = embedding_output.get("results") or []
    return [r.get("emb_vh") or [] for r in results]


def results_to_seq_emb_dict(
    embedding_output: dict[str, Any],
    chain: str = "vh",
) -> dict[str, list[float]]:
    """Convert standard embedding output to {seq_id: [float]} for downstream ML tools.

    chain: "vh" or "vl"
    seq_id is the sequence string itself (unique key).
    """
    results = embedding_output.get("results") or []
    emb_key = f"emb_{chain}"
    out: dict[str, list[float]] = {}
    for i, r in enumerate(results):
        seq = r.get(chain) or f"seq_{i}"
        emb = r.get(emb_key)
        if emb:
            out[seq] = emb
    return out
