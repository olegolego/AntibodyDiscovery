"""Collects tool outputs into the results database after each node succeeds.

Called by executor.py after every successful node run. Maps tool outputs into
the typed result tables (molecules, structures, docking_results, etc.) and
links them by molecule_id so results from the same antibody are traceable.
"""
import json
from typing import Any

from sqlalchemy import select

from app.db.models import (
    DockingResultRow,
    DesignSequenceRow,
    EmbeddingRow,
    MoleculeRow,
    NodeAnalysisRow,
    StructureRow,
    TrainedModelRow,
)
from app.db.session import AsyncSessionLocal
from app.models.run import Run


# ── Molecule registry (in-memory to avoid redundant DB lookups within a session) ──

_molecule_cache: dict[str, str] = {}  # "{heavy}:{light}" -> molecule_id


async def _get_or_create_molecule(
    run: Run, inputs: dict[str, Any]
) -> str | None:
    """Find or create a MoleculeRow for the VH/VL sequences in inputs.

    Deduplicates by (heavy_chain, light_chain) across all runs so that repeated
    runs of the same sequence accumulate results under one molecule record.
    """
    heavy = str(inputs.get("heavy_chain") or "").strip()
    light = str(inputs.get("light_chain") or "").strip()
    if not heavy:
        return None

    cache_key = f"{heavy}:{light}"
    if cache_key in _molecule_cache:
        return _molecule_cache[cache_key]

    async with AsyncSessionLocal() as db:
        # Look up existing molecule with this exact (VH, VL) pair
        existing = (await db.execute(
            select(MoleculeRow)
            .where(MoleculeRow.heavy_chain == heavy,
                   MoleculeRow.light_chain == (light or None))
            .order_by(MoleculeRow.created_at.asc())
            .limit(1)
        )).scalar_one_or_none()

        if existing is not None:
            _molecule_cache[cache_key] = existing.id
            return existing.id

        mol = MoleculeRow(
            run_id=run.id,
            pipeline_id=run.pipeline_id,
            heavy_chain=heavy,
            light_chain=light or None,
            name=_short_name(heavy),
        )
        db.add(mol)
        await db.commit()
        await db.refresh(mol)
        _molecule_cache[cache_key] = mol.id
        return mol.id


def _short_name(seq: str) -> str:
    """Auto-generate a short name like 'EVQLV…WGQGT' from a sequence."""
    seq = seq.strip()
    if len(seq) <= 12:
        return seq
    return f"{seq[:5]}…{seq[-5:]}"


# ── Per-tool collectors ───────────────────────────────────────────────────────

async def _collect_sequence_input(run: Run, node_id: str, inputs: dict, outputs: dict) -> None:
    await _get_or_create_molecule(run, outputs)


async def _collect_structure(
    run: Run, node_id: str, tool_id: str, inputs: dict, outputs: dict, molecule_id: str | None
) -> None:
    async with AsyncSessionLocal() as db:
        if tool_id == "immunebuilder":
            for rank in range(1, 5):
                pdb = outputs.get(f"structure_{rank}")
                if pdb and isinstance(pdb, str) and len(pdb) > 10:
                    row = StructureRow(
                        molecule_id=molecule_id,
                        run_id=run.id,
                        node_id=node_id,
                        tool_id=tool_id,
                        model_rank=rank,
                        pdb_data=pdb,
                        confidence=json.dumps(outputs.get("error_estimates") or []),
                    )
                    db.add(row)
        else:
            pdb = outputs.get("structure")
            if pdb and isinstance(pdb, str) and len(pdb) > 10:
                plddt = outputs.get("plddt")
                row = StructureRow(
                    molecule_id=molecule_id,
                    run_id=run.id,
                    node_id=node_id,
                    tool_id=tool_id,
                    pdb_data=pdb,
                    confidence=json.dumps(plddt) if plddt is not None else None,
                )
                db.add(row)
        await db.commit()


