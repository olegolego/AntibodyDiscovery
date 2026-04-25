# EquiDock Setup

**Paper:** Ganea et al., "Independent SE(3)-Equivariant Models for End-to-End Rigid Protein Docking", ICLR 2022  
**Repo:** https://github.com/octavian-ganea/equidock_public  
**Runtime:** CPU (slow but works) or GPU (CUDA 10.1+). Inference takes ~5–30 s on CPU.

---

## 1. Prerequisites

**Python 3.10** is supported. `setup.sh` automatically installs PyTorch 2.0.1 + DGL 1.1.3
on Python 3.10 (the original requirements.txt pins torch 1.10.2 which has no Python 3.10 wheels,
but EquiDock's model code works with torch 2.x). Python 3.9 also works with the original
torch 1.10.2 / DGL 0.7.0 pinned versions.

---

## 2. Run setup.sh

```bash
cd tools/equidock
bash setup.sh
```

This will:
1. Clone `equidock_public` into `tools/equidock/repo/`
2. Create a Python 3.9 venv at `tools/equidock/.venv/`
3. Install PyTorch 1.10.2 (CPU), DGL 0.7.0, and other pinned deps
4. Verify that checkpoint files exist in the cloned repo

---

## 3. Verify checkpoints

After cloning, confirm the pretrained checkpoints are present:

```bash
ls tools/equidock/repo/checkpts/
# Should show two long-named directories (oct20_Wdec_0.0001... and oct20_Wdec_0.001...)

ls tools/equidock/repo/checkpts/oct20_Wdec_0.0001*/dips_model_best.pth
ls tools/equidock/repo/checkpts/oct20_Wdec_0.001*/db5_model_best.pth
```

If checkpoints are missing, the repo may require downloading them separately — check the GitHub repo README.

---

## 4. Apple Silicon (M1/M2) note

PyTorch 1.10.2 does not have native ARM wheels. On Apple Silicon you have two options:

**Option A — Run under Rosetta (Intel emulation):**
```bash
arch -x86_64 python3.9 -m venv .venv
# Then run setup.sh with Rosetta Python
```

**Option B — Use a newer torch/DGL (may require minor code changes):**
```bash
# Try torch 1.13 + dgl 1.0 in setup.sh — the model code may work with newer versions
# Check the repo's open issues for community-tested newer-version configs
```

---

## 5. Test the tool manually

```bash
# Using the venv Python directly
PYTHONPATH=tools/equidock/repo \
  tools/equidock/.venv/bin/python tools/equidock/run.py <<'EOF'
{
  "ligand": "ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00  0.00\n",
  "receptor": "ATOM      1  N   ALA B   1       5.000   5.000   5.000  1.00  0.00\n",
  "dataset": "dips",
  "remove_clashes": false
}
EOF
```

---

## 6. Common errors

| Error | Fix |
|---|---|
| `ModuleNotFoundError: src` | Confirm `tools/equidock/repo/` was cloned correctly |
| `FileNotFoundError: dips_model_best.pth` | Checkpoint missing — re-clone or download manually |
| `ImportError: torch` | Ran with wrong Python; use `.venv/bin/python` |
| `DGL backend error` | DGL version mismatch with torch; re-run setup.sh |
| Python 3.10 `SyntaxError` in equidock code | Use Python 3.9 as required |

---

## 7. EquiDock vs HADDOCK3

| | EquiDock | HADDOCK3 |
|---|---|---|
| Speed | ~5–30 s | 15–90 min |
| Restraints needed | No | Yes (CDR + epitope residue numbers) |
| Refinement | Rigid + optional clash removal | Full flexible refinement |
| Scoring | Neural network prediction | HADDOCK energy function |
| Best for | Fast screening, initial poses | Accurate refinement, final models |

**Recommended workflow:** EquiDock first for fast screening → HADDOCK3 for top candidates.
