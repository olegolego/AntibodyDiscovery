// Types mirroring backend Pydantic models.
// Keep in sync with backend/app/models/

export interface PortSpec {
  name: string;
  type: string;
  required: boolean;
  default?: unknown;
  description: string;
}

export interface RuntimeSpec {
  kind: "http" | "grpc" | "local_python" | "k8s_job";
  endpoint_env: string;
  gpu: boolean;
  timeout_seconds: number;
}

export interface ToolSpec {
  id: string;
  name: string;
  version: string;
  category: string;
  icon: string;
  description: string;
  wip: boolean;
  inputs: PortSpec[];
  outputs: PortSpec[];
  runtime: RuntimeSpec;
}

export interface NodePosition {
  x: number;
  y: number;
}

export interface PipelineNode {
  id: string;
  tool: string;
  params: Record<string, unknown>;
  position: NodePosition;
}

export interface PipelineEdge {
  source: string; // "nodeId.portName"
  target: string;
}

export interface Pipeline {
  id: string;
  name: string;
  schema_version: string;
  nodes: PipelineNode[];
  edges: PipelineEdge[];
  created_at?: string;
  updated_at?: string;
}

export type NodeRunStatus =
  | "pending"
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped";

export type RunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface NodeRun {
  node_id: string;
  status: NodeRunStatus;
  logs: string[];
  outputs: Record<string, unknown>;
  error: string | null;
}

export interface Run {
  id: string;
  pipeline_id: string;
  pipeline_snapshot: Record<string, unknown>;
  status: RunStatus;
  nodes: Record<string, NodeRun>;
  created_at?: string;
}
