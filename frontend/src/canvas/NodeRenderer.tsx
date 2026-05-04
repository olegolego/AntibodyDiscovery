import { useRef, useState } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { BookOpen, Code2 } from "lucide-react";
import { useCanvasStore, type NodeData } from "./store";
import { SequencePickerModal } from "@/sequences/SequencePickerModal";
import type { DatasetEntry } from "@/api/datasets";

const CATEGORY_STYLE: Record<string, { border: string; label: string; glow: string }> = {
  input:                { border: "#fbbf24", label: "text-amber-300",   glow: "rgba(251,191,36,0.25)"  },
  structure_prediction: { border: "#38bdf8", label: "text-sky-300",     glow: "rgba(56,189,248,0.2)"   },
  structure_design:     { border: "#a78bfa", label: "text-violet-300",  glow: "rgba(167,139,250,0.2)"  },
  sequence_design:      { border: "#34d399", label: "text-emerald-300", glow: "rgba(52,211,153,0.2)"   },
  sequence_embedding:   { border: "#fb7185", label: "text-rose-300",    glow: "rgba(251,113,133,0.2)"  },
  docking:              { border: "#f97316", label: "text-orange-300",  glow: "rgba(249,115,22,0.2)"   },
  toolbox:              { border: "#e879f9", label: "text-fuchsia-300", glow: "rgba(232,121,249,0.2)"  },
  compute:              { border: "#818cf8", label: "text-indigo-300",  glow: "rgba(129,140,248,0.2)"  },
  debug:                { border: "#94a3b8", label: "text-slate-400",   glow: "rgba(148,163,184,0.15)" },
};

const STATUS_RING: Record<string, string> = {
  queued:    "ring-2 ring-yellow-400/70",
  running:   "ring-2 ring-blue-400/80 animate-pulse",
  succeeded: "ring-2 ring-emerald-400/80",
  failed:    "ring-2 ring-red-500/80",
  skipped:   "ring-1 ring-slate-500/60",
};

const STATUS_DOT: Record<string, string> = {
  queued:    "bg-yellow-400",
  running:   "bg-blue-400 animate-pulse",
  succeeded: "bg-emerald-400",
  failed:    "bg-red-500",
};

// ── Generic tool node ────────────────────────────────────────────────────────

export function ToolNode({ id, data, selected }: NodeProps<NodeData>) {
  const { tool } = data;
  const runStatus = useCanvasStore((s) => s.runNodeStatuses[id]);
  const style = CATEGORY_STYLE[tool.category] ?? CATEGORY_STYLE.debug;

  return (
    <div
      style={{
        borderColor: style.border,
        boxShadow: selected
          ? `0 0 0 2px ${style.border}99, 0 4px 28px ${style.glow}`
          : `0 4px 20px ${style.glow}`,
      }}
      className={`bg-surface2 border-2 rounded-xl px-3.5 py-2.5 min-w-[172px] transition-shadow
        ${runStatus ? STATUS_RING[runStatus] ?? "" : ""}`}
    >
      {tool.inputs.length > 0 && (
        <Handle
          type="target"
          position={Position.Left}
          id="in"
          style={{ top: "50%", background: style.border }}
          title={tool.inputs.map((p) => `${p.name}: ${p.type}`).join(", ")}
          className="!w-3 !h-3 !border-2 !border-surface"
        />
      )}

      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className={`text-[10px] font-semibold uppercase tracking-wider mb-0.5 ${style.label}`}>
            {tool.category.replace(/_/g, " ")}
          </div>
          <div className="text-sm font-bold text-white leading-tight truncate">{tool.name}</div>
        </div>
        {runStatus && STATUS_DOT[runStatus] && (
          <span className={`shrink-0 w-2.5 h-2.5 rounded-full ${STATUS_DOT[runStatus]}`} />
        )}
      </div>

      {tool.outputs.length > 0 && (
        <Handle
          type="source"
          position={Position.Right}
          id="out"
          style={{ top: "50%", background: "#818cf8" }}
          title={tool.outputs.map((p) => `${p.name}: ${p.type}`).join(", ")}
          className="!w-3 !h-3 !border-2 !border-surface"
        />
      )}
    </div>
  );
}

// ── Sequence input node ──────────────────────────────────────────────────────

