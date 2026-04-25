# Database Plan

> Living document. Update this whenever a tool's outputs or schema change.
> Goal: design a proper relational database layer on top of the current SQLite prototype.

---

## Current storage (what exists today)

### `backend/protein_design.db` — main SQLite (via SQLAlchemy async)

Three tables:

#### `pipelines`
Stores pipeline graph JSON, never mutated after save.

| column | type | notes |
|---|---|---|
| id | UUID string | pipeline UUID |
| name | varchar(255) | user-set display name |
| data | TEXT (JSON) | full `Pipeline` model (nodes, edges, params) |
| created_at | datetime | |
| updated_at | datetime | |

Pipeline JSON structure:
```json
{
  "id": "...", "name": "...", "schema_version": "1",
  "nodes": [{"id": "n1", "tool": "immunebuilder", "params": {...}, "position": {...}}],
  "edges": [{"source": "n1.structure_1", "target": "n2.antibody"}]
}
```

#### `runs`
One row per execution. `data` column is the full run state JSON (all node statuses, logs, outputs).

| column | type | notes |
|---|---|---|
| id | UUID string | run UUID |
| pipeline_id | UUID string | FK → pipelines.id |
| status | varchar(20) | queued / running / succeeded / failed / cancelled |
| data | TEXT (JSON) | full `Run` model (see below) |
| created_at | datetime | |
| updated_at | datetime | updated on every node transition |

Run JSON `data` structure:
```json
{
  "id": "...", "pipeline_id": "...", "status": "succeeded",
  "pipeline_snapshot": {...},
  "nodes": {
    "n1": {
      "node_id": "n1", "status": "succeeded",
      "logs": ["Mode: antibody | H=119 AA..."],
      "outputs": {"structure_1": "__artifact__", "error_estimates": [...]},
      "error": null
    }
  }
}
```

> **Note:** Large string outputs (PDB text, FASTA) are replaced with `"__artifact__"` sentinel in this table. Full content lives in `node_analyses`.

#### `node_analyses`
One row per node per run, only for analysis tools. Stores full PDB text + confidence metrics.

| column | type | notes |
|---|---|---|
| id | UUID string | |
| run_id | UUID string | FK → runs.id |
| node_id | varchar(64) | e.g. `"n1"` or `"n1_model_2"` (ImmuneBuilder ensemble) |
| tool_id | varchar(64) | e.g. `"immunebuilder"` |
| data | TEXT (JSON) | tool-specific analysis blob (see per-tool section below) |
| created_at | datetime | |

Index on `(run_id, node_id)`.

---

### `tools/*/cache.db` — per-tool SQLite caches

Each tool with a `ToolCache` gets its own SQLite at `tools/<name>/cache.db`.

| column | type | notes |
|---|---|---|
| input_hash | varchar(64) | SHA-256 of canonical inputs (strings truncated to 4 KB) |
| tool_version | varchar(32) | bumping version in tool.yaml invalidates all entries |
| output_json | TEXT (JSON) | full outputs dict |
| created_at | datetime | |

Current tools with caches: `immunebuilder`, `haddock3`.

---

## What each tool records

### `immunebuilder`

Writes up to 4 `node_analyses` rows (one per ranked model):

```json
{
  "structure": "<PDB text — full atom coordinates>",
  "plddt": {
    "model_index": 1,
    "per_residue_rmsd": [0.21, 0.19, 0.35, ...]
  }
}
```

- `structure`: Full PDB atom record (~50 KB per structure)
- `per_residue_rmsd`: Inter-model positional variance array. Length = number of residues (typically 220–250 for an antibody Fv). Lower = more confident.

Fields to add later: `mean_rmsd`, `chain_lengths`, `mode` (antibody/nanobody), CDR loop RMSD.

---

### `haddock3`

Writes 1 `node_analyses` row:

```json
{
  "structure": "<PDB text — best docked complex>",
  "plddt": {
    "score": -42.3,
    "score_std": 3.1,
    "vdw": -28.1,
    "vdw_std": 2.4,
    "desolv": -8.2,
    "desolv_std": 1.1,
    "air": 0.0,
    "air_std": 0.0,
    "bsa": 1240.5,
    "bsa_std": 88.2,
    "n_models": 4
  }
}
```

Fields to add later: per-cluster scores, RMSD to reference (if known), contact map, buried surface breakdown.

---

### `esmfold`

Writes 1 `node_analyses` row:

```json
{
  "structure": "<PDB text>",
  "plddt": [87.3, 92.1, 78.4, ...]
}
```

- `plddt`: Per-residue pLDDT scores (0–100). Currently the raw array from the ESMFold server.

Fields to add later: `mean_plddt`, `pae_matrix` (if ESMFold server returns it), secondary structure fractions.

---

### `alphafold_monomer`

Writes 1 `node_analyses` row (planned, currently same handler as ESMFold):

