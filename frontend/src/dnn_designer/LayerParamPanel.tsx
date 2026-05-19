import { X } from "lucide-react";
import { LAYER_BY_TYPE } from "./layers";
import { useDNNStore } from "./store";
import type { ShapeMap } from "./shapeInference";
import { shapeLabel, isShapeError } from "./shapeInference";

interface LayerParamPanelProps {
  shapeMap: ShapeMap;
}

export function LayerParamPanel({ shapeMap }: LayerParamPanelProps) {
  const { nodes, selectedNodeId, selectNode, updateLayerParams } = useDNNStore();
  const node = nodes.find((n) => n.id === selectedNodeId);
  if (!node) return null;

  const { layerType, params } = node.data;
  const def = LAYER_BY_TYPE.get(layerType);
  if (!def) return null;

  const info = shapeMap.get(node.id);
  const outShape = info?.outputShape;
  const hasError = outShape ? isShapeError(outShape) : false;

  function handleChange(name: string, value: unknown) {
    updateLayerParams(node!.id, { ...params, [name]: value });
  }

  return (
    <div className="w-64 shrink-0 border-l border-border bg-surface flex flex-col overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-2.5 border-b border-border"
        style={{ borderTopColor: def.color, borderTopWidth: 2 }}
      >
        <div>
          <div className="text-xs font-bold text-white">{def.label}</div>
          <div className="text-[10px] text-slate-500 capitalize">
            {def.category.replace(/_/g, " ")}
          </div>
        </div>
        <button
          onClick={() => selectNode(null)}
          className="text-slate-500 hover:text-white transition-colors p-0.5 rounded hover:bg-white/5"
        >
          <X size={14} />
        </button>
      </div>

      {/* Shape info */}
      {info && (
        <div className="px-3 py-2 border-b border-border bg-canvas/50">
          {info.inputShape?.length > 0 && (
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-[9px] uppercase tracking-wider text-slate-600 w-10">in</span>
              <span className="text-[10px] font-mono text-slate-400">
                {shapeLabel(info.inputShape)}
              </span>
            </div>
          )}
          <div className="flex items-center gap-1.5">
            <span className="text-[9px] uppercase tracking-wider text-slate-600 w-10">out</span>
            {hasError ? (
              <span className="text-[10px] font-mono text-red-400">
                {(outShape as { error: string }).error}
              </span>
            ) : outShape ? (
              <span className="text-[10px] font-mono" style={{ color: def.color }}>
                {shapeLabel(outShape as number[])}
              </span>
            ) : null}
          </div>
        </div>
      )}

      {/* Params */}
      <div className="flex-1 overflow-y-auto px-3 py-3 flex flex-col gap-3">
        {def.params.length === 0 && (
          <p className="text-[11px] text-slate-600 italic">No parameters.</p>
        )}
        {def.params.map((paramDef) => {
          const val = params[paramDef.name] ?? paramDef.default;

          return (
            <div key={paramDef.name} className="flex flex-col gap-1">
              <div className="flex items-center justify-between">
                <label className="text-[10px] font-semibold text-slate-300 flex items-center gap-1">
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ background: def.color }}
                  />
                  {paramDef.name}
                </label>
                <span className="text-[10px] text-slate-600">{paramDef.type}</span>
              </div>
              {paramDef.description && (
                <p className="text-[10px] text-slate-600 pl-2.5 leading-relaxed">
                  {paramDef.description}
                </p>
              )}

              {paramDef.type === "select" ? (
                <select
                  value={String(val)}
                  onChange={(e) => handleChange(paramDef.name, e.target.value)}
                  className="bg-canvas border border-border rounded-lg px-2.5 py-1.5 text-xs
                    text-slate-200 focus:outline-none focus:border-indigo-500/60 w-full cursor-pointer"
                >
                  {(paramDef.options ?? []).map((opt) => (
                    <option key={opt} value={opt} className="bg-[#111827]">{opt}</option>
                  ))}
                </select>
              ) : paramDef.type === "bool" ? (
                <div className="flex items-center gap-2 pl-2.5">
                  <input
                    type="checkbox"
                    checked={Boolean(val)}
                    onChange={(e) => handleChange(paramDef.name, e.target.checked)}
                    className="w-4 h-4 rounded accent-indigo-500 cursor-pointer"
                  />
                  <span className="text-xs text-slate-400">{Boolean(val) ? "true" : "false"}</span>
                </div>
              ) : (
                <input
                  type={paramDef.type === "int" || paramDef.type === "float" ? "number" : "text"}
                  value={String(val)}
                  step={paramDef.type === "float" ? "any" : "1"}
                  min={paramDef.min !== undefined ? paramDef.min : undefined}
                  max={paramDef.max !== undefined ? paramDef.max : undefined}
                  onChange={(e) =>
                    handleChange(
                      paramDef.name,
                      paramDef.type === "int"
                        ? parseInt(e.target.value, 10)
                        : paramDef.type === "float"
                        ? parseFloat(e.target.value)
                        : e.target.value
                    )
                  }
                  className="bg-canvas border border-border rounded-lg px-2.5 py-1.5 text-xs
                    text-slate-200 focus:outline-none focus:border-indigo-500/60 w-full"
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
