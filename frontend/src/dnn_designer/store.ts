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
import { LAYER_BY_TYPE } from "./layers";
import { randomUUID } from "@/utils";

export interface LayerNodeData {
  layerType: string;
  params: Record<string, unknown>;
}

export interface ArchitectureSpec {
  version: "1.0";
  nodes: Array<{
    id: string;
    type: string;
    params: Record<string, unknown>;
    position: { x: number; y: number };
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
  }>;
}

interface DNNDesignerState {
  nodes: Node<LayerNodeData>[];
  edges: Edge[];
  selectedNodeId: string | null;
  architectureName: string;
  dirty: boolean;

  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  selectNode: (id: string | null) => void;
  addLayer: (layerType: string, position: { x: number; y: number }, extraParams?: Record<string, unknown>) => void;
  updateLayerParams: (id: string, params: Record<string, unknown>) => void;
  setArchitectureName: (name: string) => void;
  loadSpec: (spec: ArchitectureSpec) => void;
  toSpec: () => ArchitectureSpec;
  reset: () => void;
  markClean: () => void;
}

let _counter = 0;

function defaultParams(layerType: string): Record<string, unknown> {
  const def = LAYER_BY_TYPE.get(layerType);
  if (!def) return {};
  return Object.fromEntries(def.params.map((p) => [p.name, p.default]));
}

export const useDNNStore = create<DNNDesignerState>()((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  architectureName: "My DNN",
  dirty: false,

  onNodesChange: (changes) =>
    set((s) => ({ nodes: applyNodeChanges(changes, s.nodes) as Node<LayerNodeData>[], dirty: true })),

  onEdgesChange: (changes) =>
    set((s) => ({ edges: applyEdgeChanges(changes, s.edges), dirty: true })),

  onConnect: (connection) =>
    set((s) => ({
      edges: addEdge({ ...connection, id: randomUUID() }, s.edges),
      dirty: true,
    })),

  selectNode: (id) =>
    set((s) => ({
      selectedNodeId: id,
      nodes: s.nodes.map((n) => ({ ...n, selected: n.id === id })),
    })),

  addLayer: (layerType, position, extraParams?) => {
    const id = `${layerType}_${++_counter}`;
    const newNode: Node<LayerNodeData> = {
      id,
      type: "layerNode",
      position,
      selected: false,
      data: { layerType, params: { ...defaultParams(layerType), ...(extraParams ?? {}) } },
    };
    set((s) => ({ nodes: [...s.nodes, newNode], dirty: true }));
  },

  updateLayerParams: (id, params) =>
    set((s) => ({
      nodes: s.nodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, params } } : n
      ),
      dirty: true,
    })),

  setArchitectureName: (name) => set({ architectureName: name, dirty: true }),

  loadSpec: (spec) => {
    _counter = 0;
    const nodes: Node<LayerNodeData>[] = spec.nodes.map((n) => {
      const num = parseInt(n.id.split("_").pop() ?? "0", 10);
      if (!isNaN(num)) _counter = Math.max(_counter, num);
      return {
        id: n.id,
        type: "layerNode",
        position: n.position,
        selected: false,
        data: { layerType: n.type, params: n.params },
      };
    });
    const edges: Edge[] = spec.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
    }));
    set({ nodes, edges, selectedNodeId: null, dirty: false });
  },

  toSpec: (): ArchitectureSpec => {
    const { nodes, edges } = get();
    return {
      version: "1.0",
      nodes: nodes.map((n) => ({
        id: n.id,
        type: n.data.layerType,
        params: n.data.params,
        position: n.position,
      })),
      edges: edges.map((e) => ({
        id: e.id ?? randomUUID(),
        source: e.source,
        target: e.target,
      })),
    };
  },

  reset: () => {
    _counter = 0;
    set({ nodes: [], edges: [], selectedNodeId: null, dirty: false });
  },

  markClean: () => set({ dirty: false }),
}));