export function SequenceInputNode({ id, data, selected }: NodeProps<NodeData>) {
  const runStatus = useCanvasStore((s) => s.runNodeStatuses[id]);
  const updateNodeParams = useCanvasStore((s) => s.updateNodeParams);

  const heavy = String(data.params.heavy_chain ?? "");
  const light = String(data.params.light_chain ?? "");

  function set(field: string, value: string) {
    updateNodeParams(id, { ...data.params, [field]: value });
  }

  return (
    <div
      style={{
        borderColor: "#fbbf24",
        boxShadow: selected
          ? "0 0 0 2px #fbbf2499, 0 4px 28px rgba(251,191,36,0.3)"
          : "0 4px 20px rgba(251,191,36,0.2)",
      }}
      className={`bg-surface2 border-2 rounded-xl px-3.5 py-2.5 w-72
        ${runStatus ? STATUS_RING[runStatus] ?? "" : ""}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-2.5">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-amber-300">Input</div>
          <div className="text-sm font-bold text-white">Sequence Input</div>
        </div>
        {runStatus && STATUS_DOT[runStatus] && (
          <span className={`w-2.5 h-2.5 rounded-full ${STATUS_DOT[runStatus]}`} />
        )}
      </div>

      {/* VH field */}
      <div className="flex flex-col gap-1 mb-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-bold text-amber-300 uppercase tracking-widest">VH · Heavy Chain</span>
          <span className="text-[10px] text-slate-600">{heavy.length} AA</span>
        </div>
        <textarea
          value={heavy}
          onChange={(e) => set("heavy_chain", e.target.value)}
          placeholder="EVQLVESGG… (required)"
          rows={3}
          className="nodrag w-full bg-canvas border border-border rounded-lg px-2.5 py-2 text-xs
            font-mono text-slate-200 placeholder-slate-600 resize-none focus:outline-none
            focus:border-amber-400/60 transition-colors"
        />
      </div>

      {/* VL field */}
      <div className="flex flex-col gap-1 mb-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-bold text-amber-300/60 uppercase tracking-widest">VL · Light Chain</span>
          <span className="text-[10px] text-slate-600">{light.length} AA</span>
        </div>
        <textarea
          value={light}
          onChange={(e) => set("light_chain", e.target.value)}
          placeholder="DIQMTQSPS… (optional — omit for nanobody)"
          rows={3}
          className="nodrag w-full bg-canvas border border-border rounded-lg px-2.5 py-2 text-xs
            font-mono text-slate-200 placeholder-slate-600 resize-none focus:outline-none
            focus:border-amber-400/40 transition-colors"
        />
      </div>

      <Handle
        type="source"
        position={Position.Right}
        id="out"
        style={{ top: "50%", background: "#fbbf24" }}
        title="heavy_chain, light_chain"
        className="!w-3 !h-3 !border-2 !border-surface"
      />
    </div>
  );
}

// ── Sequence DB node — picks from datasets ──────────────────────────────────

export function SequenceDbNode({ id, data, selected }: NodeProps<NodeData>) {
  const runStatus = useCanvasStore((s) => s.runNodeStatuses[id]);
  const updateNodeParams = useCanvasStore((s) => s.updateNodeParams);
  const [pickerOpen, setPickerOpen] = useState(false);

  const heavy = String(data.params.heavy_chain ?? "");
  const light = String(data.params.light_chain ?? "");

  function onSelect(entry: DatasetEntry) {
    updateNodeParams(id, { ...data.params, heavy_chain: entry.heavy_chain ?? "", light_chain: entry.light_chain ?? "" });
    setPickerOpen(false);
  }

  function preview(seq: string) {
    if (!seq) return null;
    return seq.length <= 16 ? seq : `${seq.slice(0, 8)}…${seq.slice(-6)}`;
  }

  return (
    <>
      <div
        style={{
          borderColor: "#fbbf24",
          boxShadow: selected
            ? "0 0 0 2px #fbbf2499, 0 4px 28px rgba(251,191,36,0.3)"
            : "0 4px 20px rgba(251,191,36,0.2)",
        }}
        className={`bg-surface2 border-2 rounded-xl px-3.5 py-2.5 w-72
          ${runStatus ? STATUS_RING[runStatus] ?? "" : ""}`}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-2.5">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-amber-300">Input · Datasets</div>
            <div className="text-sm font-bold text-white">Sequence Dataset</div>
          </div>
          {runStatus && STATUS_DOT[runStatus] && (
            <span className={`w-2.5 h-2.5 rounded-full ${STATUS_DOT[runStatus]}`} />
          )}
        </div>

        {/* VH display */}
        <div className="flex flex-col gap-1 mb-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold text-amber-300 uppercase tracking-widest">VH · Heavy Chain</span>
            <span className="text-[10px] text-slate-600">{heavy.length > 0 ? `${heavy.length} AA` : "—"}</span>
          </div>
          <div className="w-full bg-canvas border border-border rounded-lg px-2.5 py-2 text-xs font-mono
            text-slate-400 min-h-[32px] truncate">
            {preview(heavy) ?? <span className="text-slate-600">No sequence selected</span>}
          </div>
        </div>

        {/* VL display */}
        <div className="flex flex-col gap-1 mb-3">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold text-amber-300/60 uppercase tracking-widest">VL · Light Chain</span>
            <span className="text-[10px] text-slate-600">{light.length > 0 ? `${light.length} AA` : "—"}</span>
          </div>
          <div className="w-full bg-canvas border border-border rounded-lg px-2.5 py-2 text-xs font-mono
            text-slate-400 min-h-[32px] truncate">
            {preview(light) ?? <span className="text-slate-600">—</span>}
          </div>
        </div>

        {/* Pick button */}
        <button
          onClick={() => setPickerOpen(true)}
          className="nodrag w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg
            text-xs font-semibold border border-amber-500/40 text-amber-300
            hover:bg-amber-500/10 hover:border-amber-400/60 transition-colors"
        >
          <BookOpen size={11} />
          Pick from Datasets
        </button>

        <Handle
          type="source"
          position={Position.Right}
          id="out"
          style={{ top: "50%", background: "#fbbf24" }}
          title="heavy_chain, light_chain"
          className="!w-3 !h-3 !border-2 !border-surface"
        />
      </div>

      {pickerOpen && (
        <SequencePickerModal onSelect={onSelect} onClose={() => setPickerOpen(false)} />
      )}
    </>
  );
}

// ── ImmuneBuilder node — 4 ranked structure output handles ──────────────────

const IB_HANDLES = [
  { id: "structure_1", top: "18%", label: "1" },
  { id: "structure_2", top: "39%", label: "2" },
  { id: "structure_3", top: "61%", label: "3" },
  { id: "structure_4", top: "82%", label: "4" },
] as const;

export function ImmuneBuilderNode({ id, selected }: NodeProps<NodeData>) {
  const runStatus   = useCanvasStore((s) => s.runNodeStatuses[id]);
  const nodeOutputs = useCanvasStore((s) => s.runNodeOutputs[id]);
  const style       = CATEGORY_STYLE["structure_prediction"];

  return (
    <div
      style={{
        borderColor: style.border,
        boxShadow: selected
          ? `0 0 0 2px ${style.border}99, 0 4px 28px ${style.glow}`
          : `0 4px 20px ${style.glow}`,
      }}
      className={`relative bg-surface2 border-2 rounded-xl px-3.5 py-2.5 min-w-[188px] min-h-[130px]
        transition-shadow ${runStatus ? STATUS_RING[runStatus] ?? "" : ""}`}
    >
      {/* Single input handle */}
      <Handle
        type="target"
        position={Position.Left}
        id="in"
        style={{ top: "50%", background: style.border }}
        title="heavy_chain, light_chain"
        className="!w-3 !h-3 !border-2 !border-surface"
      />

      {/* Header */}
      <div className="flex items-center justify-between gap-2 pr-6">
        <div className="min-w-0">
          <div className={`text-[10px] font-semibold uppercase tracking-wider mb-0.5 ${style.label}`}>
            Structure Prediction
          </div>
          <div className="text-sm font-bold text-white leading-tight">ImmuneBuilder</div>
        </div>
        {runStatus && STATUS_DOT[runStatus] && (
          <span className={`shrink-0 w-2.5 h-2.5 rounded-full ${STATUS_DOT[runStatus]}`} />
        )}
      </div>

      {/* Rank labels — inside right edge */}
      <div className="absolute right-5 top-0 bottom-0 flex flex-col justify-around py-3 pointer-events-none">
        {IB_HANDLES.map((h) => (
          <span key={h.id} className="text-[9px] font-mono text-slate-500 text-right leading-none">
            {h.label}
          </span>
        ))}
      </div>

      {/* 4 named output handles */}
      {IB_HANDLES.map((h) => {
        const ready = nodeOutputs?.[h.id] != null;
        return (
          <Handle
            key={h.id}
            type="source"
            position={Position.Right}
            id={h.id}
            style={{ top: h.top, background: ready ? "#34d399" : "#818cf8" }}
            title={`Model ${h.label}${ready ? " — ready" : ""}`}
            className="!w-3 !h-3 !border-2 !border-surface"
          />
        );
      })}
    </div>
  );
}

// ── MEGADOCK node — named ligand/receptor inputs + N ranked complex outputs ──

export function MegaDockNode({ id, data, selected }: NodeProps<NodeData>) {
  const runStatus   = useCanvasStore((s) => s.runNodeStatuses[id]);
  const nodeOutputs = useCanvasStore((s) => s.runNodeOutputs[id]);
  const style       = CATEGORY_STYLE["docking"];

  const numPred = Math.max(1, Math.min(20, Number(data.params.num_predictions ?? 5)));
  const handles = Array.from({ length: numPred }, (_, i) => ({
    id:    `complex_${i + 1}`,
    label: String(i + 1),
    top:   `${10 + ((i + 0.5) / numPred) * 80}%`,
  }));
  const minH = Math.max(120, numPred * 26 + 48);

  return (
    <div
      style={{
        borderColor: style.border,
        minHeight:   minH,
        boxShadow: selected
          ? `0 0 0 2px ${style.border}99, 0 4px 28px ${style.glow}`
          : `0 4px 20px ${style.glow}`,
      }}
      className={`relative bg-surface2 border-2 rounded-xl px-3.5 py-2.5 min-w-[188px]
        transition-shadow ${runStatus ? STATUS_RING[runStatus] ?? "" : ""}`}
    >
      {/* Input handles */}
      <Handle
        type="target"
        position={Position.Left}
        id="ligand"
        style={{ top: "33%", background: style.border }}
        title="ligand: pdb — wire from ImmuneBuilder, ESMFold, etc."
        className="!w-3 !h-3 !border-2 !border-surface"
      />
      <Handle
        type="target"
        position={Position.Left}
        id="receptor"
        style={{ top: "67%", background: "#fbbf24" }}
        title="receptor: pdb — wire from Target Input"
        className="!w-3 !h-3 !border-2 !border-surface"
      />

      {/* Input labels */}
      <div className="absolute left-4 top-0 bottom-0 flex flex-col justify-around py-3 pointer-events-none pl-1">
        <span className="text-[9px] font-bold text-orange-300 leading-none">Lig</span>
        <span className="text-[9px] font-bold text-amber-300 leading-none">Rec</span>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between gap-2 pl-5 pr-6">
        <div className="min-w-0">
          <div className={`text-[10px] font-semibold uppercase tracking-wider mb-0.5 ${style.label}`}>
            Docking
          </div>
          <div className="text-sm font-bold text-white leading-tight">MEGADOCK</div>
          <div className="text-[10px] text-slate-500 mt-0.5">{numPred} poses · wire any to MD</div>
        </div>
        {runStatus && STATUS_DOT[runStatus] && (
          <span className={`shrink-0 w-2.5 h-2.5 rounded-full ${STATUS_DOT[runStatus]}`} />
        )}
      </div>

      {/* Output labels — inside right edge */}
      <div className="absolute right-5 top-0 bottom-0 pointer-events-none">
        {handles.map((h) => (
          <span
            key={h.id}
            style={{ top: h.top, transform: "translateY(-50%)" }}
            className="absolute text-[9px] font-mono text-slate-500 text-right leading-none right-0"
          >
            {h.label}
          </span>
        ))}
      </div>

      {/* N ranked output handles */}
      {handles.map((h) => {
        const ready = nodeOutputs?.[h.id] != null;
        return (
          <Handle
            key={h.id}
            type="source"
            position={Position.Right}
            id={h.id}
            style={{ top: h.top, background: ready ? "#34d399" : "#818cf8" }}
            title={`Pose ${h.label} — wire to GROMACS MD${ready ? " — ready" : ""}`}
            className="!w-3 !h-3 !border-2 !border-surface"
          />
        );
      })}
    </div>
  );
}

// ── HADDOCK3 node — named antibody / antigen input handles ───────────────────

export function HADDOCK3Node({ id, selected }: NodeProps<NodeData>) {
  const runStatus = useCanvasStore((s) => s.runNodeStatuses[id]);
  const style     = CATEGORY_STYLE["docking"];

  return (
    <div
      style={{
        borderColor: style.border,
        boxShadow: selected
          ? `0 0 0 2px ${style.border}99, 0 4px 28px ${style.glow}`
          : `0 4px 20px ${style.glow}`,
      }}
      className={`relative bg-surface2 border-2 rounded-xl px-3.5 py-2.5 min-w-[188px] min-h-[110px]
        transition-shadow ${runStatus ? STATUS_RING[runStatus] ?? "" : ""}`}
    >
      {/* Input handles */}
      <Handle
        type="target"
        position={Position.Left}
        id="antibody"
        style={{ top: "33%", background: style.border }}
        title="antibody: pdb — wire from ImmuneBuilder"
        className="!w-3 !h-3 !border-2 !border-surface"
      />
      <Handle
        type="target"
        position={Position.Left}
        id="antigen"
        style={{ top: "67%", background: "#fbbf24" }}
        title="antigen: pdb — wire from Target Input"
        className="!w-3 !h-3 !border-2 !border-surface"
      />

      {/* Input labels — inside left edge */}
      <div className="absolute left-4 top-0 bottom-0 flex flex-col justify-around py-3 pointer-events-none pl-1">
        <span className="text-[9px] font-bold text-orange-300 leading-none">Ab</span>
        <span className="text-[9px] font-bold text-amber-300 leading-none">Ag</span>
      </div>

      {/* Header — offset right to make room for input labels */}
      <div className="flex items-center justify-between gap-2 pl-5">
        <div className="min-w-0">
          <div className={`text-[10px] font-semibold uppercase tracking-wider mb-0.5 ${style.label}`}>
            Docking
          </div>
          <div className="text-sm font-bold text-white leading-tight">HADDOCK3</div>
        </div>
        {runStatus && STATUS_DOT[runStatus] && (
          <span className={`shrink-0 w-2.5 h-2.5 rounded-full ${STATUS_DOT[runStatus]}`} />
        )}
      </div>

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Right}
        id="best_complex"
        style={{ top: "50%", background: "#818cf8" }}
        title="best_complex: pdb"
        className="!w-3 !h-3 !border-2 !border-surface"
      />
    </div>
  );
}

// ── EquiDock node — named ligand / receptor input handles ────────────────────

export function EquiDockNode({ id, selected }: NodeProps<NodeData>) {
  const runStatus = useCanvasStore((s) => s.runNodeStatuses[id]);
  const style     = CATEGORY_STYLE["docking"];

  return (
    <div
      style={{
        borderColor: style.border,
        boxShadow: selected
          ? `0 0 0 2px ${style.border}99, 0 4px 28px ${style.glow}`
          : `0 4px 20px ${style.glow}`,
      }}
      className={`relative bg-surface2 border-2 rounded-xl px-3.5 py-2.5 min-w-[188px] min-h-[110px]
        transition-shadow ${runStatus ? STATUS_RING[runStatus] ?? "" : ""}`}
    >
      {/* Input handles */}
      <Handle
        type="target"
        position={Position.Left}
        id="ligand"
        style={{ top: "33%", background: style.border }}
        title="ligand: pdb — wire from ImmuneBuilder, ESMFold, etc."
        className="!w-3 !h-3 !border-2 !border-surface"
      />
      <Handle
        type="target"
        position={Position.Left}
        id="receptor"
        style={{ top: "67%", background: "#fbbf24" }}
        title="receptor: pdb — wire from Target Input"
        className="!w-3 !h-3 !border-2 !border-surface"
      />

      {/* Input labels */}
      <div className="absolute left-4 top-0 bottom-0 flex flex-col justify-around py-3 pointer-events-none pl-1">
        <span className="text-[9px] font-bold text-orange-300 leading-none">Lig</span>
        <span className="text-[9px] font-bold text-amber-300 leading-none">Rec</span>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between gap-2 pl-5">
        <div className="min-w-0">
          <div className={`text-[10px] font-semibold uppercase tracking-wider mb-0.5 ${style.label}`}>
            Docking
          </div>
          <div className="text-sm font-bold text-white leading-tight">EquiDock</div>
        </div>
        {runStatus && STATUS_DOT[runStatus] && (
          <span className={`shrink-0 w-2.5 h-2.5 rounded-full ${STATUS_DOT[runStatus]}`} />
        )}
      </div>

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Right}
        id="best_complex"
        style={{ top: "50%", background: "#818cf8" }}
        title="best_complex: pdb"
        className="!w-3 !h-3 !border-2 !border-surface"
      />
    </div>
  );
}

// ── Compute node ─────────────────────────────────────────────────────────────

export function ComputeNode({ id, selected }: NodeProps<NodeData>) {
  const runStatus = useCanvasStore((s) => s.runNodeStatuses[id]);

  return (
    <div
      style={{
        borderColor: "#818cf8",
        boxShadow: selected
          ? "0 0 0 2px #818cf899, 0 4px 28px rgba(129,140,248,0.3)"
          : "0 4px 20px rgba(129,140,248,0.18)",
      }}
      className={`bg-surface2 border-2 rounded-xl px-3.5 py-2.5 min-w-[172px] transition-shadow
        ${runStatus ? STATUS_RING[runStatus] ?? "" : ""}`}
    >
      <Handle
        type="target"
        position={Position.Left}
        id="in"
        style={{ top: "50%", background: "#818cf8" }}
        title="upstream outputs → Python variables"
        className="!w-3 !h-3 !border-2 !border-surface"
      />

      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wider mb-0.5 text-indigo-300">
            Compute
          </div>
          <div className="flex items-center gap-1.5">
            <Code2 size={12} className="text-indigo-400 shrink-0" />
            <div className="text-sm font-bold text-white leading-tight">Python</div>
          </div>
        </div>
        {runStatus && STATUS_DOT[runStatus] && (
          <span className={`shrink-0 w-2.5 h-2.5 rounded-full ${STATUS_DOT[runStatus]}`} />
        )}
      </div>

      <Handle
        type="source"
        position={Position.Right}
        id="out"
        style={{ top: "50%", background: "#c084fc" }}
        title="result: json"
        className="!w-3 !h-3 !border-2 !border-surface"
      />
    </div>
  );
}

// ── Target input node ────────────────────────────────────────────────────────

export function TargetInputNode({ id, data, selected }: NodeProps<NodeData>) {
  const runStatus = useCanvasStore((s) => s.runNodeStatuses[id]);
  const updateNodeParams = useCanvasStore((s) => s.updateNodeParams);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const target = String(data.params.target ?? "");

  function setTarget(value: string) {
    updateNodeParams(id, { ...data.params, target: value });
  }

  function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result;
      if (typeof text === "string") setTarget(text);
    };
    reader.readAsText(file);
    e.target.value = "";
  }

  return (
    <div
      style={{
        borderColor: "#fbbf24",
        boxShadow: selected
          ? "0 0 0 2px #fbbf2499, 0 4px 28px rgba(251,191,36,0.3)"
          : "0 4px 20px rgba(251,191,36,0.2)",
      }}
      className={`bg-surface2 border-2 rounded-xl px-3.5 py-2.5 w-72
        ${runStatus ? STATUS_RING[runStatus] ?? "" : ""}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-2.5">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-amber-300">Input</div>
          <div className="text-sm font-bold text-white">Target Input</div>
        </div>
        {runStatus && STATUS_DOT[runStatus] && (
          <span className={`w-2.5 h-2.5 rounded-full ${STATUS_DOT[runStatus]}`} />
        )}
      </div>

      {/* PDB field */}
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] font-bold text-amber-300 uppercase tracking-widest">Target · PDB Structure</span>
          <span className="text-[10px] text-slate-600">
            {target.length > 0 ? `${target.split("\n").length} lines` : ""}
          </span>
        </div>
        <textarea
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder={"Spike RBD (chain B 319-541) pre-loaded by default.\n\nPaste different PDB text or upload a .pdb file to override."}
          rows={5}
          className="nodrag w-full bg-canvas border border-border rounded-lg px-2.5 py-2 text-xs
            font-mono text-slate-200 placeholder-slate-600 resize-none focus:outline-none
            focus:border-amber-400/60 transition-colors"
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          className="nodrag mt-1 w-full text-[11px] font-medium text-amber-300 border border-amber-500/40
            rounded-lg py-1.5 hover:bg-amber-500/10 transition-colors"
        >
          Upload .pdb file
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdb,.ent"
          className="hidden"
          onChange={handleFileUpload}
        />
      </div>

      <Handle
        type="source"
        position={Position.Right}
        id="out"
        style={{ top: "50%", background: "#fbbf24" }}
        title="target: pdb"
        className="!w-3 !h-3 !border-2 !border-surface"
      />
    </div>
  );
}
