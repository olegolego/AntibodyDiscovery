// Layer type definitions for the DNN visual designer.
// Each LayerDef declares default params, how to compute output shape,
// and display metadata.

export type Shape = number[]; // 0 = variable/unknown dimension

export interface ShapeError {
  error: string;
}

export function isShapeError(x: Shape | ShapeError): x is ShapeError {
  return typeof (x as ShapeError).error === "string";
}

export interface LayerParam {
  name: string;
  type: "int" | "float" | "bool" | "select";
  default: number | boolean | string;
  min?: number;
  max?: number;
  options?: string[];
  description?: string;
}

export interface LayerDef {
  type: string;
  label: string;
  category: "io" | "core" | "activation" | "norm" | "recurrent" | "attention" | "pool" | "util";
  color: string;       // border/accent
  textColor: string;   // label text
  params: LayerParam[];
  computeOutput: (inShape: Shape, params: Record<string, number | boolean | string>) => Shape | ShapeError;
  // Short summary shown inside the node, e.g. "256 → 128"
  summary: (params: Record<string, number | boolean | string>) => string;
  // Name template for the nn.Module attribute, e.g. "linear"
  attrPrefix: string;
}

// ─── Shape helpers ───────────────────────────────────────────────────────────

function conv1dOutLen(L: number, k: number, s: number, p: number): number {
  if (L === 0) return 0; // variable
  return Math.floor((L + 2 * p - k) / s) + 1;
}

// ─── Layer catalogue ─────────────────────────────────────────────────────────