async def _collect_docking(
    run: Run, node_id: str, tool_id: str, inputs: dict, outputs: dict, molecule_id: str | None
) -> None:
    # MEGADOCK uses complex_1…complex_N keys; HADDOCK/EquiDock use best_complex
    best = outputs.get("best_complex") or outputs.get("complex_1")
    if not best:
        return
    antigen = inputs.get("antigen") or inputs.get("receptor") or ""
    antigen_label = "spike_rbd" if len(antigen) > 100 else (antigen[:40] or "unknown")
    scores = outputs.get("scores")
    meta = outputs.get("metadata")
    async with AsyncSessionLocal() as db:
        row = DockingResultRow(
            molecule_id=molecule_id,
            tool_id=tool_id,
            antigen_label=antigen_label,
            run_id=run.id,
            node_id=node_id,
            best_complex_pdb=best,
            scores=json.dumps(scores) if scores else None,
            extra_data=json.dumps(meta) if meta else None,
        )
        db.add(row)
        await db.commit()


async def _collect_megadock_analysis(
    run: Run, node_id: str, outputs: dict,
) -> None:
    """Save MEGADOCK top-N complexes + scores to NodeAnalysisRow for the analysis panel."""
    top_scores = outputs.get("top_scores", [])
    if not top_scores:
        return
    # Collect all complex PDBs keyed by rank
    complex_pdbs: dict[str, str] = {}
    for entry in top_scores:
        rank = entry.get("rank")
        pdb = outputs.get(f"complex_{rank}")
        if pdb:
            complex_pdbs[str(rank)] = pdb
    data = {
        "structure": outputs.get("complex_1"),   # best complex for 3-D viewer default
        "top_scores": top_scores,
        "complex_pdbs": complex_pdbs,
        "metadata": outputs.get("metadata") or {},
        "image": outputs.get("image"),
    }
    async with AsyncSessionLocal() as db:
        row = NodeAnalysisRow(
            run_id=run.id,
            node_id=node_id,
            tool_id="megadock",
            data=json.dumps(data),
        )
        db.add(row)
        await db.commit()


async def _collect_design(
    run: Run, node_id: str, tool_id: str, outputs: dict, molecule_id: str | None
) -> None:
    async with AsyncSessionLocal() as db:
        row = DesignSequenceRow(
            molecule_id=molecule_id,
            run_id=run.id,
            node_id=node_id,
            tool_id=tool_id,
            sequences=json.dumps(outputs.get("sequence") or outputs.get("sequences") or []),
            scores=json.dumps(outputs.get("scores")) if outputs.get("scores") else None,
            backbone_pdb=outputs.get("backbone") if tool_id == "rfdiffusion" else None,
        )
        db.add(row)
        await db.commit()


async def _collect_embedding(
    run: Run, node_id: str, tool_id: str, outputs: dict, molecule_id: str | None
) -> None:
    async with AsyncSessionLocal() as db:
        row = EmbeddingRow(
            molecule_id=molecule_id,
            run_id=run.id,
            node_id=node_id,
            tool_id=tool_id,
            embedding_meta=json.dumps(outputs.get("metadata") or {}),
        )
        db.add(row)
        await db.commit()


async def _collect_superwater(
    run: Run, node_id: str, tool_id: str, outputs: dict, molecule_id: str | None
) -> None:
    pdb = outputs.get("hydrated_structure")
    if not pdb or not isinstance(pdb, str) or len(pdb) <= 10:
        return
    water_count = outputs.get("water_count") or {}
    async with AsyncSessionLocal() as db:
        row = StructureRow(
            molecule_id=molecule_id,
            run_id=run.id,
            node_id=node_id,
            tool_id=tool_id,
            pdb_data=pdb,
            confidence=json.dumps(water_count),
        )
        db.add(row)
        await db.commit()


async def _collect_gromacs_mmpbsa(
    run: Run, node_id: str, tool_id: str, inputs: dict, outputs: dict, molecule_id: str | None
) -> None:
    """Store MM/GBSA binding affinity as a docking result row."""
    dg = outputs.get("delta_g_bind")
    if dg is None:
        return
    energy = outputs.get("energy_decomposition") or {}
    convergence = outputs.get("md_convergence") or {}
    scores = {
        "delta_g_bind_kcal_mol": dg,
        **{k: v for k, v in energy.items() if v is not None},
    }
    antigen = inputs.get("complex_pdb") or ""
    antigen_label = f"gromacs_complex_{node_id[:8]}"
    async with AsyncSessionLocal() as db:
        row = DockingResultRow(
            molecule_id=molecule_id,
            tool_id=tool_id,
            antigen_label=antigen_label,
            run_id=run.id,
            node_id=node_id,
            best_complex_pdb=None,
            scores=json.dumps(scores),
            extra_data=json.dumps(convergence),
        )
        db.add(row)
        await db.commit()


