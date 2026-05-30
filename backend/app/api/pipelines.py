import json
import os
import uuid
from datetime import datetime

import anthropic as _anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PipelineRow
from app.db.session import get_db
from app.models.pipeline import Pipeline
from app.tools.registry import tool_registry

router = APIRouter()

# ── System prompt ──────────────────────────────────────────────────────────────
_PIPELINE_SYSTEM_PROMPT = """
You are a pipeline architect for an antibody and protein design platform.
Generate a valid pipeline JSON based on the user's request.

## Output format
Return ONLY a raw JSON object — no markdown fences, no explanation, no trailing text.

{
  "id": "<uuid v4>",
  "name": "<short descriptive name>",
  "schema_version": "1",
  "nodes": [
    {"id": "unique_node_id", "tool": "tool_id", "params": {}, "position": {"x": 0.0, "y": 0.0}}
  ],
  "edges": [
    {"source": "sourceNodeId.outputPortName", "target": "targetNodeId.inputPortName"}
  ]
}

## Edge format
"source" and "target" are "nodeId.portName" — e.g. "immunebuilder.structure_1" → "haddock.antibody".

## Layout rules
- Arrange nodes left-to-right; x increases ~280 px per step.
- Use y to separate parallel branches (step 140 px).
- Input nodes start at x=50; loop_start and loop_end are also ~50 and ~2000.

## Available tools (tool_id | key inputs → key outputs)

### Inputs
- sequence_input | heavy_chain, light_chain → heavy_chain, light_chain
- target_input   | target(pdb)              → target(pdb), pdb

### Structure prediction
- immunebuilder | heavy_chain, light_chain, num_models(int,default=4) → structure_1, structure_2, structure_3, structure_4 (all pdb)
- esmfold       | sequence(fasta)                                      → structure(pdb), plddt(json)
- alphafold     | sequence(fasta)                                      → structure(pdb), plddt(json)
- equifold      | heavy_chain, light_chain                            → structure(pdb)

### Docking
- haddock3 | antibody(pdb), antigen(pdb), numbering_scheme(str,default="chothia"), antigen_active_residues(str) → complex(pdb), scores(json)
- equidock  | receptor(pdb), ligand(pdb)                              → complex(pdb), scores(json)
- megadock  | receptor(pdb), ligand(pdb)                              → complex(pdb), scores(json)

### Sequence design / mutagenesis
- cdr_mutator  | heavy_chain, light_chain, strategy(str,default="blosum62"), n_mutations(int,default=3), n_variants(int,default=8) → heavy_chain_variants(json), variant_1..variant_8 (each: heavy_chain+light_chain bundle)
- proteinmpnn  | structure(pdb), num_sequences(int,default=8), sampling_temp(float,default=0.1) → sequence(fasta), scores(json)
- iglm         | heavy_chain(fasta)                                   → heavy_chain_variants(json)
- progen2      | sequence(fasta)                                       → sequences(json)
- rfdiffusion  | target_pdb(pdb), hotspot_residues(str), num_designs(int,default=1), num_residues(int,default=80) → backbone(pdb)

### Embeddings
- abmap        | heavy_chain OR sequence(fasta), chain_type(str,"H"/"L"), task(str,"structure"), candidate_sequences(json) → embedding(json), candidate_embeddings(json)
- esm_embedding| sequence(fasta)                                       → embedding(json)
- ablang       | heavy_chain, light_chain                             → embedding(json)
- cheap_embedding | heavy_chain, light_chain                          → embedding(json)

### ML / active learning
- rcc_mlde  | embeddings(json), scores_rank_1..scores_rank_4(json), candidate_embeddings(json) → acquisition_scores(json), model_artifact
- dnn_mlde  | embeddings(json), scores_rank_1..scores_rank_4(json), candidate_embeddings(json), pretrain_dataset_id(str), mode("train"/"score") → acquisition_scores(json), model_artifact

### Bioinformatics / filters
- developability_filter | heavy_chain, acquisition_scores(json), cdr_mutator_variant_1..8 → feasible_variants(json), result(json), n_feasible(int)
- liability_scanner     | heavy_chain, light_chain → hits(json), summary(json), n_liabilities(int)
- biophi               | heavy_chain, light_chain → humanness_score(float)
- deepsp               | heavy_chain, light_chain → scores(json)
- netsolp              | sequence(fasta)           → solubility_score(float)
- pdbfixer             | structure(pdb)            → structure(pdb)
- superwater           | structure(pdb)            → structure(pdb)
- gromacs              | structure(pdb)            → trajectory, scores(json)
- gromacs_mmpbsa       | complex(pdb)              → scores(json)

### Loop control (for iterative active-learning pipelines)
- loop_start | heavy_chain(fasta), light_chain(fasta), max_iterations(int,default=5) → heavy_chain, light_chain
- loop_end   | code(python_code) → next_heavy_chain(str), next_light_chain(str)

### Utility / compute
- compute  | code(python_code) → result(json)
- filter   | sequences(json), threshold(float) → sequences(json)
- rank     | scores(json) → ranked(json)
- choose   | variants → best
- evaluate | sequences → scores(json)
- echo     | value → value
- data     | (static data node) → data(json)
- dataset  | dataset_id(str) → sequences(json)
- sequence_db | query → sequences(json)

## Common pipeline patterns

### Structure characterization (simplest)
sequence_input → immunebuilder → haddock3 (+ target_input)

### CDR mutagenesis scan (one-shot)
sequence_input → cdr_mutator → [immunebuilder → haddock3 per variant]

### De novo binder design
target_input → rfdiffusion → proteinmpnn → esmfold → haddock3

### Active-learning loop (standard 5-iteration)
loop_start → immunebuilder (×4 parallel) → haddock3 (×4) → abmap (train embedding)
           → rcc_mlde/dnn_mlde → cdr_mutator → abmap (candidates) → developability_filter → loop_end

### Liability / developability assessment
sequence_input → liability_scanner → developability_filter

## Rules
1. Every pipeline needs at least one input node.
2. Only connect compatible port types (pdb→pdb, fasta→fasta, json→json, str→str).
3. For HADDOCK docking, wire target_input.pdb → haddock3.antigen and immunebuilder.structure_1 → haddock3.antibody.
4. For active-learning loops, always include loop_start before and loop_end after the loop body.
5. Use short, readable node IDs (e.g., "seq_in", "immunebuilder", "haddock_r1").
6. Return ONLY the raw JSON — absolutely nothing else.
"""


