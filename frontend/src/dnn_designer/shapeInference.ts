// Topological shape inference for the DNN graph.
// Given nodes + edges, computes input/output tensor shapes for every node.

export { isShapeError } from "./layers";

import type { Node, Edge } from "reactflow";
import { LAYER_BY_TYPE, isShapeError } from "./layers";
import type { Shape, ShapeError } from "./layers";
import type { LayerNodeData } from "./store";

export interface ShapeInfo {
  inputShape: Shape;
  outputShape: Shape | ShapeError;
}

export type ShapeMap = Map<string, ShapeInfo>;

// Returns adjacency list (nodeId → upstream nodeId) and in-degree map
function buildGraph(nodes: Node[], edges: Edge[]) {
  const inEdges  = new Map<string, string[]>(); // nodeId → [sourceNodeId]
  const outEdges = new Map<string, string[]>(); // nodeId → [targetNodeId]
  const inDeg    = new Map<string, number>();

  for (const n of nodes) {
    inEdges.set(n.id, []);
    outEdges.set(n.id, []);
    inDeg.set(n.id, 0);
  }

  for (const e of edges) {
    if (!inEdges.has(e.source) || !inEdges.has(e.target)) continue;
    inEdges.get(e.target)!.push(e.source);
    outEdges.get(e.source)!.push(e.target);
    inDeg.set(e.target, (inDeg.get(e.target) ?? 0) + 1);
  }

  return { inEdges, outEdges, inDeg };
}

// Kahn's algorithm topological sort — returns ordered node IDs
function topoSort(nodes: Node[], inDeg: Map<string, number>, outEdges: Map<string, string[]>): string[] {
  const queue: string[] = [];
  for (const n of nodes) {
    if ((inDeg.get(n.id) ?? 0) === 0) queue.push(n.id);
  }
  const order: string[] = [];
  const deg = new Map(inDeg);
  while (queue.length) {
    const id = queue.shift()!;
    order.push(id);
    for (const next of (outEdges.get(id) ?? [])) {
      const d = (deg.get(next) ?? 1) - 1;
      deg.set(next, d);
      if (d === 0) queue.push(next);
    }
  }
  return order;
}

export function inferShapes(nodes: Node<LayerNodeData>[], edges: Edge[]): ShapeMap {
  const result: ShapeMap = new Map();
  if (!nodes.length) return result;

  const { inEdges, outEdges, inDeg } = buildGraph(nodes, edges);
  const order = topoSort(nodes, inDeg, outEdges);

  const outputShapes = new Map<string, Shape | ShapeError>();

  for (const nodeId of order) {
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) continue;

    const data = node.data as LayerNodeData;
    const def = LAYER_BY_TYPE.get(data.layerType);
    if (!def) continue;

    // Compute input shape from upstream nodes
    const upstreamIds = inEdges.get(nodeId) ?? [];
    let inputShape: Shape = [];

    if (upstreamIds.length > 0) {
      const upShape = outputShapes.get(upstreamIds[0]);
      if (upShape === undefined) {
        inputShape = [];
      } else if (isShapeError(upShape)) {
        // Propagate upstream error
        const info: ShapeInfo = { inputShape: [], outputShape: upShape };
        result.set(nodeId, info);
        outputShapes.set(nodeId, upShape);
        continue;
      } else {
        inputShape = upShape;
      }
    }

    const outputShape = def.computeOutput(inputShape, data.params as Record<string, number | boolean | string>);

    result.set(nodeId, { inputShape, outputShape });
    outputShapes.set(nodeId, outputShape);
  }

  return result;
}

// Human-readable shape string, e.g. "[B, L, 1280]" or "[B, 256]"
export function shapeLabel(shape: Shape): string {
  if (!shape.length) return "?";
  const parts = shape.map((d, i) => {
    if (i === 0) return "B";
    if (d === 0) return "L";
    return String(d);
  });
  return `[${parts.join(", ")}]`;
}

// Count trainable parameters for common layer types (approximate)
export function countParams(nodes: Node<LayerNodeData>[], _shapeMap?: ShapeMap): number {
  let total = 0;
  for (const node of nodes) {
    const data = node.data as LayerNodeData;
    const p = data.params as Record<string, number | boolean | string>;
    switch (data.layerType) {
      case "Linear":
      case "Output": {
        const inF  = Number(p.in_features  ?? p.features ?? 0);
        const outF = Number(p.out_features ?? 1);
        const bias = p.bias !== false ? 1 : 0;
        total += inF * outF + bias * outF;
        break;
      }
      case "Conv1d": {
        const inC = Number(p.in_channels  ?? 1);
        const outC = Number(p.out_channels ?? 1);
        const k   = Number(p.kernel_size  ?? 1);
        total += inC * outC * k + outC;
        break;
      }
      case "LSTM":
      case "GRU": {
        const inputSize  = Number(p.input_size  ?? 1);
        const hiddenSize = Number(p.hidden_size ?? 1);
        const layers     = Number(p.num_layers  ?? 1);
        const dirs       = p.bidirectional ? 2 : 1;
        const gates      = data.layerType === "LSTM" ? 4 : 3;
        // per layer per direction: gates * (inputSize + hiddenSize + 2) * hiddenSize
        for (let l = 0; l < layers; l++) {
          const inSize = l === 0 ? inputSize : hiddenSize * dirs;
          total += dirs * gates * (inSize + hiddenSize + 2) * hiddenSize;
        }
        break;
      }
      case "MultiheadAttention": {
        const d = Number(p.embed_dim ?? 1);
        total += 4 * d * d + 4 * d; // Q/K/V/out projections
        break;
      }
      case "TransformerEncoder": {
        const d   = Number(p.d_model         ?? 1);
        const ff  = Number(p.dim_feedforward ?? 1);
        const L   = Number(p.num_layers      ?? 1);
        const perLayer = 4 * d * d + 4 * d + 2 * d * ff + ff + d + 2 * (d + d);
        total += L * perLayer;
        break;
      }
      case "BatchNorm1d": {
        const nf = Number(p.num_features ?? 1);
        total += 2 * nf;
        break;
      }
      case "LayerNorm": {
        const ns = Number(p.normalized_shape ?? 1);
        total += 2 * ns;
        break;
      }
    }
  }
  return total;
}

export function formatParamCount(n: number): string {
  if (n === 0) return "0";
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}K`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}
