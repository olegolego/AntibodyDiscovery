"""Collects tool outputs into the results database after each node succeeds.

Called by executor.py after every successful node run. Maps tool outputs into
the typed result tables (molecules, structures, docking_results, etc.) and
links them by molecule_id so results from the same antibody are traceable.
"""
import json
from typing import Any

from app.db.models import (
    DockingResultRow,
    DesignSequenceRow,
    EmbeddingRow,
    MoleculeRow,
    StructureRow,
)
from app.db.session import AsyncSessionLocal
from app.models.run import Run


# ── Molecule registry (in-memory within a run to avoid redundant DB lookups) ──

_run_molecule_cache: dict[str, str] = {}  # run_id -> molecule_id


async def _get_or_create_molecule(
    run: Run, inputs: dict[str, Any]
) -> str | None:
    """Find or create a MoleculeRow for the VH/VL sequences in inputs."""
    heavy = str(inputs.get("heavy_chain") or "").strip()
    light = str(inputs.get("light_chain") or "").strip()
    if not heavy:
        return None

    cache_key = f"{run.id}:{heavy[:40]}:{light[:40]}"
    if cache_key in _run_molecule_cache:
        return _run_molecule_cache[cache_key]

    async with AsyncSessionLocal() as db:
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
        _run_molecule_cache[cache_key] = mol.id
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
    best = outputs.get("best_complex")
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

_STRUCTURE_TOOLS = {"immunebuilder", "esmfold", "alphafold_monomer"}
_DESIGN_TOOLS    = {"proteinmpnn", "rfdiffusion", "biophi"}
_EMBEDDING_TOOLS = {"abmap", "ablang"}


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
        # Resolve molecule_id from sequence in this or any upstream node
        molecule_id = _run_molecule_cache.get(f"{run.id}:")

        # Try to find sequences from current inputs or upstream sequence_input node
        seq_inputs = {**inputs}
        for prior_outputs in node_outputs.values():
            if prior_outputs.get("heavy_chain"):
                seq_inputs.setdefault("heavy_chain", prior_outputs["heavy_chain"])
            if prior_outputs.get("light_chain"):
                seq_inputs.setdefault("light_chain", prior_outputs["light_chain"])

        molecule_id = await _get_or_create_molecule(run, seq_inputs)

        if tool_id == "sequence_input":
            await _collect_sequence_input(run, node_id, inputs, outputs)
        elif tool_id in _STRUCTURE_TOOLS:
            await _collect_structure(run, node_id, tool_id, inputs, outputs, molecule_id)
        elif tool_id in ("haddock3", "equidock", "megadock"):
            await _collect_docking(run, node_id, tool_id, inputs, outputs, molecule_id)
        elif tool_id == "gromacs_mmpbsa":
            await _collect_gromacs_mmpbsa(run, node_id, tool_id, inputs, outputs, molecule_id)
        elif tool_id in _DESIGN_TOOLS:
            await _collect_design(run, node_id, tool_id, outputs, molecule_id)
        elif tool_id in _EMBEDDING_TOOLS:
            await _collect_embedding(run, node_id, tool_id, outputs, molecule_id)
    except Exception as exc:
        # Never crash the pipeline for collector failures
        import logging
        logging.getLogger(__name__).warning(f"results_collector failed for {tool_id}/{node_id}: {exc}")
