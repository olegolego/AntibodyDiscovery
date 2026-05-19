import { useCallback, useEffect, useMemo, useState } from "react";
import { ReactFlowProvider } from "reactflow";
import { Save, Check, Layers, Activity, Zap, Database } from "lucide-react";
import { LayerPalette } from "./LayerPalette";
import { DNNCanvas } from "./DNNCanvas";
import { LayerParamPanel } from "./LayerParamPanel";
import { CodePreview } from "./CodePreview";
import { useDNNStore } from "./store";
import type { ArchitectureSpec } from "./store";
import { inferShapes, countParams, formatParamCount } from "./shapeInference";
import { generatePyTorch } from "./codeGenerator";
import type { DNNContext } from "@/canvas/ParamPanel";

interface DNNDesignerPageProps {
  nodeId: string;
  initialSpec?: ArchitectureSpec | null;
  context?: DNNContext;
  onBack: () => void;
  onSave: (nodeId: string, spec: ArchitectureSpec) => void;
}

export function DNNDesignerPage({ nodeId, initialSpec, context, onBack, onSave }: DNNDesignerPageProps) {
  const {
    nodes, edges,
    architectureName, setArchitectureName,
    selectedNodeId,
    addLayer, toSpec, loadSpec, reset, dirty, markClean,
  } = useDNNStore();  // addLayer also used in mount effect for UpstreamInput auto-placement

  const [saved, setSaved] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [nameVal, setNameVal] = useState(architectureName);

  // Load initial spec once on mount; auto-place UpstreamInput nodes when opening fresh
  useEffect(() => {
    if (initialSpec) {
      loadSpec(initialSpec);
    } else {
      reset();
      // Auto-place UpstreamInput nodes from context when there's no saved spec
      const inputsWithDim = context?.inputs?.filter((u) => u.embeddingDim != null) ?? [];
      inputsWithDim.forEach((u, i) => {
        const port = u.targetHandle?.split(".").pop() ?? "embedding_input";
        addLayer("UpstreamInput", { x: 60, y: 80 + i * 190 }, {
          features: u.embeddingDim!,
          port,
          toolId: u.toolId,
          toolName: u.toolName,
        });
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Compute shapes live
  const shapeMap = useMemo(() => inferShapes(nodes, edges), [nodes, edges]);

  // Generate PyTorch code
  const code = useMemo(() => generatePyTorch(nodes, edges, shapeMap), [nodes, edges, shapeMap]);

  // Stats
  const layerCount = nodes.length;
  const paramCount = useMemo(() => countParams(nodes, shapeMap), [nodes, shapeMap]);

  function handleSave() {
    const spec = toSpec();
    onSave(nodeId, spec);
    markClean();
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  // Drag-and-drop onto canvas
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const layerType = e.dataTransfer.getData("application/dnn-layer-type");
      if (!layerType) return;

      // Convert drop coordinates to flow graph position
      const bounds = (e.currentTarget as HTMLElement).getBoundingClientRect();
      const position = {
        x: e.clientX - bounds.left - 75,
        y: e.clientY - bounds.top  - 40,
      };
      addLayer(layerType, position);
    },
    [addLayer]
  );

  function commitNameEdit() {
    const trimmed = nameVal.trim();
    if (trimmed) setArchitectureName(trimmed);
    else setNameVal(architectureName);
    setEditingName(false);
  }

  return (
    <div className="flex flex-col h-screen bg-[#0f1117] text-white overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-4 h-11 border-b border-border shrink-0">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors"
        >
          ← Canvas
        </button>
        <div className="w-px h-4 bg-border" />
        <Layers size={14} className="text-fuchsia-400 shrink-0" />
        <span className="text-sm font-bold text-white">DNN Designer</span>
        <div className="w-px h-4 bg-border" />

        {/* Architecture name */}
        {editingName ? (
          <input
            autoFocus
            value={nameVal}
            onChange={(e) => setNameVal(e.target.value)}
            onBlur={commitNameEdit}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitNameEdit();
              if (e.key === "Escape") { setEditingName(false); setNameVal(architectureName); }
            }}
            className="bg-transparent border-b border-indigo-500 outline-none text-sm font-semibold
              text-white px-0.5 min-w-[120px]"
          />
        ) : (
          <button
            onClick={() => { setNameVal(architectureName); setEditingName(true); }}
            className="text-sm font-semibold text-slate-200 hover:text-white transition-colors"
          >
            {architectureName}
          </button>
        )}

        {dirty && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" title="Unsaved changes" />}

        {/* Upstream inputs chips */}
        {context && context.inputs.length > 0 && (
          <>
            <div className="w-px h-4 bg-border" />
            <div className="flex items-center gap-1.5 overflow-x-auto">
              {context.inputs.map((u) => {
                const isEmbed = u.category === "sequence_embedding";
                const isDataset = u.toolId === "dataset";
                const port = u.targetHandle?.split(".").pop() ?? u.targetHandle ?? "";
                return (
                  <div
                    key={u.nodeId + (u.targetHandle ?? "")}
                    className={`flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-medium shrink-0 ${
                      isEmbed
                        ? "bg-pink-950/40 border-pink-700/40 text-pink-300"
                        : isDataset
                        ? "bg-amber-950/40 border-amber-700/40 text-amber-300"
                        : "bg-slate-800 border-slate-600 text-slate-300"
                    }`}
                    title={`${u.toolName} → ${port}`}
                  >
                    {isEmbed ? <Zap size={9} /> : isDataset ? <Database size={9} /> : null}
                    <span>{u.toolName}</span>
                    {u.embeddingDim != null && (
                      <span className="text-pink-400 font-mono">{u.embeddingDim}d</span>
                    )}
                    {port && <span className="text-slate-500">→ {port}</span>}
                  </div>
                );
              })}
            </div>
          </>
        )}

        {/* Stats */}
        <div className="ml-auto flex items-center gap-4">
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <Layers size={12} />
            <span>{layerCount} layer{layerCount !== 1 ? "s" : ""}</span>
          </div>
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <Activity size={12} />
            <span>~{formatParamCount(paramCount)} params</span>
          </div>
          <button
            onClick={handleSave}
            className={`flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg
              transition-all ${
                saved
                  ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                  : "bg-fuchsia-500/20 text-fuchsia-300 border border-fuchsia-500/40 hover:bg-fuchsia-500/30"
              }`}
          >
            {saved ? <Check size={13} /> : <Save size={13} />}
            {saved ? "Saved!" : "Save Architecture"}
          </button>
        </div>
      </div>

      {/* Body: palette | canvas | param panel */}
      <div className="flex flex-1 overflow-hidden">
        <LayerPalette />

        <ReactFlowProvider>
          <DNNCanvas
            shapeMap={shapeMap}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
          />
        </ReactFlowProvider>

        {selectedNodeId && <LayerParamPanel shapeMap={shapeMap} />}
      </div>

      {/* Bottom code preview */}
      <CodePreview code={code} />
    </div>
  );
}
