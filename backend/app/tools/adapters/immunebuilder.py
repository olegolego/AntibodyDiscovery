"""ImmuneBuilder adapter — local CPU antibody/nanobody structure prediction."""
import os
import tempfile
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.molecule_cache import MoleculeResultCache

_AA = set("ACDEFGHIKLMNPQRSTVWY")
_MIN_VH_LENGTH = 80


def _clean_sequence(raw: str) -> str:
    """Strip FASTA headers, whitespace, uppercase, validate."""
    lines = [l.strip() for l in raw.splitlines() if not l.startswith(">")]
    seq = "".join(lines).upper().replace(" ", "")
    invalid = set(seq) - _AA
    if invalid:
        raise ValueError(f"Sequence contains non-amino-acid characters: {invalid}")
    return seq


class ImmuneBuilderAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="immunebuilder", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        heavy_raw = inputs.get("heavy_chain", "")
        light_raw = inputs.get("light_chain", "")

        # Validate early so we don't burn cache on bad input
        heavy = _clean_sequence(str(heavy_raw))
        light = _clean_sequence(str(light_raw)) if light_raw else ""
        if len(heavy) < _MIN_VH_LENGTH:
            raise ValueError(
                f"Heavy chain is only {len(heavy)} residues — needs a full variable domain (~110+ AA). Got: {heavy}"
            )

        cache_inputs = {
            "heavy_chain": heavy,
            "light_chain": light,
            "num_models": max(1, min(4, int(inputs.get("num_models", 4)))),
        }
        cached = await self._cache.get(cache_inputs)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored ImmuneBuilder result")
            return cached

        num_models = cache_inputs["num_models"]
        mode = "nanobody" if not light else "antibody"

        await run_ctx.alog(
            f"Mode: {mode} | H={len(heavy)} AA"
            f"{', L=' + str(len(light)) + ' AA' if light else ''}"
            f" | {num_models} model(s)"
        )

        # Validate L chain with ANARCI before running (for antibody mode)
        if mode == "antibody":
            try:
                import anarci  # type: ignore
                hits = anarci.run_anarci([("test_L", light)], scheme="chothia", output=False)
                numbered = hits[0][0]
                if not numbered or numbered[0] is None:
                    raise ValueError("ANARCI could not number the light chain")
            except ValueError as exc:
                await run_ctx.alog(
                    f"WARNING: Light chain not recognised as a valid VL by ANARCI ({exc}). "
                    "Falling back to VH-only (nanobody) mode."
                )
                mode = "nanobody"
                light = ""
            except Exception:
                pass  # anarci unavailable — let ImmuneBuilder raise its own error

        if mode == "nanobody":
            from ImmuneBuilder import NanoBodyBuilder2  # type: ignore
            Builder = NanoBodyBuilder2
            seqs: dict[str, str] = {"H": heavy}
        else:
            from ImmuneBuilder import ABodyBuilder2  # type: ignore
            Builder = ABodyBuilder2
            seqs = {"H": heavy, "L": light}

        model_ids = list(range(1, num_models + 1))
        await run_ctx.alog(f"Running prediction ({num_models} models)…")

        predictor = Builder(model_ids=model_ids)
        try:
            antibody = predictor.predict(seqs)
        except Exception as exc:
            msg = str(exc)
            if "not recognised as an L chain" in msg and mode == "antibody":
                await run_ctx.alog("WARNING: L chain rejected — falling back to nanobody mode.")
                from ImmuneBuilder import NanoBodyBuilder2  # type: ignore
                predictor = NanoBodyBuilder2(model_ids=model_ids)
                seqs = {"H": heavy}
                mode = "nanobody"
                antibody = predictor.predict(seqs)
            else:
                raise

        outputs: dict[str, Any] = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            # save_all writes rank{i}.pdb (or rank{i}_unrefined.pdb) + error_estimates.npy
            antibody.save_all(tmpdir)

            # Per-residue RMSD across ensemble — this is ImmuneBuilder's confidence metric
            import numpy as np
            error_file = os.path.join(tmpdir, "error_estimates.npy")
            error_estimates: list[float] = []
            mean_rmsd = 0.0
            if os.path.exists(error_file):
                arr = np.load(error_file)
                error_estimates = [round(float(v), 4) for v in arr.flatten()]
                mean_rmsd = round(float(arr.mean()), 4) if arr.size > 0 else 0.0
                await run_ctx.alog(f"Error estimates: {len(error_estimates)} residues, mean RMSD {mean_rmsd:.4f} Å")
            else:
                await run_ctx.alog("WARNING: error_estimates.npy not found")

            for rank in range(num_models):
                i = rank + 1  # structure_1 .. structure_4

                # save_all naming varies by ImmuneBuilder version; try both conventions
                pdb_path = next(
                    (c for c in [
                        os.path.join(tmpdir, f"rank{rank}_unrefined.pdb"),
                        os.path.join(tmpdir, f"rank{rank}.pdb"),
                    ] if os.path.exists(c)),
                    None,
                )

                if pdb_path is None:
                    await run_ctx.alog(f"WARNING: no PDB found for rank {rank}")
                    outputs[f"structure_{i}"] = None
                    continue

                # Optional refinement via OpenMM — skip gracefully if unavailable
                refined_path = os.path.join(tmpdir, f"rank{rank}_refined.pdb")
                try:
                    from ImmuneBuilder.refine import refine as ib_refine  # type: ignore
                    if ib_refine(pdb_path, refined_path):
                        pdb_path = refined_path
                        await run_ctx.alog(f"Rank {rank} refined ✓")
                    else:
                        await run_ctx.alog(f"Rank {rank} refinement returned False — using unrefined")
                except Exception as exc:
                    await run_ctx.alog(f"Refinement unavailable for rank {rank} ({type(exc).__name__}) — using unrefined")

                with open(pdb_path) as f:
                    outputs[f"structure_{i}"] = f.read()
                await run_ctx.alog(f"Model {i} ready")

        # Pad unused slots
        for i in range(num_models + 1, 5):
            outputs[f"structure_{i}"] = None

        # Keep error estimates for analysis storage (small: ~250 floats for an antibody)
        outputs["error_estimates"] = error_estimates
        await run_ctx.alog(f"Done — {num_models} model(s), mean RMSD {mean_rmsd:.4f} Å")

        await self._cache.put(cache_inputs, outputs, run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        return outputs
