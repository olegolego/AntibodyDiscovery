# ESMFold — Setup Guide

**What it does:** Fast single-sequence protein structure prediction using ESM-2 language model embeddings. No MSA required. Good for rapid iteration.

**Environment:** HTTP endpoint — ESMFold runs as an external server (GPU required for production speed).

---

## Requirements

- GPU instance (A10G or better recommended; A100 for full `esm2_t48_15B`)
- ~30 GB GPU VRAM for the full model; `esm2_t36_3B` needs ~12 GB
- `ESMFOLD_URL` environment variable

---

## Running the ESMFold server

### Option A — Meta's official ESMFold server

```bash
# Install fair-esm
pip install fair-esm

# The server wrapper (from this repo)
backend/.venv/bin/python -m esm.scripts.fold --help
```

Or use the lightweight HTTP wrapper:

```bash
# On the GPU instance
pip install fair-esm torch flask
python -c "
import esm, torch
from flask import Flask, request, jsonify

app = Flask(__name__)
model = esm.pretrained.esmfold_v1()
model = model.eval().cuda()

@app.route('/predict', methods=['POST'])
def predict():
    seq = request.json['sequence']
    with torch.no_grad():
        out = model.infer_pdb(seq)
    return jsonify({'pdb': out})

app.run(host='0.0.0.0', port=8011)
"
```

### Option B — ESMFold via Hugging Face

```bash
pip install transformers torch
python -c "
from transformers import EsmForProteinFolding, EsmTokenizer
from flask import Flask, request, jsonify
import torch

app = Flask(__name__)
tokenizer = EsmTokenizer.from_pretrained('facebook/esmfold_v1')
model = EsmForProteinFolding.from_pretrained('facebook/esmfold_v1', low_cpu_mem_usage=True)
model = model.cuda().eval()

@app.route('/predict', methods=['POST'])
def predict():
    seq = request.json['sequence']
    inputs = tokenizer([seq], return_tensors='pt', add_special_tokens=False).to('cuda')
    with torch.no_grad():
        out = model(**inputs)
    # convert to PDB ...
    return jsonify({'pdb': pdb_str})

app.run(host='0.0.0.0', port=8011)
"
```

### Option C — Remote endpoint

```bash
export ESMFOLD_URL=http://<gpu-instance-ip>:8011
```

---

## Backend configuration

```env
ESMFOLD_URL=http://localhost:8011
```

---

## Verify

```bash
curl -X POST $ESMFOLD_URL/predict \
  -H "Content-Type: application/json" \
  -d '{"sequence": "MKTIIALSYIFCLVFA"}'
# Should return {"pdb": "ATOM ..."}
```

---

## Known issues

| Issue | Fix |
|---|---|
| `CUDA out of memory` | Use `esm2_t36_3B` (12 GB) instead of `esm2_t48_15B` (30 GB) |
| First request is slow (60+ s) | Model loads weights on first call. Pre-warm with a short sequence |
| Sequences > 400 AA are slow | Expected — ESMFold complexity is O(n²). Use AlphaFold for long sequences |
