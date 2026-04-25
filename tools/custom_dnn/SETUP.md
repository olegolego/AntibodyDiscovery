# Custom DNN — Setup Guide

> **Status: Work in Progress** — This tool is a design scaffold. The backend adapter raises `NotImplementedError`. The spec is fully defined; implementation is tracked below.

**What it will do:** Train and run custom deep neural networks (MLP, Transformer, CNN) for bio-property prediction from antibody sequences. Uses ESM-2 embeddings as input features.

---

## Planned architecture

```
sequences (FASTA)
    ↓
ESM-2 encoder  (esm2_t33_650M or smaller)
    ↓
[optional] Per-residue pooling → fixed-size vector
    ↓
Configurable head:
  - MLP: Linear(d) → ReLU → ... → Linear(out)
  - Transformer: n_heads, n_layers, ff_dim
  - CNN: n_filters, kernel_size, pooling
    ↓
Loss: MSE (regression) | BCE (binary) | CrossEntropy (multiclass)
    ↓
predictions + model_artifact (checkpoint JSON)
```

---

## Planned environment

Will use the shared backend venv + these packages:

```bash
backend/.venv/bin/pip install \
  torch torchvision \
  fair-esm \
  scikit-learn \
  numpy pandas
```

GPU optional — training will run on CPU (slower) if no CUDA.

---

## Implementation roadmap

- [ ] ESM-2 embedding extractor (reuse from Property Predictor)
- [ ] MLP training loop with configurable layers
- [ ] Transformer encoder head
- [ ] CNN encoder head
- [ ] Model checkpoint serialisation to JSON artifact
- [ ] Inference-only mode (load checkpoint, skip training)
- [ ] Metrics logging: loss curves, RMSE/AUC per epoch
- [ ] Integration with Property Predictor (pass embeddings as features)

---

## Inputs / outputs reference

See `tool.yaml` for the full spec. Key inputs:
- `sequences`: FASTA sequences to train on or run inference over
- `labels`: Training targets (JSON array or `{id: label}` dict)
- `architecture`: `mlp` | `transformer` | `cnn`
- `hidden_dims`: Space-separated layer widths, e.g. `"256 128 64"`
- `task`: `regression` | `binary_classification` | `multiclass`

Key outputs:
- `model_artifact`: Checkpoint JSON (pass to another Custom DNN node for inference)
- `predictions`: Per-sequence predictions with confidence
- `metrics`: Training curves and eval scores
