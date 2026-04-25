"""AlphaFold adapter using the EBI AlphaFold Database REST API."""
from typing import Any

import httpx

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext

EBI_BASE = "https://alphafold.ebi.ac.uk/api"


def _extract_plddt(pdb_text: str) -> tuple[list[int], list[float]]:
    """Extract per-residue pLDDT scores from PDB B-factor column (CA atoms only)."""
    residues: list[int] = []
    scores: list[float] = []
    seen: set[int] = set()
    for line in pdb_text.splitlines():
        if line.startswith("ATOM") and len(line) >= 66 and line[12:16].strip() == "CA":
            try:
                res_num = int(line[22:26])
                b_factor = float(line[60:66])
            except ValueError:
                continue
            if res_num not in seen:
                seen.add(res_num)
                residues.append(res_num)
                scores.append(b_factor)
    return residues, scores


class AlphaFoldAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        uniprot_id = (inputs.get("uniprot_id") or "").strip().upper()
        if not uniprot_id:
            raise ValueError("uniprot_id is required for AlphaFold EBI lookup")

        run_ctx.log(f"Querying EBI AlphaFold database for {uniprot_id}…")

        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(f"{EBI_BASE}/prediction/{uniprot_id}")
            if resp.status_code == 404:
                raise ValueError(f"No AlphaFold prediction found for UniProt ID: {uniprot_id}")
            resp.raise_for_status()

            predictions = resp.json()
            if not predictions:
                raise ValueError(f"Empty prediction list for {uniprot_id}")
            meta = predictions[0]

            run_ctx.log(
                f"Found: {meta.get('uniprotDescription', uniprot_id)} "
                f"({meta.get('organismScientificName', 'unknown')})"
            )

            run_ctx.log("Downloading PDB structure…")
            pdb_resp = await client.get(meta["pdbUrl"])
            pdb_resp.raise_for_status()
            pdb_text = pdb_resp.text

            run_ctx.log("Downloading PAE matrix…")
            pae_resp = await client.get(meta["paeDocUrl"])
            pae_resp.raise_for_status()
            pae_raw = pae_resp.json()
            pae_data = pae_raw[0] if isinstance(pae_raw, list) else pae_raw

        residue_nums, plddt_scores = _extract_plddt(pdb_text)
        n = len(plddt_scores)
        mean_plddt = sum(plddt_scores) / n if n else 0.0
        high_conf_pct = 100 * sum(1 for v in plddt_scores if v >= 70) / n if n else 0.0
        very_high_pct = 100 * sum(1 for v in plddt_scores if v >= 90) / n if n else 0.0

        run_ctx.log(
            f"Done — {n} residues | mean pLDDT {mean_plddt:.1f} | "
            f"high-conf {high_conf_pct:.0f}% | very-high {very_high_pct:.0f}%"
        )

        plddt = {
            "uniprot_id": uniprot_id,
            "entry_id": meta.get("entryId", ""),
            "gene": meta.get("gene", ""),
            "description": meta.get("uniprotDescription", ""),
            "organism": meta.get("organismScientificName", ""),
            "sequence_length": n,
            "mean_plddt": round(mean_plddt, 2),
            "high_confidence_pct": round(high_conf_pct, 1),
            "very_high_confidence_pct": round(very_high_pct, 1),
            "residue_numbers": residue_nums,
            "plddt_per_residue": plddt_scores,
        }

        return {
            "structure": pdb_text,
            "plddt": plddt,
            "pae": pae_data,
        }
