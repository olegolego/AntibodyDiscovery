# Property Predictor — Setup Guide

> **Status: Work in Progress** — This tool is a design scaffold. The backend adapter raises `NotImplementedError`.

**What it will do:** Predict antibody biophysical properties from sequence using ESM-2 embeddings: binding affinity (ΔG), thermostability (Tm), aggregation risk, immunogenicity risk, and composite developability score.

---

## Planned environment

Will use the shared backend venv:

```bash
backend/.venv/bin/pip install \
  fair-esm torch \
  scikit-learn \
  numpy pandas \
  antiberty    # optional: antibody-specific language model
```

GPU recommended for ESM-2 inference (50–500 ms/sequence on GPU vs 5–10 s on CPU).

---

## Planned data sources and models

| Property | Model approach | Reference dataset |
|---|---|---|
| Binding affinity (ΔG) | ESM-2 + MLP regression | SAbDab, ProtaBank |
| Thermostability (Tm) | ESM-2 + MLP regression | Published Tm datasets |
| Aggregation risk | Sequence features (SAP, Kyte-Doolittle) | Therapeutic mAb dataset |
| Immunogenicity | T-cell epitope scan (NetMHCIIpan) | IEDB |
| Developability | Composite (above scores + charge, pI, HIC) | BioPharma benchmark |

---

## Planned architecture

```
sequences (FASTA)
    ↓
ESM-2 encoder → per-residue + mean-pool embeddings
    ↓
┌─────────────────────────────────┐
│ Property-specific heads (MLP):  │
│   affinity_head → ΔG (kcal/mol) │
│   stability_head → Tm (°C)      │
│   agg_head → risk score (0–1)   │
│   immuno_head → risk score (0–1)│
└─────────────────────────────────┘
    ↓
predictions JSON + ranking
```

---

## Implementation roadmap

- [ ] ESM-2 embedding extraction (batch mode)
- [ ] Affinity prediction head (regressor trained on SAbDab)
- [ ] Stability prediction head
- [ ] Aggregation risk (SAP score + ML head)
- [ ] Immunogenicity T-cell epitope scan
- [ ] Composite developability score with configurable weights
- [ ] Fine-tuning path (wire to Custom DNN `predictor_checkpoint` input)
- [ ] UI: ranked output table in AnalysisPanel

---

## Inputs / outputs reference

See `tool.yaml` for the full spec. Key inputs:
- `sequences`: Antibody sequences to score
- `properties`: Which properties to predict (space-separated from: `affinity stability developability immunogenicity all`)
- `antigen_sequence`: Required if `affinity` is selected
- `embedding_model`: ESM-2 size — larger = more accurate, slower: `esm2_t6_8M` → `esm2_t36_3B`
- `predictor_checkpoint`: Optional fine-tuned weights from Custom DNN

Key outputs:
- `predictions`: Per-sequence scores for all requested properties
- `ranking`: Sequences sorted by composite developability score
- `embeddings`: Raw ESM-2 embeddings (pass to Custom DNN for fine-tuning)
