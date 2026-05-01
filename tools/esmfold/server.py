"""ESMFold HTTP wrapper — uses HuggingFace transformers (no openfold dep)."""
import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="ESMFold")
_model = None
_tokenizer = None


@app.on_event("startup")
async def load_model():
    global _model, _tokenizer
    from transformers import AutoTokenizer, EsmForProteinFolding
    print("Loading ESMFold v1 via HuggingFace transformers…")
    _tokenizer = AutoTokenizer.from_pretrained("facebook/esmfold_v1")
    _model = EsmForProteinFolding.from_pretrained(
        "facebook/esmfold_v1", low_cpu_mem_usage=True
    )
    _model = _model.eval()
    if torch.cuda.is_available():
        _model = _model.cuda()
        print("ESMFold running on CUDA")
    else:
        print("ESMFold running on CPU (slow — expect 5-30 min per sequence)")


def _to_pdb(outputs) -> str:
    from transformers.models.esm.openfold_utils.protein import to_pdb, Protein as OFProtein
    from transformers.models.esm.openfold_utils.feats import atom14_to_atom37

    final_atom_positions = atom14_to_atom37(outputs["positions"][-1], outputs)
    final_atom_positions = final_atom_positions.cpu().numpy()

    def _np(key):
        v = outputs[key]
        return v.cpu().numpy() if hasattr(v, "cpu") else np.array(v)

    aa        = _np("aatype")[0]
    pred_pos  = final_atom_positions[0]
    mask      = _np("atom37_atom_exists")[0]
    resid     = _np("residue_index")[0].astype(int) + 1
    b_factors = np.repeat(_np("plddt")[0][..., None], 37, axis=-1)
    chain_idx = _np("chain_index")[0] if "chain_index" in outputs else np.zeros(len(aa), dtype=int)

    protein = OFProtein(
        aatype=aa,
        atom_positions=pred_pos,
        atom_mask=mask,
        residue_index=resid,
        b_factors=b_factors,
        chain_index=chain_idx,
    )
    return to_pdb(protein)


class PredictRequest(BaseModel):
    sequence: str


@app.post("/predict")
async def predict(req: PredictRequest):
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    seq = req.sequence.strip().upper()
    if not seq:
        raise HTTPException(status_code=400, detail="sequence is required")

    tokenized = _tokenizer([seq], return_tensors="pt", add_special_tokens=False)
    if torch.cuda.is_available():
        tokenized = {k: v.cuda() for k, v in tokenized.items()}

    with torch.no_grad():
        outputs = _model(**tokenized)

    pdb_string = _to_pdb(outputs)

    # Parse per-residue pLDDT from B-factor column (CA atoms only)
    plddt: list[float] = []
    for line in pdb_string.splitlines():
        if line.startswith("ATOM") and len(line) >= 66 and line[12:16].strip() == "CA":
            try:
                plddt.append(float(line[60:66]))
            except ValueError:
                pass

    return {"pdb": pdb_string, "plddt": plddt}


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": _model is not None}
