import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
} from "reactflow";
import { create } from "zustand";
import type { NodeRunStatus, Pipeline, PipelineNode, ToolSpec } from "@/types";

export interface NodeData {
  tool: ToolSpec;
  params: Record<string, unknown>;
}

interface CanvasState {
  nodes: Node[];
  edges: Edge[];
  selectedNodeId: string | null;
  runNodeStatuses: Record<string, NodeRunStatus>;
  runNodeOutputs: Record<string, Record<string, unknown>>;

  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  selectNode: (id: string | null) => void;
  updateNodeParams: (id: string, params: Record<string, unknown>) => void;
  addToolNode: (tool: ToolSpec, position: { x: number; y: number }) => void;
  setRunNodeStatuses: (statuses: Record<string, NodeRunStatus>) => void;
  setRunNodeOutputs: (outputs: Record<string, Record<string, unknown>>) => void;
  clearRunStatuses: () => void;
  loadPipeline: (pipeline: Pipeline, tools: ToolSpec[]) => void;
  toPipeline: (name: string) => Pipeline;
}

let _nodeCounter = 0;

function nodeType(toolId: string): string {
  if (toolId === "sequence_input")  return "sequenceInputNode";
  if (toolId === "target_input")    return "targetInputNode";
  if (toolId === "immunebuilder")   return "immunebuilderNode";
  if (toolId === "haddock3")        return "haddock3Node";
  if (toolId === "equidock")        return "equidockNode";
  if (toolId === "compute")         return "computeNode";
  return "toolNode";
}

function defaultParams(tool: ToolSpec): Record<string, unknown> {
  return Object.fromEntries(
    tool.inputs
      .filter((p) => p.default !== undefined && p.default !== null
        // Sentinel values are resolved server-side at run time — don't store in canvas state
        && !(typeof p.default === "string" && p.default.startsWith("__default_file__:")))
      .map((p) => [p.name, p.default])
  );
}

function fallbackHandle(
  nodes: Node[],
  nodeId: string,
  kind: "source" | "target",
  handle?: string | null
): string {
  // Generic handles are intentional — never remap them to a named port.
  // This matters for the Compute node whose target handle is "in" but whose
  // first input port is "code" (a param, not a wirable input).
  if (handle === "in" || handle === "out") return handle;
  const node = nodes.find((n) => n.id === nodeId);
  const data = node?.data as NodeData | undefined;
  const ports = kind === "source" ? data?.tool.outputs : data?.tool.inputs;
  const portNames = ports?.map((p) => p.name) ?? [];
  if (handle && portNames.includes(handle)) return handle;
  return portNames[0] ?? (kind === "source" ? "out" : "in");
}

export const useCanvasStore = create<CanvasState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  runNodeStatuses: {},
  runNodeOutputs: {},

  onNodesChange: (changes) =>
    set((s) => ({ nodes: applyNodeChanges(changes, s.nodes) })),

  onEdgesChange: (changes) =>
    set((s) => ({ edges: applyEdgeChanges(changes, s.edges) })),

  onConnect: (connection) =>
    set((s) => ({
      edges: addEdge(
        {
          ...connection,
          sourceHandle: fallbackHandle(s.nodes, connection.source!, "source", connection.sourceHandle),
          targetHandle: fallbackHandle(s.nodes, connection.target!, "target", connection.targetHandle),
        },
        s.edges
      ),
    })),

  selectNode: (id) => set({ selectedNodeId: id }),

  updateNodeParams: (id, params) =>
    set((s) => ({
      nodes: s.nodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, params } } : n
      ),
    })),

  addToolNode: (tool, position) => {
    const id = `${tool.id}_${++_nodeCounter}`;
    set((s) => ({
      nodes: [
        ...s.nodes,
        {
          id,
          type: nodeType(tool.id),
          position,
          selected: false,
          data: { tool, params: defaultParams(tool) } satisfies NodeData,
        },
      ],
    }));
  },

  setRunNodeStatuses: (statuses) => set({ runNodeStatuses: statuses }),
  setRunNodeOutputs: (outputs) => set({ runNodeOutputs: outputs }),
  clearRunStatuses: () => set({ runNodeStatuses: {}, runNodeOutputs: {} }),

  loadPipeline: (pipeline, tools) => {
    const toolMap = new Map(tools.map((t) => [t.id, t]));
    const nodes: Node[] = pipeline.nodes
      .filter((n) => toolMap.has(n.tool))
      .map((n) => ({
        id: n.id,
        type: nodeType(n.tool),
        position: n.position,
        selected: false,
        data: { tool: toolMap.get(n.tool)!, params: n.params as Record<string, unknown> } satisfies NodeData,
      }));

    _nodeCounter = nodes.reduce((max, n) => {
      const num = parseInt(n.id.split("_").pop() ?? "0", 10);
      return isNaN(num) ? max : Math.max(max, num);
    }, _nodeCounter);

    set({
      nodes,
      edges: pipeline.edges.map((e, i) => {
        const [srcNode, srcHandle] = e.source.split(".");
        const [tgtNode, tgtHandle] = e.target.split(".");
        return { id: `e_${i}`, source: srcNode, sourceHandle: srcHandle, target: tgtNode, targetHandle: tgtHandle };
      }),
      selectedNodeId: null,
      runNodeStatuses: {},
    });
  },

  toPipeline: (name) => {
    const { nodes, edges } = get();
    const pipelineNodes: PipelineNode[] = nodes.map((n) => {
      const d = n.data as NodeData;
      return { id: n.id, tool: d.tool.id, params: d.params, position: n.position };
    });
    return {
      id: crypto.randomUUID(),
      name,
      schema_version: "1",
      nodes: pipelineNodes,
      edges: edges.map((e) => ({
        source: `${e.source}.${fallbackHandle(nodes, e.source, "source", e.sourceHandle)}`,
        target: `${e.target}.${fallbackHandle(nodes, e.target, "target", e.targetHandle)}`,
      })),
    };
  },
}));
