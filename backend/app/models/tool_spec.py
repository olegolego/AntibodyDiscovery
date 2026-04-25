from enum import Enum
from typing import Any

from pydantic import BaseModel


class RuntimeKind(str, Enum):
    HTTP = "http"
    GRPC = "grpc"
    LOCAL_PYTHON = "local_python"
    K8S_JOB = "k8s_job"


class PortSpec(BaseModel):
    name: str
    type: str
    required: bool = True
    default: Any = None
    default_file: str | None = None  # path relative to backend/ dir; content loaded at registry startup
    description: str = ""


class RuntimeSpec(BaseModel):
    kind: RuntimeKind
    endpoint_env: str = ""
    gpu: bool = False
    timeout_seconds: int = 3600


class ToolSpec(BaseModel):
    id: str
    name: str
    version: str
    category: str
    icon: str = ""
    description: str = ""
    wip: bool = False  # marks toolbox/experimental tools; adapter raises NotImplementedError
    inputs: list[PortSpec] = []
    outputs: list[PortSpec] = []
    runtime: RuntimeSpec
