from pydantic import BaseModel, Field
import uuid


class NodePosition(BaseModel):
    x: float
    y: float


class PipelineNode(BaseModel):
    id: str
    tool: str
    params: dict = Field(default_factory=dict)
    position: NodePosition


class PipelineEdge(BaseModel):
    # format: "<node_id>.<port_name>"
    source: str
    target: str


class Pipeline(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    schema_version: str = "1"
    nodes: list[PipelineNode] = []
    edges: list[PipelineEdge] = []
