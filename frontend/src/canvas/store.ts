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
import { persist } from "zustand/middleware";
import type { NodeRunStatus, Pipeline, PipelineNode, ToolSpec } from "@/types";
import { randomUUID } from "@/utils";

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
  resetCanvas: () => void;
  loadPipeline: (pipeline: Pipeline, tools: ToolSpec[]) => void;
  toPipeline: (name: string) => Pipeline;
}

let _nodeCounter = 0;

function nodeType(toolId: string): string {
  if (toolId === "sequence_input")  return "sequenceInputNode";
  if (toolId === "sequence_db")     return "sequenceDbNode";
  if (toolId === "target_input")    return "targetInputNode";
  if (toolId === "immunebuilder")   return "immunebuilderNode";
  if (toolId === "megadock")        return "megadockNode";
  if (toolId === "superwater")      return "superWaterNode";
  if (toolId === "haddock3")        return "haddock3Node";
  if (toolId === "equidock")        return "equidockNode";
  if (toolId === "compute")         return "computeNode";
  if (toolId === "cdr_mutator")     return "cdrMutatorNode";
  if (toolId === "abmap")           return "abmapNode";
  if (toolId === "iglm")            return "iglmNode";
  if (toolId === "progen2")         return "progen2Node";
  if (toolId === "loop_start")      return "loopStartNode";
  if (toolId === "loop_end")        return "loopEndNode";
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
  // Dynamic per-pose handles (complex_1, complex_2, …) are always valid as-is.
  if (handle && /^complex_\d+$/.test(handle)) return handle;
  const node = nodes.find((n) => n.id === nodeId);
  const data = node?.data as NodeData | undefined;
  const ports = kind === "source" ? data?.tool.outputs : data?.tool.inputs;
  const portNames = ports?.map((p) => p.name) ?? [];
  if (handle && portNames.includes(handle)) return handle;
  return portNames[0] ?? (kind === "source" ? "out" : "in");
}

export const useCanvasStore = create<CanvasState>()(persist((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  runNodeStatuses: {},
  runNodeOutputs: {},

  onNodesChange: (changes) =>
    set((s) => {
      const removedNodeIds = new Set(
        changes
          .filter((change) => change.type === "remove")
          .map((change) => change.id)
      );
      const nodes = applyNodeChanges(changes, s.nodes);
      const edges = removedNodeIds.size
        ? s.edges.filter((edge) => !removedNodeIds.has(edge.source) && !removedNodeIds.has(edge.target))
        : s.edges;
      return { nodes, edges };
    }),

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

  selectNode: (id) => set((s) => ({
    selectedNodeId: id,
    nodes: s.nodes.map((n) => ({ ...n, selected: n.id === id })),
  })),

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
  resetCanvas: () => { _nodeCounter = 0; set({ nodes: [], edges: [], runNodeStatuses: {}, runNodeOutputs: {} }); },

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
    const nodeIds = new Set(nodes.map((n) => n.id));
    const pipelineNodes: PipelineNode[] = nodes.map((n) => {
      const d = n.data as NodeData;
      return { id: n.id, tool: d.tool.id, params: d.params, position: n.position };
    });
    return {
      id: randomUUID(),
      name,
      schema_version: "1",
      nodes: pipelineNodes,
      edges: edges
        .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
        .map((e) => ({
          source: `${e.source}.${fallbackHandle(nodes, e.source, "source", e.sourceHandle)}`,
          target: `${e.target}.${fallbackHandle(nodes, e.target, "target", e.targetHandle)}`,
        })),
    };
  },
}), {
  name: "pdp_canvas",
  partialize: (state) => ({
    edges: state.edges,
    nodes: state.nodes.map((n) => ({
      ...n,
      data: {
        ...n.data,
        params: Object.fromEntries(
          Object.entries((n.data as { params: Record<string, unknown> }).params ?? {}).map(
            ([k, v]) => [k, typeof v === "string" && v.length > 50_000 ? "__large_omitted__" : v]
          )
        ),
      },
    })),
  }),
  onRehydrateStorage: () => (state) => {
    if (!state?.nodes?.length) return;
    _nodeCounter = state.nodes.reduce((max: number, n: Node) => {
      const num = parseInt(n.id.split("_").pop() ?? "0", 10);
      return isNaN(num) ? max : Math.max(max, num);
    }, 0);
  },
}));
