import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Database, BrainCircuit, X, Layers, Eye, Zap, FlaskConical } from "lucide-react";
import { useCanvasStore, type NodeData } from "./store";
import { ComputePanel, LoopEndPanel } from "./ComputePanel";
import { listDatasets } from "@/api/datasets";
import type { ArchitectureSpec } from "@/dnn_designer/store";
import type { RLSpec } from "@/rl_designer/store";

const TYPE_INPUT: Record<string, string> = {
  int: "number",
  float: "number",
  bool: "checkbox",
};

const CATEGORY_COLOR: Record<string, string> = {
  input:                "#fbbf24",
  structure_prediction: "#38bdf8",
  structure_design:     "#a78bfa",
  sequence_design:      "#34d399",
  sequence_embedding:   "#fb7185",
  docking:              "#f97316",
  toolbox:              "#e879f9",
  compute:              "#818cf8",
  control_flow:         "#06b6d4",
  bioinformatics:       "#2dd4bf",
  design:               "#f472b6",
  ml:                   "#a3e635",
  loop:                 "#facc15",
  debug:                "#94a3b8",
};

const ARTIFACT_SENTINEL = "__artifact__";

// Names always available regardless of custom columns
const BUILTIN_COLS = ["heavy_chain", "light_chain"];

function colDropdown(
  label: string,
  value: string,
  options: string[],
  onChange: (v: string) => void,
  optional?: boolean,
) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-slate-500 w-20 shrink-0">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1 bg-[#1a1f2e] border border-border rounded px-2 py-1 text-xs
          text-slate-200 focus:outline-none focus:border-amber-500/60 cursor-pointer"
      >
        {optional && <option value="" className="bg-surface2">— (none)</option>}
        {options.map((o) => (
          <option key={o} value={o} className="bg-surface2">{o}</option>
        ))}
      </select>
    </div>
  );
}