class GenerateRequest(BaseModel):
    prompt: str


@router.post("/generate", response_model=Pipeline)
async def generate_pipeline(req: GenerateRequest) -> Pipeline:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    # Enrich prompt with available tool IDs from the live registry
    registered_ids = sorted(t.id for t in tool_registry.all())
    enriched_prompt = (
        f"{req.prompt}\n\n"
        f"[Registered tool IDs available: {', '.join(registered_ids)}]"
    )

    client = _anthropic.AsyncAnthropic(api_key=api_key)
    try:
        msg = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=_PIPELINE_SYSTEM_PROMPT.strip(),
            messages=[{"role": "user", "content": enriched_prompt}],
        )
    except _anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Claude API error: {exc}") from exc

    raw = msg.content[0].text.strip()

    # Strip markdown fences if Claude wrapped it anyway
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Claude returned invalid JSON: {exc}") from exc

    # Guarantee a fresh UUID so it never collides with saved pipelines
    data["id"] = str(uuid.uuid4())
    data.setdefault("schema_version", "1")
    data.setdefault("name", "AI-generated pipeline")
    data.setdefault("nodes", [])
    data.setdefault("edges", [])

    try:
        return Pipeline.model_validate(data)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Pipeline validation failed: {exc}") from exc


@router.get("/", response_model=list[Pipeline])
async def list_pipelines(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(PipelineRow).order_by(PipelineRow.updated_at.desc()))).scalars()
    result = []
    for r in rows:
        p = Pipeline.model_validate_json(r.data)
        p.created_at = r.created_at.isoformat()
        p.updated_at = r.updated_at.isoformat()
        result.append(p)
    return result


@router.post("/", response_model=Pipeline, status_code=201)
async def create_pipeline(pipeline: Pipeline, db: AsyncSession = Depends(get_db)):
    row = PipelineRow(
        id=pipeline.id,
        name=pipeline.name,
        data=pipeline.model_dump_json(),
    )
    db.add(row)
    await db.commit()
    return pipeline


@router.get("/{pipeline_id}", response_model=Pipeline)
async def get_pipeline(pipeline_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(PipelineRow, pipeline_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return Pipeline.model_validate_json(row.data)


@router.put("/{pipeline_id}", response_model=Pipeline)
async def update_pipeline(pipeline_id: str, pipeline: Pipeline, db: AsyncSession = Depends(get_db)):
    row = await db.get(PipelineRow, pipeline_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    pipeline.id = pipeline_id
    row.name = pipeline.name
    row.data = pipeline.model_dump_json()
    row.updated_at = datetime.utcnow()
    await db.commit()
    return pipeline


@router.delete("/{pipeline_id}", status_code=204)
async def delete_pipeline(pipeline_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(PipelineRow, pipeline_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    await db.delete(row)
    await db.commit()