# ── Public entry point ────────────────────────────────────────────────────────

_STRUCTURE_TOOLS = {"immunebuilder", "esmfold", "alphafold_monomer", "equifold"}
_DESIGN_TOOLS    = {"proteinmpnn", "rfdiffusion", "biophi", "iglm", "progen2"}
_EMBEDDING_TOOLS = {"abmap", "ablang", "esm_embedding", "cheap_embedding", "aa_chem_embedding", "aa_onehot_embedding"}

_MAX_VARIANT_HANDLES = 10


async def _collect_cdr_mutator(
    run: Run, node_id: str, inputs: dict, outputs: dict, source_molecule_id: str | None
) -> None:
    """Register each CDR Mutator variant as its own MoleculeRow.

    - The original input molecule is linked via a DesignSequenceRow so the
      Results page can show "N variants generated from EVQLV…WGQGT".
    - Each variant (variant_1 … variant_10) that is non-null gets its own
      MoleculeRow, pre-named with its strategy + CDR label, so they appear as
      distinct entries in the results database rather than collapsing onto the
      parent sequence.
    """
    summary  = outputs.get("summary") or {}
    strategy = summary.get("strategy", "?")
    cdrs     = "+".join(summary.get("cdr_regions_targeted") or []) or "?"

    variant_heavy_chains: list[str] = []

    for i in range(1, _MAX_VARIANT_HANDLES + 1):
        bundle = outputs.get(f"variant_{i}")
        if not bundle or not isinstance(bundle, dict):
            continue

        vh = str(bundle.get("heavy_chain") or "").strip()
        vl = str(bundle.get("light_chain") or "").strip()
        if not vh:
            continue

        # Register the variant as a molecule with a descriptive name
        variant_mol_id = await _get_or_create_molecule(run, {"heavy_chain": vh, "light_chain": vl})

        # Annotate the name to flag it as a CDR mutant (only on first creation)
        if variant_mol_id:
            async with AsyncSessionLocal() as db:
                mol = (await db.execute(
                    select(MoleculeRow).where(MoleculeRow.id == variant_mol_id)
                )).scalar_one_or_none()
                if mol and not mol.name.startswith("mut:"):
                    mol.name = f"mut:{strategy}:{cdrs}:{i} {mol.name}"
                    await db.commit()

        variant_heavy_chains.append(vh)

    # Record all variant heavy chains as a DesignSequenceRow on the source molecule
    if source_molecule_id and variant_heavy_chains:
        async with AsyncSessionLocal() as db:
            db.add(DesignSequenceRow(
                molecule_id=source_molecule_id,
                run_id=run.id,
                node_id=node_id,
                tool_id="cdr_mutator",
                sequences=json.dumps(variant_heavy_chains),
                scores=json.dumps({
                    "strategy": strategy,
                    "cdr_regions": cdrs,
                    "num_variants": len(variant_heavy_chains),
                }),
            ))
            await db.commit()


async def _collect_rcc_mlde(
    run: Run, node_id: str, outputs: dict[str, Any]
) -> None:
    # Only collect from training nodes (not scoring/inference nodes)
    if "score" in node_id.lower() and "train" not in node_id.lower():
        return
    artifact = outputs.get("model_artifact")
    if not artifact or not isinstance(artifact, dict):
        return
    committees_b64 = artifact.get("committees")  # dict: {rank_name: base64_pickle}
    if not committees_b64:
        return

    rank_names = artifact.get("rank_names", [])
    kappa_epi = artifact.get("kappa_epi", 2.0)
    kappa_conf = artifact.get("kappa_conf", 0.5)
    model_type = artifact.get("model_type", "ridge")
    task = artifact.get("task", "regression")
    metrics_raw = outputs.get("metrics") or {}
    n_seqs = int((outputs.get("metrics") or {}).get("n_candidates") or len(outputs.get("acquisition_scores") or {}))
    arch_spec = {
        "model_type": model_type,
        "rank_names": rank_names,
        "kappa_epi": kappa_epi,
        "kappa_conf": kappa_conf,
        "n_committees": len(rank_names),
    }
    iter_label = f" · iter {run.iteration}" if run.iteration is not None else ""
    name = f"RCC-MLDE{iter_label} · {run.id[:8]}"

    async with AsyncSessionLocal() as db:
        db.add(TrainedModelRow(
            name=name,
            run_id=run.id,
            node_id=node_id,
            architecture_spec=json.dumps(arch_spec),
            embedding_model="AbMAP",
            task=task,
            num_sequences=n_seqs,
            metrics=json.dumps(metrics_raw),
            weights_b64=json.dumps(committees_b64) if isinstance(committees_b64, dict) else committees_b64,
        ))
        await db.commit()