// ── Full dataset config block (dataset picker + column mapping) ────────────
function DatasetPicker({
  datasetId,
  params,
  onParamChange,
}: {
  datasetId: string;
  params: Record<string, unknown>;
  onParamChange: (name: string, value: unknown) => void;
}) {
  // Shared cache across all DatasetPicker instances — no duplicate fetches
  const { data: datasets = [], isLoading: loading } = useQuery({
    queryKey: ["datasets"],
    queryFn: listDatasets,
    staleTime: 60_000,   // serve from cache for 60 s
  });

  const selected = datasets.find((d) => d.id === datasetId);
  const customCols = selected?.columns?.map((c) => c.name) ?? [];
  const allCols = [...BUILTIN_COLS, ...customCols];

  const vhCol    = String(params.vh_column    ?? "heavy_chain");
  const vlCol    = String(params.vl_column    ?? "light_chain");
  const labelCol = String(params.label_column ?? "");

  return (
    <div className="flex flex-col gap-2">
      {/* Dataset selector */}
      <select
        value={datasetId}
        onChange={(e) => onParamChange("dataset_id", e.target.value)}
        disabled={loading}
        className="bg-canvas border border-border rounded-lg px-3 py-2 text-sm
          text-slate-200 focus:outline-none focus:border-amber-500/60
          transition-colors w-full cursor-pointer disabled:opacity-50"
      >
        <option value="" className="bg-surface2">
          {loading ? "Loading…" : "Select a dataset…"}
        </option>
        {datasets.map((ds) => (
          <option key={ds.id} value={ds.id} className="bg-surface2">
            {ds.name} ({ds.entry_count})
          </option>
        ))}
      </select>

      {/* Dataset info card + column mapping */}
      {selected && (
        <div className="flex flex-col gap-2 px-2.5 py-2.5 rounded-lg bg-amber-950/30 border border-amber-800/30">
          <div className="flex items-center gap-2">
            <Database size={11} className="text-amber-400 shrink-0" />
            <span className="text-[11px] text-amber-300 font-semibold truncate">{selected.name}</span>
            <span className="text-[10px] text-slate-500 ml-auto shrink-0">{selected.entry_count} entries</span>
          </div>

          {/* Column mapping */}
          <div className="flex flex-col gap-1.5 pt-0.5 border-t border-amber-900/40">
            {colDropdown("VH column", vhCol, allCols, (v) => onParamChange("vh_column", v))}
            {colDropdown("VL column", vlCol, allCols, (v) => onParamChange("vl_column", v))}
            {colDropdown(
              "Label col",
              labelCol,
              allCols,
              (v) => onParamChange("label_column", v),
              true, // optional
            )}
          </div>

          {/* Custom column type chips */}
          {customCols.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-0.5">
              {selected.columns!.map((col) => (
                <span
                  key={col.id}
                  className="px-1 py-0.5 rounded text-[9px] font-mono bg-slate-800 text-slate-400"
                  title={col.type}
                >
                  {col.name}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Model picker (unchanged) ───────────────────────────────────────────────
interface ModelMeta {
  id: string;
  name: string;
  task?: string;
  embedding_model?: string;
  num_sequences?: number;
  metrics?: Record<string, unknown>;
  created_at?: string;
}

function ModelPicker({ value, onChange }: {
  value: unknown;
  onChange: (artifact: { __model_id__: string } | null) => void;
}) {
  const [models, setModels] = useState<ModelMeta[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/models/")
      .then((r) => r.json())
      .then((data: ModelMeta[]) => setModels(data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const selectedId = (value && typeof value === "object" && "__model_id__" in (value as object))
    ? (value as { __model_id__: string }).__model_id__
    : "";

  const selected = models.find((m) => m.id === selectedId);

  function metricLine(m: ModelMeta) {
    if (!m.metrics) return null;
    const v = m.metrics.val_rmse ?? m.metrics.val_acc ?? m.metrics.val_loss;
    if (v === undefined) return null;
    const key = m.metrics.val_rmse !== undefined ? "RMSE" : m.metrics.val_acc !== undefined ? "Acc" : "val_loss";
    return `${key} ${Number(v).toFixed(3)}`;
  }

  return (
    <div className="flex flex-col gap-2">
      <select
        value={selectedId}
        onChange={(e) => {
          const id = e.target.value;
          onChange(id ? { __model_id__: id } : null);
        }}
        disabled={loading}
        className="bg-canvas border border-border rounded-lg px-3 py-2 text-sm
          text-slate-200 focus:outline-none focus:border-indigo-500/60
          transition-colors w-full cursor-pointer disabled:opacity-50"
      >
        <option value="" className="bg-surface2">
          {loading ? "Loading…" : models.length === 0 ? "No saved models yet" : "Select a model…"}
        </option>
        {models.map((m) => {
          const metric = metricLine(m);
          return (
            <option key={m.id} value={m.id} className="bg-surface2">
              {m.name}{metric ? ` · ${metric}` : ""}
            </option>
          );
        })}
      </select>

      {selected && (
        <div className="flex items-start gap-2 px-2.5 py-2 rounded-lg bg-indigo-950/30 border border-indigo-800/30">
          <BrainCircuit size={11} className="text-indigo-400 shrink-0 mt-0.5" />
          <div className="flex flex-col gap-0.5 min-w-0">
            <span className="text-[11px] text-indigo-300 font-semibold truncate">{selected.name}</span>
            <div className="flex gap-2 flex-wrap">
              {selected.task && (
                <span className="text-[10px] text-slate-500">{selected.task.replace(/_/g, " ")}</span>
              )}
              {selected.embedding_model && (
                <span className="text-[10px] text-slate-500">ESM-2 {selected.embedding_model}</span>
              )}
              {selected.num_sequences != null && (
                <span className="text-[10px] text-slate-500">{selected.num_sequences} seqs</span>
              )}
              {metricLine(selected) && (
                <span className="text-[10px] text-emerald-500">{metricLine(selected)}</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Output viewer modal ────────────────────────────────────────────────────
function OutputModal({ name, type, value, onClose }: {
  name: string; type: string; value: unknown; onClose: () => void;
}) {
  const isArtifact = value === ARTIFACT_SENTINEL;
  const isPdb = type === "pdb";
  const isFasta = type === "fasta";
  const text = (isPdb || isFasta) ? String(value ?? "") : JSON.stringify(value, null, 2);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-end p-4 pointer-events-none">
      <div
        className="w-96 max-h-[70vh] flex flex-col rounded-xl border border-border shadow-2xl pointer-events-auto"
        style={{ background: "#0e1425" }}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <div>
            <div className="text-xs font-bold text-white">{name}</div>
            <div className="text-[11px] text-slate-500 font-mono">{type}</div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-white p-1 rounded">
            <X size={14} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          {isArtifact ? (
            <div className="text-slate-400 text-xs leading-relaxed">
              Large artifact — use <span className="text-indigo-400 font-semibold">View Analysis</span> in the Run panel to view the structure.
            </div>
          ) : value === null || value === undefined ? (
            <div className="text-slate-500 text-xs italic">No output yet</div>
          ) : (
            <pre className="text-xs font-mono text-slate-300 whitespace-pre-wrap break-all leading-relaxed">
              {text}
            </pre>
          )}
        </div>
        {!isArtifact && (isPdb || isFasta) && Boolean(value) && (
          <div className="px-4 py-2 border-t border-border shrink-0">
            <button
              onClick={() => {
                const blob = new Blob([String(value)], { type: "text/plain" });
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = `${name}.${type}`;
                a.click();
              }}
              className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
            >
              Download .{type}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Developability check configurator ────────────────────────────────────────

const DEV_CHECKS: { name: string; category: string; defaultMode: "hard" | "warn" | "off" }[] = [
  { name: "N-glycosylation",  category: "PTM",          defaultMode: "hard" },
  { name: "Deamidation",      category: "PTM",          defaultMode: "warn" },
  { name: "Isomerization",    category: "PTM",          defaultMode: "warn" },
  { name: "Oxidation-Trp",    category: "PTM",          defaultMode: "warn" },
  { name: "Oxidation-Met",    category: "PTM",          defaultMode: "warn" },
  { name: "DP-cleavage",      category: "PTM",          defaultMode: "warn" },
  { name: "Aromatic-overload",category: "Biophysics",   defaultMode: "warn" },
  { name: "Hydrophobic-patch",category: "Biophysics",   defaultMode: "warn" },
  { name: "pI-extreme",       category: "Biophysics",   defaultMode: "warn" },
  { name: "Net-charge-extreme",category:"Biophysics",   defaultMode: "warn" },
  { name: "Polyspecificity",  category: "Instability",  defaultMode: "warn" },
  { name: "CDR-H3-length",    category: "Instability",  defaultMode: "warn" },
  { name: "Homopolymer",      category: "Instability",  defaultMode: "hard" },
  { name: "Unpaired-Cys",     category: "Instability",  defaultMode: "hard" },
];

const DEV_DEFAULTS: Record<string, "hard" | "warn" | "off"> = Object.fromEntries(
  DEV_CHECKS.map((c) => [c.name, c.defaultMode])
) as Record<string, "hard" | "warn" | "off">;

const MODE_STYLE: Record<string, string> = {
  hard: "bg-red-500/20 border-red-500/40 text-red-300",
  warn: "bg-amber-500/15 border-amber-500/30 text-amber-300",
  off:  "bg-slate-700/30 border-slate-600/30 text-slate-500",
};

const CAT_COLOR: Record<string, string> = {
  PTM:        "text-purple-400",
  Biophysics: "text-sky-400",
  Instability:"text-orange-400",
};

function DevelopabilityChecks({
  config,
  onChange,
}: {
  config: Record<string, string> | undefined;
  onChange: (cfg: Record<string, string>) => void;
}) {
  const merged: Record<string, "hard" | "warn" | "off"> = { ...DEV_DEFAULTS, ...(config ?? {}) } as Record<string, "hard" | "warn" | "off">;

  function cycle(name: string) {
    const cur = merged[name] ?? "warn";
    const next = cur === "hard" ? "warn" : cur === "warn" ? "off" : "hard";
    onChange({ ...merged, [name]: next });
  }

  const categories = ["PTM", "Biophysics", "Instability"];
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Checks</span>
        <div className="flex items-center gap-1.5 ml-auto text-[9px] font-medium">
          {(["hard","warn","off"] as const).map((m) => (
            <span key={m} className={`px-1.5 py-0.5 rounded border ${MODE_STYLE[m]}`}>{m}</span>
          ))}
        </div>
      </div>
      {categories.map((cat) => (
        <div key={cat} className="flex flex-col gap-1">
          <span className={`text-[9px] font-bold uppercase tracking-widest ${CAT_COLOR[cat]}`}>{cat}</span>
          {DEV_CHECKS.filter((c) => c.category === cat).map((check) => {
            const mode = merged[check.name] ?? check.defaultMode;
            return (
              <button
                key={check.name}
                onClick={() => cycle(check.name)}
                className={`flex items-center justify-between px-2.5 py-1.5 rounded-lg border
                  text-left transition-colors hover:opacity-80 ${MODE_STYLE[mode]}`}
              >
                <span className="text-[11px] font-medium">{check.name}</span>
                <span className="text-[9px] font-bold uppercase tracking-wider opacity-70">{mode}</span>
              </button>
            );
          })}
        </div>
      ))}
      <p className="text-[10px] text-slate-600 leading-relaxed">
        Click to cycle: <span className="text-red-400">hard</span> (always reject) →{" "}
        <span className="text-amber-400">warn</span> (counts toward PTM budget) →{" "}
        <span className="text-slate-500">off</span> (skip)
      </p>
    </div>
  );
}

// ── Upstream input utilities ───────────────────────────────────────────────

export interface UpstreamInput {
  nodeId: string;
  toolId: string;
  toolName: string;
  sourceHandle: string | null;
  targetHandle: string | null;
  embeddingDim: number | null;
  category: string;
  params: Record<string, unknown>;
}

const ESM_DIMS: Record<string, number> = { "8M": 320, "35M": 480, "150M": 640, "650M": 1280 };

function getEmbeddingDim(toolId: string, params: Record<string, unknown>): number | null {
  if (toolId === "esm_embedding") return ESM_DIMS[String(params.model_size ?? "650M")] ?? null;
  if (toolId === "abmap") return 512;
  if (toolId === "cheap_embedding") return Number(params.dim ?? 64);
  return null;
}

// ── ParamPanel ─────────────────────────────────────────────────────────────
export interface DNNContext {
  inputs: UpstreamInput[];
}

interface ParamPanelProps {
  onOpenDNNDesigner?: (nodeId: string, spec: ArchitectureSpec | null, context: DNNContext) => void;
  onOpenRLDesigner?: (nodeId: string, spec: RLSpec | null) => void;
}

// Params on the dataset tool that are rendered inside DatasetPicker
const DATASET_MANAGED_PARAMS = new Set(["dataset_id", "vh_column", "vl_column", "label_column"]);

export function ParamPanel({ onOpenDNNDesigner, onOpenRLDesigner }: ParamPanelProps = {}) {
  const { nodes, edges, selectedNodeId, selectNode, updateNodeParams, runNodeOutputs } = useCanvasStore();
  const [openOutput, setOpenOutput] = useState<{ name: string; type: string; value: unknown } | null>(null);

  const node = nodes.find((n) => n.id === selectedNodeId);
  if (!node) return null;

  const data = node.data as NodeData;

  if (data.tool.id === "compute") {
    return <ComputePanel />;
  }

  if (data.tool.id === "loop_end") {
    return <LoopEndPanel />;
  }

  const { tool, params } = data;
  const accentColor = CATEGORY_COLOR[tool.category] ?? "#94a3b8";
  const nodeOutputs = runNodeOutputs[node.id] ?? {};

  function handleChange(name: string, value: unknown) {
    updateNodeParams(node!.id, { ...params, [name]: value });
  }

  // ── Find ALL upstream nodes connected to this DNN node ───────────────────
  const upstreamInputs: UpstreamInput[] = (() => {
    if (tool.id !== "custom_dnn") return [];
    const inEdges = edges?.filter((e) => e.target === node.id) ?? [];
    return inEdges.map((e) => {
      const srcNode = nodes.find((n) => n.id === e.source);
      if (!srcNode) return null;
      const srcData = srcNode.data as NodeData;
      const srcParams = srcData.params as Record<string, unknown>;
      return {
        nodeId: srcNode.id,
        toolId: srcData.tool.id,
        toolName: srcData.tool.name,
        sourceHandle: e.sourceHandle ?? null,
        targetHandle: e.targetHandle ?? null,
        embeddingDim: getEmbeddingDim(srcData.tool.id, srcParams),
        category: srcData.tool.category,
        params: srcParams,
      } satisfies UpstreamInput;
    }).filter(Boolean) as UpstreamInput[];
  })();

  return (
    <>
      <div className="w-72 shrink-0 border-l border-border bg-surface flex flex-col overflow-hidden">
        {/* Header */}
        <div
          className="flex items-center justify-between px-4 py-3 border-b border-border"
          style={{ borderTopColor: accentColor, borderTopWidth: 2 }}
        >
          <div>
            <div className="text-sm font-bold text-white">{tool.name}</div>
            <div className="text-xs text-slate-500 mt-0.5">{tool.category.replace(/_/g, " ")}</div>
          </div>
          <button
            onClick={() => selectNode(null)}
            className="text-slate-500 hover:text-white transition-colors p-1 rounded hover:bg-white/5"
          >
            <X size={15} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
          {tool.wip && (
            <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-fuchsia-950/60 border border-fuchsia-800/50">
              <span className="text-fuchsia-400 text-[10px] font-bold uppercase tracking-wider mt-0.5">WIP</span>
              <p className="text-[11px] text-fuchsia-300 leading-relaxed">
                This tool is experimental and not yet runnable. Drop it on the canvas to plan your pipeline — it will fail with a clear message if executed.
              </p>
            </div>
          )}

          {/* ── DNN: upstream inputs card + Architecture button ──────────── */}
          {tool.id === "custom_dnn" && onOpenDNNDesigner && (
            <div className="flex flex-col gap-2">
              {/* All upstream connections */}
              {upstreamInputs.length > 0 && (
                <div className="flex flex-col gap-1 px-2.5 py-2 rounded-lg bg-slate-800/40 border border-slate-700/40">
                  <span className="text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-0.5">Inputs</span>
                  {upstreamInputs.map((u) => {
                    const isEmbed = u.category === "sequence_embedding";
                    const isDataset = u.toolId === "dataset";
                    const port = u.targetHandle?.split(".").pop() ?? u.targetHandle ?? "?";
                    return (
                      <div key={u.nodeId + (u.targetHandle ?? "")} className="flex items-start gap-1.5 text-[10px]">
                        {isEmbed ? (
                          <Zap size={10} className="text-pink-400 shrink-0 mt-0.5" />
                        ) : isDataset ? (
                          <Database size={10} className="text-amber-400 shrink-0 mt-0.5" />
                        ) : (
                          <span className="w-2 h-2 rounded-full bg-slate-500 shrink-0 mt-0.5" />
                        )}
                        <div className="flex flex-col gap-0 min-w-0">
                          <span className="text-slate-300 font-semibold truncate">{u.toolName}</span>
                          <span className="text-slate-500">
                            → <span className="text-slate-400">{port}</span>
                            {u.embeddingDim != null && (
                              <> · <span className="text-pink-400 font-mono">{u.embeddingDim}d</span></>
                            )}
                            {isDataset && !!u.params.label_column && (
                              <> · label: <span className="text-amber-400">{String(u.params.label_column)}</span></>
                            )}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              <button
                onClick={() => {
                  const raw = params.architecture_spec;
                  const spec: ArchitectureSpec | null =
                    raw && typeof raw === "object" && Array.isArray((raw as ArchitectureSpec).nodes)
                      ? (raw as ArchitectureSpec)
                      : null;
                  onOpenDNNDesigner(node!.id, spec, { inputs: upstreamInputs });
                }}
                className="flex items-center justify-center gap-2 w-full px-3 py-2 rounded-lg
                  bg-fuchsia-500/15 border border-fuchsia-500/40 text-fuchsia-300 text-xs
                  font-semibold hover:bg-fuchsia-500/25 transition-colors"
              >
                <Layers size={13} />
                Design Architecture →
              </button>

              {Boolean(params.architecture_spec) && typeof params.architecture_spec === "object" && Array.isArray((params.architecture_spec as ArchitectureSpec).nodes) && (() => {
                const spec = params.architecture_spec as ArchitectureSpec;
                const layerCount = spec.nodes?.length ?? 0;
                const types = [...new Set(spec.nodes?.map((n) => n.type) ?? [])];
                const hasTransformer = types.some((t) => t.includes("Transformer") || t.includes("Attention"));
                const archLabel = hasTransformer ? "Transformer" : types.some((t) => t === "LSTM" || t === "GRU") ? "Recurrent" : "MLP";
                return (
                  <div className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg bg-fuchsia-950/30 border border-fuchsia-900/40">
                    <Layers size={11} className="text-fuchsia-400 shrink-0" />
                    <span className="text-[10px] text-fuchsia-300">
                      {archLabel} · {layerCount} layer{layerCount !== 1 ? "s" : ""}
                    </span>
                  </div>
                );
              })()}
            </div>
          )}

          {tool.description && (
            <p className="text-xs text-slate-500 leading-relaxed">{tool.description}</p>
          )}

          {/* ── Dataset node: full column mapping block ─────────────────── */}
          {tool.id === "dataset" && (
            <DatasetPicker
              datasetId={String(params.dataset_id ?? "")}
              params={params as Record<string, unknown>}
              onParamChange={handleChange}
            />
          )}

          {/* ── Developability filter: check list ───────────────────────── */}
          {tool.id === "developability_filter" && (
            <DevelopabilityChecks
              config={params.check_config as Record<string, string> | undefined}
              onChange={(cfg) => handleChange("check_config", cfg)}
            />
          )}

          {/* ── RL Designer: Configure RL Policy button ─────────────────── */}
          {tool.id === "rl_designer" && onOpenRLDesigner && (
            <div className="flex flex-col gap-2">
              <button
                onClick={() => {
                  const raw = params.rl_spec;
                  const spec: RLSpec | null =
                    raw && typeof raw === "object" && (raw as RLSpec).version === "1.0"
                      ? (raw as RLSpec)
                      : null;
                  onOpenRLDesigner(node!.id, spec);
                }}
                className="flex items-center justify-center gap-2 w-full px-3 py-2 rounded-lg
                  bg-violet-500/15 border border-violet-500/40 text-violet-300 text-xs
                  font-semibold hover:bg-violet-500/25 transition-colors"
              >
                <FlaskConical size={13} />
                Configure RL Policy →
              </button>
              {Boolean(params.rl_spec) && typeof params.rl_spec === "object" && (() => {
                const spec = params.rl_spec as RLSpec;
                const actionCount = (spec.action?.cdrs?.length ?? 0) *
                                    (spec.action?.strategies?.length ?? 0) *
                                    (spec.action?.n_mutations_choices?.length ?? 0);
                return (
                  <div className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg bg-violet-950/30 border border-violet-900/40">
                    <FlaskConical size={11} className="text-violet-400 shrink-0" />
                    <span className="text-[10px] text-violet-300">
                      {spec.algorithm?.kind?.toUpperCase() ?? "DQN"} · |A|={actionCount} ·{" "}
                      ε {spec.algorithm?.epsilon_start}→{spec.algorithm?.epsilon_end}
                    </span>
                  </div>
                );
              })()}
            </div>
          )}

          {/* ── Generic parameter loop ──────────────────────────────────── */}
          {tool.inputs.filter((p) => {
            if (p.panel_hidden) return false;
            if (p.type === "pdb") return false;
            if (tool.id === "custom_dnn" && p.name === "architecture_spec") return false;
            if (tool.id === "rl_designer" && p.name === "rl_spec") return false;
            if (tool.id === "dataset" && DATASET_MANAGED_PARAMS.has(p.name)) return false;
            if (tool.id === "developability_filter" && p.name === "check_config") return false;
            return true;
          }).map((port) => {
            const inputType = TYPE_INPUT[port.type] ?? "text";
            const value = params[port.name] ?? port.default ?? "";
            const isTextarea = port.type === "fasta" || port.type === "pdb";

            return (
              <div key={port.name} className="flex flex-col gap-1.5">
                <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-300">
                  <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: accentColor }} />
                  {port.name}
                  {port.required && <span className="text-red-400">*</span>}
                  <span className="ml-auto text-slate-600 font-normal">{port.type}</span>
                </label>

                {port.description && (
                  <p className="text-[11px] text-slate-600 pl-3 max-h-16 overflow-y-auto leading-relaxed scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent">
                    {port.description}
                  </p>
                )}

                {port.type === "model" ? (
                  <ModelPicker
                    value={value}
                    onChange={(artifact) => handleChange(port.name, artifact)}
                  />
                ) : port.options ? (
                  <select
                    value={String(value)}
                    onChange={(e) => handleChange(port.name, e.target.value)}
                    className="bg-canvas border border-border rounded-lg px-3 py-2 text-sm
                      text-slate-200 focus:outline-none focus:border-indigo-500/60
                      transition-colors w-full cursor-pointer"
                  >
                    {port.options.map((opt) => (
                      <option key={opt} value={opt} className="bg-surface2">{opt}</option>
                    ))}
                  </select>
                ) : inputType === "checkbox" ? (
                  <input
                    type="checkbox"
                    checked={Boolean(value)}
                    onChange={(e) => handleChange(port.name, e.target.checked)}
                    className="ml-3 w-4 h-4 accent-indigo-500"
                  />
                ) : isTextarea ? (
                  <textarea
                    value={String(value)}
                    onChange={(e) => handleChange(port.name, e.target.value)}
                    rows={4}
                    placeholder={`${port.type}…`}
                    className="bg-canvas border border-border rounded-lg px-3 py-2 text-xs
                      font-mono text-slate-200 placeholder-slate-600 resize-none
                      focus:outline-none focus:border-indigo-500/60 transition-colors w-full"
                  />
                ) : (
                  <input
                    type={inputType}
                    value={String(value)}
                    step={inputType === "number" ? "any" : undefined}
                    onChange={(e) =>
                      handleChange(
                        port.name,
                        inputType === "number" ? Number(e.target.value) : e.target.value
                      )
                    }
                    placeholder={port.required ? `${port.type} (required)` : `${port.type} (optional)`}
                    className="bg-canvas border border-border rounded-lg px-3 py-2 text-sm
                      text-slate-200 placeholder-slate-600 focus:outline-none
                      focus:border-indigo-500/60 transition-colors w-full"
                  />
                )}
              </div>
            );
          })}

          {/* ── Outputs ─────────────────────────────────────────────────── */}
          {tool.outputs.length > 0 && (
            <div className="border-t border-border pt-3 mt-1">
              <div className="text-[11px] font-bold uppercase tracking-widest text-slate-600 mb-2">
                Outputs
              </div>
              {tool.outputs.map((port) => {
                const value = nodeOutputs[port.name];
                const hasValue = value !== undefined && value !== null;
                return (
                  <div key={port.name} className="py-1.5">
                    <div className="flex items-center justify-between group">
                      <button
                        onClick={() => setOpenOutput({ name: port.name, type: port.type, value })}
                        className={`flex items-center gap-1.5 text-xs transition-colors ${
                          hasValue
                            ? "text-indigo-400 hover:text-indigo-300 cursor-pointer"
                            : "text-slate-500 cursor-default"
                        }`}
                        disabled={!hasValue}
                        title={hasValue ? "Click to view output" : "No output yet"}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full ${hasValue ? "bg-indigo-400" : "bg-slate-600"}`} />
                        {port.name}
                        {hasValue && <Eye size={10} className="opacity-0 group-hover:opacity-100 transition-opacity" />}
                      </button>
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] text-slate-600 font-mono">{port.type}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {openOutput && (
        <OutputModal
          name={openOutput.name}
          type={openOutput.type}
          value={openOutput.value}
          onClose={() => setOpenOutput(null)}
        />
      )}
    </>
  );
}
