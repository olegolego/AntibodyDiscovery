import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Database, FlaskConical, FolderOpen, Play, Save } from "lucide-react";
import { usePipelines, savePipeline } from "@/api/pipelines";
import { useCanvasStore } from "@/canvas/store";
import { useTools } from "@/api/tools";
import type { Pipeline } from "@/types";

interface PipelineBarProps {
  name: string;
  onNameChange: (name: string) => void;
  onRun: () => void;
  running: boolean;
  pipelineId: string;
  onOpenPlayground: () => void;
  onOpenResults: () => void;
}

export function PipelineBar({ name, onNameChange, onRun, running, pipelineId, onOpenPlayground, onOpenResults }: PipelineBarProps) {
  const [showLoad, setShowLoad] = useState(false);
  const [saving, setSaving] = useState(false);
  const { data: savedPipelines } = usePipelines();
  const { data: tools } = useTools();
  const toPipeline = useCanvasStore((s) => s.toPipeline);
  const loadPipeline = useCanvasStore((s) => s.loadPipeline);
  const nodes = useCanvasStore((s) => s.nodes);
  const queryClient = useQueryClient();

  async function handleSave() {
    setSaving(true);
    try {
      const pipeline: Pipeline = { ...toPipeline(name), id: pipelineId };
      await savePipeline(pipeline);
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    } finally {
      setSaving(false);
    }
  }

  function handleLoad(pipeline: Pipeline) {
    if (!tools) return;
    loadPipeline(pipeline, tools);
    setShowLoad(false);
  }

  return (
    <div className="h-12 border-b border-border bg-surface flex items-center px-4 gap-3 relative z-10 shrink-0"
      style={{ background: "linear-gradient(90deg, #0e1425 0%, #111830 100%)" }}
    >
      {/* Logo mark */}
      <div className="flex items-center gap-2 mr-2">
        <div className="w-6 h-6 rounded-md bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white text-xs font-black">
          P
        </div>
        <span className="text-xs font-semibold text-slate-500 hidden sm:block">PDP</span>
      </div>

      {/* Pipeline name */}
      <input
        value={name}
        onChange={(e) => onNameChange(e.target.value)}
        className="bg-transparent text-white text-sm font-medium w-52 focus:outline-none
          border-b border-transparent focus:border-indigo-500/60 pb-0.5 transition-colors
          placeholder-slate-600"
        placeholder="Pipeline name…"
      />

      <div className="flex-1" />

      {/* Load */}
      <div className="relative">
        <button
          onClick={() => setShowLoad((v) => !v)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-slate-400
            hover:text-white hover:bg-white/5 border border-border hover:border-slate-500
            transition-all duration-150"
        >
          <FolderOpen size={13} />
          <span>Load</span>
          <ChevronDown size={11} />
        </button>

        {showLoad && (
          <div className="absolute right-0 top-full mt-1.5 w-64 bg-surface border border-border
            rounded-xl shadow-2xl overflow-hidden z-50">
            <div className="px-3 py-2 border-b border-border text-[11px] text-slate-500 font-semibold uppercase tracking-wider">
              Saved pipelines
            </div>
            {!savedPipelines?.length && (
              <div className="px-4 py-4 text-xs text-slate-500 text-center">No saved pipelines yet</div>
            )}
            {savedPipelines?.map((p) => (
              <button
                key={p.id}
                onClick={() => handleLoad(p)}
                className="w-full text-left px-4 py-2.5 text-sm hover:bg-surface2
                  transition-colors border-b border-border/50 last:border-0"
              >
                <div className="font-medium text-slate-200">{p.name}</div>
                <div className="text-xs text-slate-500 mt-0.5">{p.nodes.length} nodes</div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Save */}
      <button
        onClick={handleSave}
        disabled={saving}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-slate-400
          hover:text-white hover:bg-white/5 border border-border hover:border-slate-500
          transition-all duration-150 disabled:opacity-40"
      >
        <Save size={13} />
        <span>{saving ? "Saving…" : "Save"}</span>
      </button>

      {/* Playground */}
      <button
        onClick={onOpenPlayground}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-slate-400
          hover:text-white hover:bg-white/5 border border-border hover:border-slate-500
          transition-all duration-150"
      >
        <FlaskConical size={13} />
        <span>Playground</span>
      </button>

      {/* Results DB */}
      <button
        onClick={onOpenResults}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
          text-slate-400 hover:text-white border border-transparent
          hover:border-indigo-500/40 hover:bg-indigo-500/10 transition-all"
      >
        <Database size={13} />
        <span>Results</span>
      </button>

      {/* Run */}
      <button
        onClick={onRun}
        disabled={running || nodes.length === 0}
        className="flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-semibold
          text-white disabled:opacity-40 transition-all duration-150 shadow-lg
          bg-gradient-to-r from-indigo-600 to-purple-600
          hover:from-indigo-500 hover:to-purple-500
          disabled:cursor-not-allowed"
        style={{ boxShadow: nodes.length > 0 && !running ? "0 0 16px rgba(99,102,241,0.4)" : undefined }}
      >
        <Play size={13} fill="white" />
        <span>{running ? "Running…" : "Run"}</span>
      </button>
    </div>
  );
}
