# Diffusion Designer — Setup Guide

> **Status: Work in Progress** — This tool is a design scaffold. The backend adapter raises `NotImplementedError`.

**What it will do:** Configure and run custom diffusion models for antibody structure generation. Supports fine-tuning or sampling from RFdiffusion, FrameDiff, or Chroma with user-defined noise schedules, motif constraints, and conditioning signals.

---

## Planned environment

Will require an isolated venv (GPU required for reasonable speed):

```bash
python3.10 -m venv tools/diffusion_design/.venv

# Base: RFdiffusion dependencies
tools/diffusion_design/.venv/bin/pip install \
  torch torchvision \
  numpy scipy \
  biopython \
  hydra-core omegaconf
```

Model weights (~1–3 GB depending on checkpoint):
- RFdiffusion: https://github.com/RosettaCommons/RFdiffusion
- FrameDiff: https://github.com/jasonkyuyim/se3_diffusion
- Chroma: https://github.com/generatebio/chroma

---

## Planned architecture

```
conditioning inputs:
  - target_structure (PDB) — antigen for binder design
  - motif_residues — fixed scaffold positions
  - length_min / length_max

base model checkpoint (rfdiffusion | framediff | chroma | custom)
    ↓
[optional] fine-tune on training_pdbs (fine_tune_epochs > 0)
    ↓
reverse diffusion sampler
  num_designs × denoising trajectory
    ↓
designs (PDB array) + best_design + scores
```

---

## Implementation roadmap

- [ ] RFdiffusion subprocess runner (isolated venv)
- [ ] Motif scaffolding via `contigmap` syntax
- [ ] Target-conditioned sampling (antibody binder mode)
- [ ] FrameDiff integration
- [ ] Chroma integration
- [ ] Fine-tuning loop on user PDB data
- [ ] Design diversity / novelty scoring
- [ ] UI: noise schedule visualisation

---

## Inputs / outputs reference

See `tool.yaml` for the full spec. Key inputs:
- `base_model`: `rfdiffusion` | `framediff` | `chroma` | `custom`
- `target_structure`: Antigen PDB to condition on
- `motif_residues`: Space-separated residue indices to hold fixed
- `num_designs`: How many structures to generate
- `guidance_scale`: Classifier-free guidance strength (1.0 = none)
- `fine_tune_epochs`: 0 = inference only; >0 = fine-tune on `training_pdbs` first