export const LAYER_DEFS: LayerDef[] = [
  // ── Input / Output ────────────────────────────────────────────────────────
  {
    // UpstreamInput — auto-placed from pipeline context, never in palette.
    // Represents a live connection from an upstream tool (AbMAP, ESM, CHEAP, dataset).
    // The adapter injects slice_start/slice_end at runtime so each node receives
    // its slice of the concatenated embedding tensor.
    type: "UpstreamInput",
    label: "Pipeline Input",
    category: "io",
    color: "#fb7185",
    textColor: "text-rose-300",
    attrPrefix: "upstream",
    params: [
      { name: "features", type: "int", default: 320, min: 1, description: "Embedding dim from connected upstream tool" },
      // port, toolId, toolName are stored in params but not listed here — they don't
      // appear in LayerParamPanel because LayerDef.params doesn't include them.
    ],
    computeOutput: (_in, p) => [0, Number(p.features)],
    summary: (p) => `[B, ${p.features}]`,
  },
  {
    type: "Input",
    label: "Input",
    category: "io",
    color: "#34d399",
    textColor: "text-emerald-300",
    attrPrefix: "input",
    params: [
      { name: "features", type: "int", default: 1280, min: 1, description: "Feature dimension (e.g. 1280 for ESM-650M)" },
    ],
    computeOutput: (_in, p) => [0, Number(p.features)],
    summary: (p) => `[B, ${p.features}]`,
  },
  {
    type: "Input3D",
    label: "Input 3D",
    category: "io",
    color: "#34d399",
    textColor: "text-emerald-300",
    attrPrefix: "input3d",
    params: [
      { name: "features", type: "int", default: 1280, min: 1, description: "Feature dim per position" },
    ],
    computeOutput: (_in, p) => [0, 0, Number(p.features)],
    summary: (p) => `[B, L, ${p.features}]`,
  },
  {
    type: "Output",
    label: "Output",
    category: "io",
    color: "#f87171",
    textColor: "text-red-300",
    attrPrefix: "output",
    params: [
      { name: "out_features", type: "int", default: 1, min: 1, description: "Number of output units" },
      { name: "task", type: "select", default: "regression", options: ["regression", "binary_classification", "multiclass"], description: "Training task type" },
    ],
    computeOutput: (inShape, p) => {
      if (inShape.length === 0) return { error: "No input connected" };
      const batch = inShape.slice(0, -1);
      return [...batch, Number(p.out_features)];
    },
    summary: (p) => `→ ${p.out_features} (${p.task})`,
  },

  // ── Core layers ───────────────────────────────────────────────────────────
  {
    type: "Linear",
    label: "Linear",
    category: "core",
    color: "#818cf8",
    textColor: "text-indigo-300",
    attrPrefix: "linear",
    params: [
      { name: "in_features",  type: "int", default: 256, min: 1 },
      { name: "out_features", type: "int", default: 128, min: 1 },
      { name: "bias", type: "bool", default: true },
    ],
    computeOutput: (inShape, p) => {
      if (inShape.length === 0) return { error: "No input connected" };
      const last = inShape[inShape.length - 1];
      const inF = Number(p.in_features);
      if (last !== 0 && last !== inF) {
        return { error: `in_features mismatch: expected ${inF}, got ${last}` };
      }
      return [...inShape.slice(0, -1), Number(p.out_features)];
    },
    summary: (p) => `${p.in_features} → ${p.out_features}`,
  },
  {
    type: "Conv1d",
    label: "Conv1d",
    category: "core",
    color: "#818cf8",
    textColor: "text-indigo-300",
    attrPrefix: "conv1d",
    params: [
      { name: "in_channels",  type: "int", default: 64,  min: 1 },
      { name: "out_channels", type: "int", default: 128, min: 1 },
      { name: "kernel_size",  type: "int", default: 3,   min: 1 },
      { name: "stride",       type: "int", default: 1,   min: 1 },
      { name: "padding",      type: "int", default: 1,   min: 0 },
    ],
    computeOutput: (inShape, p) => {
      if (inShape.length < 2) return { error: "Conv1d expects [B, C, L] input" };
      const L = inShape[inShape.length - 1];
      const outC = Number(p.out_channels);
      const outL = conv1dOutLen(L, Number(p.kernel_size), Number(p.stride), Number(p.padding));
      // Input must be [B, C, L] — 3D
      if (inShape.length === 2) {
        return { error: "Conv1d expects 3D input [B, C, L]. Use Reshape or Unsqueeze first." };
      }
      return [inShape[0], outC, outL];
    },
    summary: (p) => `${p.in_channels}→${p.out_channels} k=${p.kernel_size}`,
  },

  // ── Activations ───────────────────────────────────────────────────────────
  {
    type: "ReLU",
    label: "ReLU",
    category: "activation",
    color: "#fbbf24",
    textColor: "text-amber-300",
    attrPrefix: "relu",
    params: [],
    computeOutput: (inShape) => inShape.length ? inShape : { error: "No input" },
    summary: () => "ReLU",
  },
  {
    type: "GELU",
    label: "GELU",
    category: "activation",
    color: "#fbbf24",
    textColor: "text-amber-300",
    attrPrefix: "gelu",
    params: [],
    computeOutput: (inShape) => inShape.length ? inShape : { error: "No input" },
    summary: () => "GELU",
  },
  {
    type: "Sigmoid",
    label: "Sigmoid",
    category: "activation",
    color: "#fbbf24",
    textColor: "text-amber-300",
    attrPrefix: "sigmoid",
    params: [],
    computeOutput: (inShape) => inShape.length ? inShape : { error: "No input" },
    summary: () => "Sigmoid",
  },
  {
    type: "Tanh",
    label: "Tanh",
    category: "activation",
    color: "#fbbf24",
    textColor: "text-amber-300",
    attrPrefix: "tanh",
    params: [],
    computeOutput: (inShape) => inShape.length ? inShape : { error: "No input" },
    summary: () => "Tanh",
  },
  {
    type: "Softmax",
    label: "Softmax",
    category: "activation",
    color: "#fbbf24",
    textColor: "text-amber-300",
    attrPrefix: "softmax",
    params: [
      { name: "dim", type: "int", default: -1, description: "Dimension to apply softmax along" },
    ],
    computeOutput: (inShape) => inShape.length ? inShape : { error: "No input" },
    summary: () => "Softmax(dim=-1)",
  },

  // ── Normalisation ─────────────────────────────────────────────────────────
  {
    type: "BatchNorm1d",
    label: "BatchNorm1d",
    category: "norm",
    color: "#a78bfa",
    textColor: "text-violet-300",
    attrPrefix: "bn",
    params: [
      { name: "num_features", type: "int", default: 256, min: 1 },
      { name: "eps",          type: "float", default: 1e-5 },
      { name: "momentum",     type: "float", default: 0.1 },
    ],
    computeOutput: (inShape, p) => {
      if (inShape.length === 0) return { error: "No input" };
      const last = inShape[inShape.length - 1];
      const nf = Number(p.num_features);
      if (last !== 0 && last !== nf)
        return { error: `num_features mismatch: expected ${nf}, got ${last}` };
      return inShape;
    },
    summary: (p) => `${p.num_features} features`,
  },
  {
    type: "LayerNorm",
    label: "LayerNorm",
    category: "norm",
    color: "#a78bfa",
    textColor: "text-violet-300",
    attrPrefix: "ln",
    params: [
      { name: "normalized_shape", type: "int", default: 256, min: 1, description: "Last dimension size" },
    ],
    computeOutput: (inShape, p) => {
      if (inShape.length === 0) return { error: "No input" };
      const last = inShape[inShape.length - 1];
      const ns = Number(p.normalized_shape);
      if (last !== 0 && last !== ns)
        return { error: `normalized_shape mismatch: expected ${ns}, got ${last}` };
      return inShape;
    },
    summary: (p) => `norm ${p.normalized_shape}`,
  },
  {
    type: "Dropout",
    label: "Dropout",
    category: "norm",
    color: "#a78bfa",
    textColor: "text-violet-300",
    attrPrefix: "dropout",
    params: [
      { name: "p", type: "float", default: 0.5, min: 0, max: 1, description: "Drop probability" },
    ],
    computeOutput: (inShape) => inShape.length ? inShape : { error: "No input" },
    summary: (p) => `p=${p.p}`,
  },

  // ── Recurrent ─────────────────────────────────────────────────────────────
  {
    type: "LSTM",
    label: "LSTM",
    category: "recurrent",
    color: "#38bdf8",
    textColor: "text-sky-300",
    attrPrefix: "lstm",
    params: [
      { name: "input_size",    type: "int",  default: 256, min: 1 },
      { name: "hidden_size",   type: "int",  default: 128, min: 1 },
      { name: "num_layers",    type: "int",  default: 1,   min: 1 },
      { name: "bidirectional", type: "bool", default: false },
      { name: "dropout",       type: "float", default: 0,  min: 0, max: 1 },
      { name: "return_last",   type: "bool", default: false, description: "Return last hidden state instead of all outputs" },
    ],
    computeOutput: (inShape, p) => {
      if (inShape.length < 2) return { error: "LSTM expects [B, L, D] input" };
      const dirs = p.bidirectional ? 2 : 1;
      const hidden = Number(p.hidden_size) * dirs;
      if (p.return_last) return [inShape[0], hidden];
      return [inShape[0], inShape[1], hidden];
    },
    summary: (p) => `h=${p.hidden_size}${p.bidirectional ? " bi" : ""}`,
  },
  {
    type: "GRU",
    label: "GRU",
    category: "recurrent",
    color: "#38bdf8",
    textColor: "text-sky-300",
    attrPrefix: "gru",
    params: [
      { name: "input_size",    type: "int",  default: 256, min: 1 },
      { name: "hidden_size",   type: "int",  default: 128, min: 1 },
      { name: "num_layers",    type: "int",  default: 1,   min: 1 },
      { name: "bidirectional", type: "bool", default: false },
      { name: "dropout",       type: "float", default: 0,  min: 0, max: 1 },
      { name: "return_last",   type: "bool", default: false },
    ],
    computeOutput: (inShape, p) => {
      if (inShape.length < 2) return { error: "GRU expects [B, L, D] input" };
      const dirs = p.bidirectional ? 2 : 1;
      const hidden = Number(p.hidden_size) * dirs;
      if (p.return_last) return [inShape[0], hidden];
      return [inShape[0], inShape[1], hidden];
    },
    summary: (p) => `h=${p.hidden_size}${p.bidirectional ? " bi" : ""}`,
  },

  // ── Attention / Transformer ───────────────────────────────────────────────
  {
    type: "MultiheadAttention",
    label: "Multihead Attention",
    category: "attention",
    color: "#fb7185",
    textColor: "text-rose-300",
    attrPrefix: "attn",
    params: [
      { name: "embed_dim",  type: "int",   default: 256, min: 1, description: "Must equal input feature dim" },
      { name: "num_heads",  type: "int",   default: 8,   min: 1 },
      { name: "dropout",    type: "float", default: 0,   min: 0, max: 1 },
    ],
    computeOutput: (inShape, p) => {
      if (inShape.length < 2) return { error: "Attention expects [B, L, D]" };
      const last = inShape[inShape.length - 1];
      const ed = Number(p.embed_dim);
      if (last !== 0 && last !== ed)
        return { error: `embed_dim mismatch: expected ${ed}, got ${last}` };
      return inShape;
    },
    summary: (p) => `d=${p.embed_dim} h=${p.num_heads}`,
  },
  {
    type: "TransformerEncoder",
    label: "Transformer Encoder",
    category: "attention",
    color: "#fb7185",
    textColor: "text-rose-300",
    attrPrefix: "transformer",
    params: [
      { name: "d_model",         type: "int",   default: 256, min: 1 },
      { name: "nhead",           type: "int",   default: 8,   min: 1 },
      { name: "num_layers",      type: "int",   default: 2,   min: 1 },
      { name: "dim_feedforward", type: "int",   default: 512, min: 1 },
      { name: "dropout",         type: "float", default: 0.1, min: 0, max: 1 },
    ],
    computeOutput: (inShape, p) => {
      if (inShape.length < 2) return { error: "TransformerEncoder expects [B, L, D]" };
      const last = inShape[inShape.length - 1];
      const dm = Number(p.d_model);
      if (last !== 0 && last !== dm)
        return { error: `d_model mismatch: expected ${dm}, got ${last}` };
      return inShape;
    },
    summary: (p) => `d=${p.d_model} L=${p.num_layers}`,
  },

  // ── Pooling ───────────────────────────────────────────────────────────────
  {
    type: "GlobalAvgPool",
    label: "Global Avg Pool",
    category: "pool",
    color: "#f97316",
    textColor: "text-orange-300",
    attrPrefix: "gap",
    params: [],
    computeOutput: (inShape) => {
      if (inShape.length !== 3) return { error: "GlobalAvgPool expects 3D input [B, L, D]" };
      return [inShape[0], inShape[2]];
    },
    summary: () => "mean over L",
  },
  {
    type: "GlobalMaxPool",
    label: "Global Max Pool",
    category: "pool",
    color: "#f97316",
    textColor: "text-orange-300",
    attrPrefix: "gmp",
    params: [],
    computeOutput: (inShape) => {
      if (inShape.length !== 3) return { error: "GlobalMaxPool expects 3D input [B, L, D]" };
      return [inShape[0], inShape[2]];
    },
    summary: () => "max over L",
  },

  // ── Utility ───────────────────────────────────────────────────────────────
  {
    type: "Flatten",
    label: "Flatten",
    category: "util",
    color: "#94a3b8",
    textColor: "text-slate-300",
    attrPrefix: "flatten",
    params: [],
    computeOutput: (inShape) => {
      if (inShape.length < 2) return { error: "Nothing to flatten" };
      const prod = inShape.slice(1).reduce((a, b) => {
        if (a === 0 || b === 0) return 0;
        return a * b;
      }, 1);
      return [inShape[0], prod];
    },
    summary: () => "flatten",
  },
  {
    type: "Residual",
    label: "Residual",
    category: "util",
    color: "#94a3b8",
    textColor: "text-slate-300",
    attrPrefix: "residual",
    params: [],
    computeOutput: (inShape) => inShape.length ? inShape : { error: "No input" },
    summary: () => "x + branch",
  },
];

export const LAYER_BY_TYPE = new Map<string, LayerDef>(LAYER_DEFS.map((d) => [d.type, d]));

export const CATEGORY_LABELS: Record<LayerDef["category"], string> = {
  io:         "Input / Output",
  core:       "Core Layers",
  activation: "Activations",
  norm:       "Normalization",
  recurrent:  "Recurrent",
  attention:  "Attention",
  pool:       "Pooling",
  util:       "Utilities",
};

export const CATEGORY_ORDER: LayerDef["category"][] = [
  "io", "core", "activation", "norm", "recurrent", "attention", "pool", "util",
];