async def _collect_custom_dnn(
    run: Run, node_id: str, inputs: dict[str, Any], outputs: dict[str, Any]
) -> None:
    artifact = outputs.get("model_artifact")
    if not artifact or not isinstance(artifact, dict):
        return
    weights_b64 = artifact.get("weights_b64")
    if not weights_b64:
        return  # inference-only run — don't re-register the existing model

    metrics_raw = outputs.get("metrics") or {}
    arch_spec = artifact.get("architecture_spec") or {}
    nodes_list = arch_spec.get("nodes", []) if isinstance(arch_spec, dict) else []
    layer_types = [n.get("type", "") for n in nodes_list]
    has_transformer = any(t in ("TransformerEncoder", "MultiheadAttention") for t in layer_types)
    has_recurrent = any(t in ("LSTM", "GRU") for t in layer_types)
    arch_label = "Transformer" if has_transformer else "Recurrent" if has_recurrent else "MLP"
    task = artifact.get("task", "regression")
    emb = artifact.get("embedding_model", "8M")
    name = f"{arch_label} · {task} · {run.id[:8]}"

    async with AsyncSessionLocal() as db:
        db.add(TrainedModelRow(
            name=name,
            run_id=run.id,
            node_id=node_id,
            architecture_spec=json.dumps(arch_spec) if isinstance(arch_spec, dict) else str(arch_spec),
            embedding_model=emb,
            task=task,
            num_sequences=len(outputs.get("predictions") or []),
            metrics=json.dumps(metrics_raw),
            weights_b64=weights_b64,
        ))
        await db.commit()


async def collect(
    run: Run,
    node_id: str,
    tool_id: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    node_outputs: dict[str, dict[str, Any]],  # all prior node outputs in this run
) -> None:
    """Called by executor after every successful node. Fire-and-forget safe."""
    try:
        # Try to find sequences from current inputs or upstream sequence_input node
        seq_inputs = {**inputs}
        for prior_outputs in node_outputs.values():
            if prior_outputs.get("heavy_chain"):
                seq_inputs.setdefault("heavy_chain", prior_outputs["heavy_chain"])
            if prior_outputs.get("light_chain"):
                seq_inputs.setdefault("light_chain", prior_outputs["light_chain"])

        molecule_id = await _get_or_create_molecule(run, seq_inputs)

        if tool_id in ("sequence_input", "sequence_db"):
            await _collect_sequence_input(run, node_id, inputs, outputs)
        elif tool_id == "cdr_mutator":
            await _collect_cdr_mutator(run, node_id, inputs, outputs, molecule_id)
        elif tool_id in _STRUCTURE_TOOLS:
            await _collect_structure(run, node_id, tool_id, inputs, outputs, molecule_id)
        elif tool_id in ("haddock3", "equidock", "megadock"):
            await _collect_docking(run, node_id, tool_id, inputs, outputs, molecule_id)
            if tool_id == "megadock":
                await _collect_megadock_analysis(run, node_id, outputs)
        elif tool_id == "superwater":
            await _collect_superwater(run, node_id, tool_id, outputs, molecule_id)
        elif tool_id == "gromacs_mmpbsa":
            await _collect_gromacs_mmpbsa(run, node_id, tool_id, inputs, outputs, molecule_id)
        elif tool_id in _DESIGN_TOOLS:
            await _collect_design(run, node_id, tool_id, outputs, molecule_id)
        elif tool_id in _EMBEDDING_TOOLS:
            await _collect_embedding(run, node_id, tool_id, outputs, molecule_id)
        elif tool_id in ("rcc_mlde", "dnn_mlde"):
            await _collect_rcc_mlde(run, node_id, outputs)
        elif tool_id == "custom_dnn":
            await _collect_custom_dnn(run, node_id, inputs, outputs)
    except Exception as exc:
        # Never crash the pipeline for collector failures
        import logging
        logging.getLogger(__name__).warning(f"results_collector failed for {tool_id}/{node_id}: {exc}")
