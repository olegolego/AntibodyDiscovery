import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PipelineRow(Base):
    __tablename__ = "pipelines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pipeline_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NodeAnalysisRow(Base):
    """Persists analysis results (structure, pLDDT, PAE) for every succeeded analysis node."""

    __tablename__ = "node_analyses"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON blob
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_node_analyses_run_node", "run_id", "node_id"),)


class MoleculeRow(Base):
    """One antibody/nanobody candidate, identified by its VH (+VL) sequence pair."""
    __tablename__ = "molecules"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    heavy_chain: Mapped[str | None] = mapped_column(Text, nullable=True)
    light_chain: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pipeline_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StructureRow(Base):
    """PDB structure produced by any structure-prediction tool, linked to a molecule."""
    __tablename__ = "structures"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    molecule_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_rank: Mapped[int | None] = mapped_column(nullable=True)   # 1-4 for immunebuilder
    pdb_data: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_structures_molecule", "molecule_id"),)


class DockingResultRow(Base):
    """Docking result from HADDOCK3 or EquiDock, linked to the antibody molecule."""
    __tablename__ = "docking_results"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    antibody_structure_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    molecule_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tool_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    antigen_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    best_complex_pdb: Mapped[str | None] = mapped_column(Text, nullable=True)
    scores: Mapped[str | None] = mapped_column(Text, nullable=True)      # JSON — HADDOCK scores
    extra_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON — EquiDock metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_docking_molecule", "molecule_id"),)


class DesignSequenceRow(Base):
    """Sequences designed by ProteinMPNN or backbones from RFdiffusion."""
    __tablename__ = "design_sequences"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    molecule_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sequences: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON list
    scores: Mapped[str | None] = mapped_column(Text, nullable=True)       # JSON
    backbone_pdb: Mapped[str | None] = mapped_column(Text, nullable=True) # RFdiffusion backbone
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EmbeddingRow(Base):
    """Sequence/structure embeddings from AbMAP or ESM."""
    __tablename__ = "embeddings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    molecule_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_meta: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON (non-vector metadata)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ToolCacheRow(Base):
    """Unified result cache for all tools, keyed by inputs_hash + queryable by molecule_key.

    molecule_key = MoleculeKey(vh, vl).primary() when the tool receives sequence inputs.
    Null for tools whose inputs are PDB blobs with no sequence context.
    """
    __tablename__ = "tool_cache"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(32), nullable=False)
    inputs_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    molecule_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inputs_preview: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON
    outputs_json: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_tool_cache_lookup", "tool_id", "inputs_hash"),
        Index("ix_tool_cache_molecule", "molecule_key", "tool_id"),
    )


class AbMAPEmbeddingRow(Base):
    """Full AbMAP embedding result keyed by (VH, VL) pair via MoleculeKey.primary().

    molecule_key = MoleculeKey(vh, vl).primary() — stable 64-char SHA-256 hex.
    All queries from the Results page use this key, not run_id or node_id.
    Multiple embeddings for the same molecule can exist (different chain_type / task).
    """
    __tablename__ = "abmap_embeddings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    molecule_key: Mapped[str] = mapped_column(String(64), nullable=False)
    heavy_chain: Mapped[str | None] = mapped_column(Text, nullable=True)
    light_chain: Mapped[str | None] = mapped_column(Text, nullable=True)
    chain_type: Mapped[str] = mapped_column(String(4), nullable=False)
    task: Mapped[str] = mapped_column(String(32), nullable=False)
    embedding_type: Mapped[str] = mapped_column(String(32), nullable=False)
    num_mutations: Mapped[int] = mapped_column(nullable=False, default=10)
    embedding_json: Mapped[str] = mapped_column(Text, nullable=False)   # JSON list of floats
    embedding_shape: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sequence_length: Mapped[int | None] = mapped_column(nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_abmap_molecule_key", "molecule_key"),
        Index("ix_abmap_molecule_params", "molecule_key", "chain_type", "task", "embedding_type", "num_mutations"),
    )


class SequenceCollectionRow(Base):
    __tablename__ = "sequence_collections"

    id:          Mapped[str]      = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name:        Mapped[str]      = mapped_column(String(255), nullable=False)
    description: Mapped[str|None] = mapped_column(Text, nullable=True)
    created_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SequenceEntryRow(Base):
    __tablename__ = "sequence_entries"

    id:                 Mapped[str]      = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    collection_id:      Mapped[str]      = mapped_column(String(36), nullable=False, index=True)
    name:               Mapped[str|None] = mapped_column(String(255), nullable=True)
    heavy_chain:        Mapped[str]      = mapped_column(Text, nullable=False)
    light_chain:        Mapped[str|None] = mapped_column(Text, nullable=True)
    source_molecule_id: Mapped[str|None] = mapped_column(String(36), nullable=True)
    notes:              Mapped[str|None] = mapped_column(Text, nullable=True)
    created_at:         Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ── Dataset system (replaces SequenceCollection with user-defined columns) ─────

class DatasetRow(Base):
    """A named table of antibody sequences with a user-defined schema.

    columns is a JSON array of ColumnDef objects:
      {id: str, name: str, type: "text"|"number"|"select"|"boolean", options?: str[], required?: bool}
    The three built-in columns (name, heavy_chain, light_chain) are always present
    and are NOT stored in this array.
    """
    __tablename__ = "datasets"

    id:          Mapped[str]      = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name:        Mapped[str]      = mapped_column(String(255), nullable=False)
    description: Mapped[str|None] = mapped_column(Text, nullable=True)
    columns:     Mapped[str]      = mapped_column(Text, nullable=False, default="[]")  # JSON ColumnDef[]
    created_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DatasetEntryRow(Base):
    """One row in a Dataset.  Built-in fields + arbitrary user data as JSON."""
    __tablename__ = "dataset_entries"

    id:                 Mapped[str]      = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    dataset_id:         Mapped[str]      = mapped_column(String(36), nullable=False, index=True)
    name:               Mapped[str|None] = mapped_column(String(255), nullable=True)
    heavy_chain:        Mapped[str|None] = mapped_column(Text, nullable=True)
    light_chain:        Mapped[str|None] = mapped_column(Text, nullable=True)
    source_molecule_id: Mapped[str|None] = mapped_column(String(36), nullable=True)
    data:               Mapped[str]      = mapped_column(Text, nullable=False, default="{}")  # JSON {col_id: value}
    created_at:         Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:         Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
