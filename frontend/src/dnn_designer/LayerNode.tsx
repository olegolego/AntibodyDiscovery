import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { LAYER_BY_TYPE, isShapeError } from "./layers";
import { shapeLabel, type ShapeMap } from "./shapeInference";
import type { LayerNodeData } from "./store";

interface LayerNodeProps extends NodeProps<LayerNodeData> {
  shapeMap?: ShapeMap;
}

export const LayerNode = memo(function LayerNode({ id, data, selected }: LayerNodeProps) {
  // shapeMap is injected into data by DNNCanvas so shape labels stay live
  const shapeMap: ShapeMap = (data as LayerNodeData & { shapeMap?: ShapeMap }).shapeMap ?? new Map();
  const def = LAYER_BY_TYPE.get(data.layerType);
  if (!def) return null;

  const info = shapeMap.get(id);
  const outShape = info?.outputShape;
  const hasError = outShape ? isShapeError(outShape) : false;
  const outLabel = outShape ? (isShapeError(outShape) ? null : shapeLabel(outShape)) : null;
  const inLabel  = info?.inputShape?.length ? shapeLabel(info.inputShape) : null;

  const isInput    = data.layerType === "Input" || data.layerType === "Input3D" || data.layerType === "UpstreamInput";
  const isUpstream = data.layerType === "UpstreamInput";
  const isOutput   = data.layerType === "Output";

  const params = data.params as Record<string, number | boolean | string>;
  const accent = hasError ? "#ef4444" : def.color;

  return (
    <div
      style={{
        borderLeft: `3px solid ${accent}`,
        outline: selected ? `1px solid ${accent}55` : "1px solid transparent",
        outlineOffset: "2px",
        minWidth: 164,
        maxWidth: 210,
      }}
      className="bg-[#0d1117] border border-[#21293a] rounded overflow-hidden select-none"
    >
      {/* ── Top handle (input) ── */}
      {!isInput && (
        <Handle
          type="target"
          position={Position.Top}
          id="in"
          style={{ background: accent, left: "50%", top: -4, width: 8, height: 8 }}
          className="!border-[1.5px] !border-[#0d1117] !rounded-sm"
        />
      )}

      {/* ── Bottom handle (output) ── */}
      {!isOutput && (
        <Handle
          type="source"
          position={Position.Bottom}
          id="out"
          style={{ background: accent, left: "50%", bottom: -4, width: 8, height: 8 }}
          className="!border-[1.5px] !border-[#0d1117] !rounded-sm"
        />
      )}

      {/* ── Header ── */}
      <div className="flex items-center justify-between gap-2 px-2.5 pt-[7px] pb-[5px]">
        <span className="text-[11px] font-semibold text-white leading-tight truncate">
          {isUpstream ? String(params.toolName || "Pipeline Input") : def.label}
        </span>
        <span
          className="text-[8px] font-bold uppercase tracking-widest px-1.5 py-[2px] rounded-sm shrink-0 leading-tight"
          style={{ color: def.color, background: `${def.color}18` }}
        >
          {isUpstream ? "input" : def.category.replace(/_/g, " ")}
        </span>
      </div>

      {/* ── Attribute rows ── */}
      <div className="border-t border-[#21293a]">
        {hasError && outShape ? (
          /* Error state — show the shape-inference error message */
          <div className="px-2.5 py-1.5 bg-red-950/20">
            <span className="text-[9px] text-red-400 leading-snug block">
              {(outShape as { error: string }).error}
            </span>
          </div>
        ) : def.params.length > 0 ? (
          /* Netron-style key/value rows for every param */
          def.params.map((p) => {
            const val = params[p.name] !== undefined ? params[p.name] : p.default;
            return (
              <div
                key={p.name}
                className="flex items-center justify-between px-2.5 py-[3px] odd:bg-white/[0.025]"
              >
                <span
                  className="text-[9px] text-slate-500 truncate"
                  style={{ maxWidth: "56%" }}
                  title={p.name}
                >
                  {p.name.replace(/_/g, " ")}
                </span>
                <span className="text-[9px] font-mono text-slate-200 shrink-0 ml-1.5">
                  {String(val)}
                </span>
              </div>
            );
          })
        ) : (
          /* Param-free layers (ReLU, Pool…) — show the short summary */
          <div className="px-2.5 py-1.5">
            <span className="text-[9px] text-slate-600">{def.summary(params)}</span>
          </div>
        )}
      </div>

      {/* ── Port badge for UpstreamInput ── */}
      {isUpstream && params.port && (
        <div className="px-2.5 py-[3px] border-t border-[#21293a]">
          <span className="text-[8px] font-mono text-slate-500">
            ← {String(params.port)}
          </span>
        </div>
      )}

      {/* ── Shape footer ── */}
      {(inLabel || outLabel) && (
        <div
          className="flex items-center gap-1.5 px-2.5 py-[5px] border-t border-[#21293a]"
        >
          {inLabel && (
            <span className="text-[8px] font-mono text-slate-600">{inLabel}</span>
          )}
          {inLabel && outLabel && (
            <span className="text-[8px] text-[#374151]">→</span>
          )}
          {outLabel && (
            <span
              className="text-[8px] font-mono"
              style={{ color: `${def.color}cc` }}
            >
              {outLabel}
            </span>
          )}
        </div>
      )}
    </div>
  );
});
