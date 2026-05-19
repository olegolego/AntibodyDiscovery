// Generates PyTorch nn.Module code from the visual layer graph.

import type { Node, Edge } from "reactflow";
import { LAYER_BY_TYPE, isShapeError } from "./layers";
import type { ShapeMap } from "./shapeInference";
import { shapeLabel, countParams, formatParamCount } from "./shapeInference";
import type { LayerNodeData } from "./store";

// Kahn's topological sort (duplicated to avoid circular imports)
function topoOrder(nodes: Node[], edges: Edge[]): string[] {
  const outEdges = new Map<string, string[]>();
  const inDeg    = new Map<string, number>();
  for (const n of nodes) { outEdges.set(n.id, []); inDeg.set(n.id, 0); }
  for (const e of edges) {
    if (!outEdges.has(e.source) || !inDeg.has(e.target)) continue;
    outEdges.get(e.source)!.push(e.target);
    inDeg.set(e.target, (inDeg.get(e.target) ?? 0) + 1);
  }
  const queue = nodes.filter((n) => (inDeg.get(n.id) ?? 0) === 0).map((n) => n.id);
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

function attrName(nodeId: string): string {
  return nodeId.replace(/[^a-zA-Z0-9_]/g, "_");
}

export function generatePyTorch(
  nodes: Node<LayerNodeData>[],
  edges: Edge[],
  shapes: ShapeMap,
): string {
  if (!nodes.length) return "# Add layers to get started.";

  const order = topoOrder(nodes, edges);
  // upstream map: nodeId → [sourceNodeId]
  const upstream = new Map<string, string[]>();
  for (const n of nodes) upstream.set(n.id, []);
  for (const e of edges) {
    if (upstream.has(e.target)) upstream.get(e.target)!.push(e.source);
  }

  const inits: string[] = [];
  const forwards: string[] = [];

  // Track variable names for branching: nodeId → varName
  const varName = new Map<string, string>();
  let varCounter = 0;

  for (const nodeId of order) {
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) continue;

    const data = node.data as LayerNodeData;
    const def = LAYER_BY_TYPE.get(data.layerType);
    if (!def) continue;

    const p = data.params as Record<string, number | boolean | string>;
    const info = shapes.get(nodeId);
    const outShape = info?.outputShape;
    const outLabel = outShape && !isShapeError(outShape) ? shapeLabel(outShape) : "?";
    const attr = attrName(nodeId);
    const ups = upstream.get(nodeId) ?? [];

    // Determine input variable name
    let inputVar = "x";
    if (ups.length === 1) {
      inputVar = varName.get(ups[0]) ?? "x";
    } else if (ups.length > 1) {
      // Multiple inputs → concatenate (for Residual: add)
      const upVars = ups.map((u) => varName.get(u) ?? "x");
      if (data.layerType === "Residual") {
        inputVar = `(${upVars[0]} + ${upVars[1] ?? upVars[0]})`;
      } else {
        inputVar = `torch.cat([${upVars.join(", ")}], dim=-1)`;
      }
    }

    // Output variable name
    let outVar = "x";
    if (varCounter === 0 && nodeId === order[0]) {
      outVar = "x";
    } else {
      outVar = "x";
    }
    // For non-linear graphs, use unique names
    const multiOut = nodes.some((n) => {
      const u = upstream.get(n.id) ?? [];
      return u.length > 1;
    });
    if (multiOut) {
      outVar = `h${++varCounter}`;
    }
    varName.set(nodeId, outVar);

    switch (data.layerType) {
      case "Input":
      case "Input3D":
        forwards.push(`        # ${outVar}: ${outLabel} — input tensor`);
        varName.set(nodeId, "x");
        break;

      case "Output": {
        const outF = Number(p.out_features ?? 1);
        const inF  = info?.inputShape ? info.inputShape[info.inputShape.length - 1] : 0;
        inits.push(`        self.${attr} = nn.Linear(${inF || "???"}, ${outF}, bias=${p.bias !== false})`);
        forwards.push(`        ${outVar} = self.${attr}(${inputVar})  # ${outLabel}`);
        break;
      }

      case "Linear": {
        const inF  = Number(p.in_features  ?? 1);
        const outF = Number(p.out_features ?? 1);
        inits.push(`        self.${attr} = nn.Linear(${inF}, ${outF}, bias=${p.bias !== false})`);
        forwards.push(`        ${outVar} = self.${attr}(${inputVar})  # ${outLabel}`);
        break;
      }

      case "Conv1d": {
        const inC  = Number(p.in_channels  ?? 1);
        const outC = Number(p.out_channels ?? 1);
        const k    = Number(p.kernel_size  ?? 3);
        const s    = Number(p.stride       ?? 1);
        const pad  = Number(p.padding      ?? 0);
        inits.push(`        self.${attr} = nn.Conv1d(${inC}, ${outC}, kernel_size=${k}, stride=${s}, padding=${pad})`);
        forwards.push(`        ${outVar} = self.${attr}(${inputVar})  # ${outLabel}`);
        break;
      }

      case "LSTM": {
        const inputSize  = Number(p.input_size  ?? 1);
        const hiddenSize = Number(p.hidden_size ?? 1);
        const layers     = Number(p.num_layers  ?? 1);
        const bidir      = p.bidirectional ? "True" : "False";
        const drop       = Number(p.dropout     ?? 0);
        inits.push(`        self.${attr} = nn.LSTM(${inputSize}, ${hiddenSize}, num_layers=${layers}, bidirectional=${bidir}, dropout=${drop}, batch_first=True)`);
        if (p.return_last) {
          forwards.push(`        _, (${outVar}_h, _) = self.${attr}(${inputVar})  # last hidden`);
          forwards.push(`        ${outVar} = ${outVar}_h[-1]  # ${outLabel}`);
          varName.set(nodeId, outVar);
        } else {
          forwards.push(`        ${outVar}, _ = self.${attr}(${inputVar})  # ${outLabel}`);
        }
        break;
      }

      case "GRU": {
        const inputSize  = Number(p.input_size  ?? 1);
        const hiddenSize = Number(p.hidden_size ?? 1);
        const layers     = Number(p.num_layers  ?? 1);
        const bidir      = p.bidirectional ? "True" : "False";
        const drop       = Number(p.dropout     ?? 0);
        inits.push(`        self.${attr} = nn.GRU(${inputSize}, ${hiddenSize}, num_layers=${layers}, bidirectional=${bidir}, dropout=${drop}, batch_first=True)`);
        if (p.return_last) {
          forwards.push(`        _, ${outVar}_h = self.${attr}(${inputVar})`);
          forwards.push(`        ${outVar} = ${outVar}_h[-1]  # ${outLabel}`);
        } else {
          forwards.push(`        ${outVar}, _ = self.${attr}(${inputVar})  # ${outLabel}`);
        }
        break;
      }

      case "MultiheadAttention": {
        const ed  = Number(p.embed_dim  ?? 1);
        const nh  = Number(p.num_heads  ?? 1);
        const drop = Number(p.dropout   ?? 0);
        inits.push(`        self.${attr} = nn.MultiheadAttention(${ed}, ${nh}, dropout=${drop}, batch_first=True)`);
        forwards.push(`        ${outVar}, _ = self.${attr}(${inputVar}, ${inputVar}, ${inputVar})  # ${outLabel}`);
        break;
      }

      case "TransformerEncoder": {
        const dm  = Number(p.d_model         ?? 1);
        const nh  = Number(p.nhead           ?? 1);
        const nl  = Number(p.num_layers      ?? 1);
        const ff  = Number(p.dim_feedforward ?? 1);
        const drop = Number(p.dropout        ?? 0.1);
        inits.push(`        _enc_layer = nn.TransformerEncoderLayer(d_model=${dm}, nhead=${nh}, dim_feedforward=${ff}, dropout=${drop}, batch_first=True)`);
        inits.push(`        self.${attr} = nn.TransformerEncoder(_enc_layer, num_layers=${nl})`);
        forwards.push(`        ${outVar} = self.${attr}(${inputVar})  # ${outLabel}`);
        break;
      }

      case "ReLU":
        inits.push(`        self.${attr} = nn.ReLU()`);
        forwards.push(`        ${outVar} = self.${attr}(${inputVar})`);
        break;
      case "GELU":
        inits.push(`        self.${attr} = nn.GELU()`);
        forwards.push(`        ${outVar} = self.${attr}(${inputVar})`);
        break;
      case "Sigmoid":
        inits.push(`        self.${attr} = nn.Sigmoid()`);
        forwards.push(`        ${outVar} = self.${attr}(${inputVar})`);
        break;
      case "Tanh":
        inits.push(`        self.${attr} = nn.Tanh()`);
        forwards.push(`        ${outVar} = self.${attr}(${inputVar})`);
        break;
      case "Softmax": {
        const dim = Number(p.dim ?? -1);
        inits.push(`        self.${attr} = nn.Softmax(dim=${dim})`);
        forwards.push(`        ${outVar} = self.${attr}(${inputVar})`);
        break;
      }

      case "BatchNorm1d": {
        const nf = Number(p.num_features ?? 1);
        const eps = Number(p.eps ?? 1e-5);
        const mom = Number(p.momentum ?? 0.1);
        inits.push(`        self.${attr} = nn.BatchNorm1d(${nf}, eps=${eps}, momentum=${mom})`);
        forwards.push(`        ${outVar} = self.${attr}(${inputVar})`);
        break;
      }
      case "LayerNorm": {
        const ns = Number(p.normalized_shape ?? 1);
        inits.push(`        self.${attr} = nn.LayerNorm(${ns})`);
        forwards.push(`        ${outVar} = self.${attr}(${inputVar})`);
        break;
      }
      case "Dropout": {
        const prob = Number(p.p ?? 0.5);
        inits.push(`        self.${attr} = nn.Dropout(p=${prob})`);
        forwards.push(`        ${outVar} = self.${attr}(${inputVar})`);
        break;
      }

      case "GlobalAvgPool":
        forwards.push(`        ${outVar} = ${inputVar}.mean(dim=1)  # ${outLabel}`);
        break;
      case "GlobalMaxPool":
        forwards.push(`        ${outVar} = ${inputVar}.max(dim=1).values  # ${outLabel}`);
        break;
      case "Flatten":
        inits.push(`        self.${attr} = nn.Flatten()`);
        forwards.push(`        ${outVar} = self.${attr}(${inputVar})  # ${outLabel}`);
        break;
      case "Residual":
        forwards.push(`        ${outVar} = ${inputVar}  # residual passthrough`);
        break;

      default:
        forwards.push(`        # ${data.layerType}: not yet generated`);
        break;
    }
  }

  const totalParams = countParams(nodes, shapes);
  const paramStr = formatParamCount(totalParams);

  const lines: string[] = [
    "import torch",
    "import torch.nn as nn",
    "",
    "",
    "class CustomDNN(nn.Module):",
    "    def __init__(self):",
    "        super().__init__()",
    ...inits,
    "",
    "    def forward(self, x: torch.Tensor) -> torch.Tensor:",
    ...forwards,
    "        return x",
    "",
    `# Trainable parameters: ~${paramStr}`,
  ];

  return lines.join("\n");
}
