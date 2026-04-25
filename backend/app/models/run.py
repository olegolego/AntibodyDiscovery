import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeRunStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class NodeRun(BaseModel):
    node_id: str
    status: NodeRunStatus = NodeRunStatus.PENDING
    logs: list[str] = []
    outputs: dict[str, Any] = {}
    error: str | None = None


class Run(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pipeline_id: str
    pipeline_snapshot: dict
    status: RunStatus = RunStatus.QUEUED
    nodes: dict[str, NodeRun] = {}
