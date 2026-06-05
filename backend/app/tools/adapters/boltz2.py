"""Boltz2 adapter — HTTP tool for structure prediction + binding affinity.

Calls tools/boltz2/server.py (FastAPI wrapping `boltz predict` CLI).
Pattern C (HTTP). See docs/adding-tools.md § Pattern C.

Setup: see tools/boltz2/SETUP.md — start the server on BOLTZ2_URL (default port 8010).
"""
from typing import Any

from app.config import settings
from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.cache import ToolCache
from app.tools.http_tool import post_with_retry


class Boltz2Adapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = ToolCache(tool_id="boltz2", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        # Prefer heavy_chain (upstream edge) over sequence (node param) so wired pipelines win.
        sequence = str(inputs.get("heavy_chain", "") or inputs.get("sequence", "") or "").strip()
        light_chain = str(inputs.get("light_chain", "") or "").strip()
        structure = str(inputs.get("structure", "") or "").strip()
        ligand_name = str(inputs.get("ligand_name", "LIG") or "LIG").strip()

        # compound_library outputs a list of {name, smiles, source} dicts.
        # When wired to ligand_smiles, take the first compound's SMILES string.
        raw_smiles = inputs.get("ligand_smiles", "") or ""
        if isinstance(raw_smiles, list):
            first = raw_smiles[0] if raw_smiles else {}
            raw_smiles = first.get("smiles", "") if isinstance(first, dict) else str(first)
            if isinstance(first, dict) and not ligand_name:
                ligand_name = first.get("name", "LIG")[:3].upper()
        ligand_smiles = str(raw_smiles).strip()

        if not sequence and not structure:
            raise ValueError("boltz2 requires either 'sequence' (FASTA) or 'structure' (PDB)")

        cache_key: dict[str, Any] = {
            "sequence": sequence,
            "light_chain": light_chain,
            "structure": structure,
            "ligand_smiles": ligand_smiles,
            "ligand_name": ligand_name,
        }

        cached = self._cache.get(cache_key)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored Boltz2 result")
            return cached

        mode = "structure" if (structure and "ATOM" in structure) else "sequence"
        lig_msg = f" + ligand={ligand_name}" if ligand_smiles else ""
        await run_ctx.alog(
            f"Submitting to Boltz2 at {settings.boltz2_url}: input={mode}{lig_msg}"
        )

        payload: dict[str, Any] = {
            "sequence": sequence,
            "light_chain": light_chain,
            "structure": structure,
            "ligand_smiles": ligand_smiles,
            "ligand_name": ligand_name,
        }

        data = await post_with_retry(
            settings.boltz2_url,
            "/predict",
            payload,
            tool_name="Boltz2",
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
        )

        outputs: dict[str, Any] = {
            "structure": data.get("structure", ""),
            "binding_probability": data.get("binding_probability"),
            "binding_affinity": data.get("binding_affinity"),
            "plddt": data.get("plddt"),
        }

        prob = outputs["binding_probability"]
        aff = outputs["binding_affinity"]
        await run_ctx.alog(
            f"Boltz2 done — binding_prob={prob}, affinity={aff} µM"
        )

        self._cache.put(cache_key, outputs)
        return outputs
