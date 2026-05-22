"""Tool Feature Registry — extracts scalar features from tool node outputs for dataset export.

Design
------
Two-tier extraction:

1. Generic scalar walker (extract_scalars):
   Automatically walks any tool's output dict and pulls every int/float/bool/short-string
   value, naming columns as {tool_id}_{key} or {tool_id}_{key}_{subkey} for nested dicts.
   No registration required — new tools work automatically.

2. Computed registry (FeatureSpec / register):
   For features that require computation from lists or multiple keys
   (e.g. mean pLDDT from a list, total mutations = VH + VL).
   Keep this small — only add an entry when auto-extraction genuinely can't do the job.

Usage
-----
    from app.core.tool_features import extract_features, all_features_for_pipeline

    row_data = extract_features("haddock3", node_outputs)
    col_specs = all_features_for_pipeline(["immunebuilder", "haddock3"])

Adding a new tool
-----------------
Usually nothing needed — scalars are captured automatically.
Only add a FeatureSpec (at the bottom) when you need a value computed from a list
(mean, percentage, count) that won't appear in the output as a standalone scalar.
See docs/adding-tools.md § 7.5.

Column ID convention: {tool_id}_{key}  e.g. "deepsp_sap_score", "netsolp_heavy_solubility"
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

_ARTIFACT = "__artifact__"

# Maximum length for text column values (longer strings are skipped)
_MAX_STR_LEN = 500

# Keys that are always large blobs, embeddings, or non-informative — never auto-extracted.
# These are tool-agnostic: the same key name means "large blob" across all tools.
_SKIP_KEYS: frozenset[str] = frozenset({
    # PDB / structure blobs
    "structure", "fixed_structure", "hydrated_structure", "best_complex",
    "pdb", "pdb_data", "model_pdb",
    # Embeddings (always large lists)
    "embedding", "embeddings", "candidate_embeddings", "residue_embeddings",
    "pretrain_dataset",
    # Sequences — already stored in DatasetEntry.heavy_chain / light_chain
    "heavy_chain", "light_chain", "next_heavy_chain", "next_light_chain",
    # Variant bundles (large nested dicts, one per candidate)
    "variant_1", "variant_2", "variant_3", "variant_4", "variant_5",
    "variant_6", "variant_7", "variant_8", "variant_9", "variant_10",
    "heavy_chain_variants", "light_chain_variants",
    "feasible_variants", "liability_report",
    # MLDE per-sequence dicts (one float per candidate sequence — too wide for columns)
    "acquisition_scores", "mean_predictions", "epistemic_uncertainty",
    "conformational_uncertainty", "rank_predictions",
    # Model weights / architecture
    "model_artifact", "weights_b64", "architecture_spec", "committees",
    # Control / debug
    "stdout", "error", "result",
    # Local filesystem paths — not meaningful outside the machine that ran the tool
    "artifact_dir", "output_dir", "work_dir", "run_dir", "tmp_dir",
    # Per-residue arrays (handled by computed registry below)
    "plddt", "pae", "error_estimates",
    # Other large complex blobs
    "cdr_residues", "mutation_report", "top_scores", "complex_pdbs",
    "per_rank", "history",
})

# Dict keys whose children should be promoted to the top-level prefix.
# e.g.  haddock3.scores.score  →  haddock3_score  (not haddock3_scores_score)
# Only keys that are consistently "thin wrapper dicts" for scalars belong here.
_TRANSPARENT_WRAPPERS: frozenset[str] = frozenset({
    "scores", "metadata", "report", "summary", "water_count", "energy_decomposition",
})


# ── Coercion helpers ───────────────────────────────────────────────────────────

def _safe(v: Any) -> float | None:
    if v is None or v == _ARTIFACT:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_round(v: Any, ndigits: int = 4) -> float | None:
    f = _safe(v)
    return round(f, ndigits) if f is not None else None


def _is_scalar(v: Any) -> bool:
    if v is None or v == _ARTIFACT:
        return False
    if isinstance(v, bool):
        return True
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        return 0 < len(v) <= _MAX_STR_LEN
    return False


def _coerce(v: Any) -> Any:
    """Normalize a scalar for storage: floats rounded, ints kept, strings stripped."""
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return v.strip()
    return v


# ── Generic scalar walker ──────────────────────────────────────────────────────

def extract_scalars(tool_id: str, outputs: dict) -> dict[str, Any]:
    """Auto-extract every scalar from *outputs*, two levels deep.

    Top-level scalars  →  {tool_id}_{key}
    Nested dict value  →  {tool_id}_{key}_{subkey}  (or {tool_id}_{subkey} for wrappers)
    Lists / blobs / _SKIP_KEYS are silently ignored.
    """
    result: dict[str, Any] = {}

    for k, v in outputs.items():
        if k in _SKIP_KEYS:
            continue

        if _is_scalar(v):
            result[f"{tool_id}_{k}"] = _coerce(v)

        elif isinstance(v, dict) and v:
            # Transparent wrappers: promote children directly under tool_id
            sub_prefix = tool_id if k in _TRANSPARENT_WRAPPERS else f"{tool_id}_{k}"
            for sk, sv in v.items():
                if sk in _SKIP_KEYS:
                    continue
                if _is_scalar(sv):
                    result[f"{sub_prefix}_{sk}"] = _coerce(sv)

    return result


# ── Computed FeatureSpec registry (keep small) ─────────────────────────────────

@dataclass
class FeatureSpec:
    col_id: str
    label: str
    col_type: str                     # "number" | "text" | "boolean"
    extractor: Callable[[dict], Any]  # (outputs) → value or None


_registry: dict[str, list[FeatureSpec]] = {}
_prefix_registry: list[tuple[str, list[FeatureSpec]]] = []


def register(tool_id: str, specs: list[FeatureSpec]) -> None:
    _registry[tool_id] = specs


def register_prefix(prefix: str, specs: list[FeatureSpec]) -> None:
    _prefix_registry.append((prefix, specs))


def get_features(tool_id: str) -> list[FeatureSpec]:
    if tool_id in _registry:
        return _registry[tool_id]
    best: tuple[str, list[FeatureSpec]] | None = None
    for prefix, specs in _prefix_registry:
        if tool_id.startswith(prefix):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, specs)
    return best[1] if best else []


def extract_features(tool_id: str, outputs: dict) -> dict[str, Any]:
    """Full extraction: auto-scalars first, then computed registry (can override).

    Returns {col_id: value} with None values omitted.
    """
    result = extract_scalars(tool_id, outputs)

    for spec in get_features(tool_id):
        try:
            val = spec.extractor(outputs)
            if val is not None:
                result[spec.col_id] = val
        except Exception:
            pass

    return result


def all_features_for_pipeline(tool_ids: list[str]) -> list[FeatureSpec]:
    """Deduped list of computed FeatureSpecs for the given tool ids.

    Note: auto-scalar columns are discovered at extraction time, not enumerated
    ahead of time, so they don't appear here. Use this only to pre-declare column
    types for computed features.
    """
    seen: set[str] = set()
    out: list[FeatureSpec] = []
    for tid in tool_ids:
        for spec in get_features(tid):
            if spec.col_id not in seen:
                seen.add(spec.col_id)
                out.append(spec)
    return out


# ── Computed registry entries ──────────────────────────────────────────────────
# Add a FeatureSpec ONLY when the value cannot be auto-extracted from a scalar key.
# Common cases: mean/percentage/count computed from a LIST output.

# ImmuneBuilder: error_estimates is a list → compute mean RMSD and count structures
register("immunebuilder", [
    FeatureSpec(
        "immunebuilder_mean_rmsd", "IB Mean RMSD (Å)", "number",
        lambda o: (
            lambda errs: _safe_round(sum(errs) / len(errs), 3) if errs else None
        )([v for v in (o.get("error_estimates") or []) if isinstance(v, (int, float))]),
    ),
    FeatureSpec(
        "immunebuilder_num_structures", "IB Structures", "number",
        lambda o: (
            lambda n: n if n > 0 else None
        )(sum(1 for i in range(1, 5) if o.get(f"structure_{i}") not in (None, _ARTIFACT))),
    ),
])

# ESMFold: plddt is a list → compute statistics
register("esmfold", [
    FeatureSpec(
        "esmfold_mean_plddt", "ESMFold Mean pLDDT", "number",
        lambda o: (
            lambda pl: _safe_round(sum(pl) / len(pl), 1) if pl else None
        )([v for v in (o.get("plddt") or []) if isinstance(v, (int, float))]),
    ),
    FeatureSpec(
        "esmfold_high_conf_pct", "ESMFold High Conf %", "number",
        lambda o: (
            lambda pl: _safe_round(100 * sum(1 for v in pl if v >= 70) / len(pl), 1) if pl else None
        )([v for v in (o.get("plddt") or []) if isinstance(v, (int, float))]),
    ),
    FeatureSpec(
        "esmfold_num_residues", "ESMFold Residues", "number",
        lambda o: (
            lambda pl: len(pl) if pl else None
        )([v for v in (o.get("plddt") or []) if isinstance(v, (int, float))]),
    ),
])

# AlphaFold: plddt is a dict (auto-extracted as alphafold_monomer_mean_plddt etc.)
# but the key is nested under "plddt" which is in _SKIP_KEYS, so we need registry.
register("alphafold_monomer", [
    FeatureSpec(
        "alphafold_monomer_mean_plddt", "AlphaFold Mean pLDDT", "number",
        lambda o: _safe_round((o.get("plddt") or {}).get("mean_plddt"), 1),
    ),
    FeatureSpec(
        "alphafold_monomer_high_conf_pct", "AlphaFold High Conf %", "number",
        lambda o: _safe_round((o.get("plddt") or {}).get("high_confidence_pct"), 1),
    ),
    FeatureSpec(
        "alphafold_monomer_very_high_conf_pct", "AlphaFold Very High Conf %", "number",
        lambda o: _safe_round((o.get("plddt") or {}).get("very_high_confidence_pct"), 1),
    ),
    FeatureSpec(
        "alphafold_monomer_num_residues", "AlphaFold Residues", "number",
        lambda o: _safe((o.get("plddt") or {}).get("sequence_length")),
    ),
])

# HADDOCK prefix: catches haddock3, haddock_r1, haddock_r2, etc.
# scores dict is transparent → auto-extracted as haddock3_score etc.
# but we also need the prefix to fire for haddock_r1/r2 variants.
# Auto-extraction handles the actual values; the prefix entry just ensures
# all_features_for_pipeline() knows haddock variants are covered.
# (No computed specs needed — everything in scores{} is a scalar.)

# ProteinMPNN: scores is a list → compute mean and best
register("proteinmpnn", [
    FeatureSpec(
        "proteinmpnn_num_sequences", "MPNN Sequences", "number",
        lambda o: (lambda n: n if n > 0 else None)(
            len(o.get("sequence") or []) if isinstance(o.get("sequence"), list) else 0
        ),
    ),
    FeatureSpec(
        "proteinmpnn_mean_score", "MPNN Mean Score", "number",
        lambda o: (
            lambda sc: _safe_round(sum(sc) / len(sc), 4) if sc else None
        )([v for v in (o.get("scores") or []) if isinstance(v, (int, float))]),
    ),
    FeatureSpec(
        "proteinmpnn_best_score", "MPNN Best Score", "number",
        lambda o: (
            lambda sc: _safe_round(min(sc), 4) if sc else None
        )([v for v in (o.get("scores") or []) if isinstance(v, (int, float))]),
    ),
])

# BioPhi: compute total from the two separate mutation counts
register("biophi", [
    FeatureSpec(
        "biophi_total_mutations", "BioPhi Total Mutations", "number",
        lambda o: (
            lambda vh, vl: vh + vl if vh is not None and vl is not None else None
        )(_safe(o.get("heavy_mutations")), _safe(o.get("light_mutations"))),
    ),
])

# MEGADOCK: top_scores is a list → count and best score
register("megadock", [
    FeatureSpec(
        "megadock_num_poses", "MEGADOCK Poses", "number",
        lambda o: (lambda n: n if n > 0 else None)(len(o.get("top_scores") or [])),
    ),
    FeatureSpec(
        "megadock_best_score", "MEGADOCK Best Score", "number",
        lambda o: _safe_round(
            (o.get("metadata") or {}).get("best_score")
            or ((o.get("top_scores") or [{}])[0].get("score")),
            2,
        ),
    ),
])

# EquiDock: complex_pdbs is a list → count poses
register("equidock", [
    FeatureSpec(
        "equidock_num_poses", "EquiDock Poses", "number",
        lambda o: (lambda n: n if n > 0 else None)(
            len(o.get("complex_pdbs") or [])
            or (1 if o.get("best_complex") not in (None, _ARTIFACT) else 0)
        ),
    ),
])
