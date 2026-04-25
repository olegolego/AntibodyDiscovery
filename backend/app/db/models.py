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
    """HADDOCK3 docking result, linked to the antibody structure that was docked."""
    __tablename__ = "docking_results"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    antibody_structure_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    molecule_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    antigen_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    best_complex_pdb: Mapped[str | None] = mapped_column(Text, nullable=True)
    scores: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
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