```json
{
  "structure": "<PDB text>",
  "plddt": [88.2, 91.5, ...],
  "pae": [[...], [...], ...]
}
```

- `plddt`: Per-residue pLDDT
- `pae`: N×N PAE matrix (predicted aligned error, Å)

---

### `custom_dnn` (planned)

Will write 1 `node_analyses` row:

```json
{
  "task": "regression",
  "architecture": "mlp",
  "metrics": {
    "train_loss": [0.42, 0.31, ...],
    "val_loss": [0.44, 0.33, ...],
    "val_rmse": 0.28,
    "val_r2": 0.91
  },
  "model_artifact": "<checkpoint JSON — serialised weights>",
  "predictions": [
    {"id": "seq_001", "prediction": 0.83, "confidence": 0.12},
    ...
  ]
}
```

---

### `diffusion_design` (planned)

Will write 1 `node_analyses` row:

```json
{
  "base_model": "rfdiffusion",
  "num_designs": 10,
  "designs": ["<PDB1>", "<PDB2>", ...],
  "scores": [
    {"rank": 1, "confidence": 0.87, "novelty": 0.72, "diversity": 0.65},
    ...
  ],
  "model_checkpoint": "<fine-tuned weights JSON, if fine_tune_epochs > 0>"
}
```

---

### `property_predictor` (planned)

Will write 1 `node_analyses` row:

```json
{
  "embedding_model": "esm2_t33_650M",
  "predictions": [
    {
      "id": "seq_001",
      "affinity_dG": -9.2,
      "tm_celsius": 72.4,
      "aggregation_risk": 0.12,
      "immunogenicity_risk": 0.08,
      "developability_score": 0.91,
      "flags": []
    },
    ...
  ],
  "ranking": ["seq_001", "seq_003", "seq_002", ...],
  "embeddings": "<large float array — only stored if downstream tool needs it>"
}
```

---

## Migration plan (SQLite → Postgres)

Current state: SQLite is used via SQLAlchemy async. Switching to Postgres is a config change:

```python
# backend/app/db/session.py
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./protein_design.db")
# Switch to: "postgresql+asyncpg://user:pass@host/dbname"
```

No schema changes needed — all tables use standard SQL types.

---

## Planned schema additions

These columns should be added as proper DB fields rather than buried in the `data` JSON blob:

### `node_analyses` — add columns

| new column | type | populated by |
|---|---|---|
| mean_confidence | FLOAT | all structure tools (mean pLDDT / mean 1/RMSD) |
| sequence_length | INT | all tools with sequence input |
| heavy_chain_seq | TEXT | immunebuilder, haddock3 |
| light_chain_seq | TEXT | immunebuilder, haddock3 |
| antigen_id | varchar(64) | haddock3 (spike_rbd, custom, ...) |
| docking_score | FLOAT | haddock3 (top cluster HADDOCK score) |
| bsa_angstrom2 | FLOAT | haddock3 (buried surface area) |

### New table: `sequences`

Store unique sequences with a content hash to avoid duplication.

```sql
CREATE TABLE sequences (
  id        VARCHAR(64) PRIMARY KEY,  -- SHA-256 of sequence string
  sequence  TEXT NOT NULL,
  chain_type VARCHAR(2),              -- H, L, VHH
  source    VARCHAR(64),              -- e.g. trastuzumab, user_input
  created_at DATETIME DEFAULT NOW()
);
```

### New table: `designs`

Link designs to their parent run + sequence for cross-run comparison:

```sql
CREATE TABLE designs (
  id           VARCHAR(36) PRIMARY KEY,
  run_id       VARCHAR(36) REFERENCES runs(id),
  node_id      VARCHAR(64),
  sequence_id  VARCHAR(64) REFERENCES sequences(id),
  tool_id      VARCHAR(64),
  pdb_text     TEXT,                   -- or S3 URI when artifact store is wired up
  confidence   FLOAT,
  created_at   DATETIME DEFAULT NOW()
);
```

---

## Cache DB schema (per-tool)

Current schema for `tools/*/cache.db`:

```sql
CREATE TABLE cache (
  input_hash   VARCHAR(64) NOT NULL,
  tool_version VARCHAR(32) NOT NULL,
  output_json  TEXT NOT NULL,
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (input_hash, tool_version)
);
```

Future additions:
- `hit_count` INT — for LRU eviction
- `compute_seconds` FLOAT — to prioritise expensive cache hits
- `size_bytes` INT — for cache size management

---

## Artifact store (future)

Large artifacts (PDB files, model weights) should move from the `data` TEXT blob to object storage:

```
node_analyses.data.structure → S3 URI (s3://bucket/runs/{run_id}/{node_id}/structure.pdb)
designs.pdb_text              → S3 URI
custom_dnn.model_artifact     → S3 URI
```

The sentinel `"__artifact__"` already used in WS messages can become an S3 URI once the artifact store is wired up.
