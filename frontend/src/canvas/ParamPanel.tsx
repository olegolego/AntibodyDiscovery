import { useState } from "react";
import { X, Eye } from "lucide-react";
import { useCanvasStore, type NodeData } from "./store";
import { ComputePanel } from "./ComputePanel";

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
  debug:                "#94a3b8",
};

const ARTIFACT_SENTINEL = "__artifact__";

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

export function ParamPanel() {
  const { nodes, selectedNodeId, selectNode, updateNodeParams, runNodeOutputs } = useCanvasStore();
  const [openOutput, setOpenOutput] = useState<{ name: string; type: string; value: unknown } | null>(null);

  const node = nodes.find((n) => n.id === selectedNodeId);
  if (!node) return null;

  const data = node.data as NodeData;

  // Compute node gets its own full-featured panel
  if (data.tool.id === "compute") {
    return <ComputePanel />;
  }
  const { tool, params } = data;
  const accentColor = CATEGORY_COLOR[tool.category] ?? "#94a3b8";
  const nodeOutputs = runNodeOutputs[node.id] ?? {};

  function handleChange(name: string, value: unknown) {
    updateNodeParams(node!.id, { ...params, [name]: value });
  }

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
          {tool.description && (
            <p className="text-xs text-slate-500 leading-relaxed">{tool.description}</p>
          )}

          {(() => {
            const configurable = tool.inputs.filter(
              (p) => p.type !== "fasta" && p.type !== "pdb"
            );
            if (configurable.length === 0)
              return <p className="text-xs text-slate-600">No configurable parameters. Connect inputs via edges.</p>;
            return null;
          })()}

          {tool.inputs.filter((p) => p.type !== "fasta" && p.type !== "pdb").map((port) => {
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
                  <p className="text-[11px] text-slate-600 pl-3">{port.description}</p>
                )}

                {inputType === "checkbox" ? (
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
