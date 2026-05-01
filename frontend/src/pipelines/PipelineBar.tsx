import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BookOpen, ChevronDown, Database, FilePlus, FlaskConical, FolderOpen, Play, Save, Terminal, Trash2 } from "lucide-react";
import { usePipelines, savePipeline, deletePipeline } from "@/api/pipelines";
import { useCanvasStore } from "@/canvas/store";
import { useTools } from "@/api/tools";
import { randomUUID } from "@/utils";
import type { Pipeline } from "@/types";

interface PipelineBarProps {
  name: string;
  onNameChange: (name: string) => void;
  onRun: () => void;
  running: boolean;
  pipelineId: string;
  onPipelineIdChange: (id: string) => void;
  onOpenPlayground: () => void;
  onOpenResults: () => void;
  onOpenLibrary: () => void;
  onOpenTerminal: () => void;
  onNewPipeline: () => void;
}

function ts(iso: string | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function PipelineBar({
  name, onNameChange, onRun, running, pipelineId, onPipelineIdChange,
  onOpenPlayground, onOpenResults, onOpenLibrary, onOpenTerminal, onNewPipeline,
}: PipelineBarProps) {
  const [showLoad, setShowLoad] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const { data: savedPipelines } = usePipelines();
  const { data: tools } = useTools();
  const toPipeline = useCanvasStore((s) => s.toPipeline);
  const loadPipeline = useCanvasStore((s) => s.loadPipeline);
  const resetCanvas = useCanvasStore((s) => s.resetCanvas);
  const nodes = useCanvasStore((s) => s.nodes);
  const queryClient = useQueryClient();

  function handleNew() {
    if (nodes.length > 0 && !window.confirm("Start a new pipeline? The current canvas will be cleared.")) return;
    const freshId = randomUUID();
    resetCanvas();
    onPipelineIdChange(freshId);
    onNameChange("Untitled pipeline");
    localStorage.setItem("pdp_pipeline_id", freshId);
    localStorage.setItem("pdp_pipeline_name", "Untitled pipeline");
    onNewPipeline();
  }

  async function handleSave() {
    setSaving(true);
    setSaveError("");
    try {
      const pipeline: Pipeline = { ...toPipeline(name), id: pipelineId };
      await savePipeline(pipeline);
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    } catch (err: unknown) {
      setSaveError(String((err as { message?: string })?.message ?? "Save failed"));
    } finally {
      setSaving(false);
    }
  }

  function handleLoad(pipeline: Pipeline) {
    if (!tools) return;
    loadPipeline(pipeline, tools);
    onPipelineIdChange(pipeline.id);
    onNameChange(pipeline.name);
    localStorage.setItem("pdp_pipeline_name", pipeline.name);
    setShowLoad(false);
  }

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    setDeletingId(id);
    try {
      await deletePipeline(id);
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    } finally {
      setDeletingId(null);
    }
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

      {/* Save error badge */}
      {saveError && (
        <span className="text-xs text-red-400 max-w-xs truncate" title={saveError}>
          ⚠ {saveError}
        </span>
      )}

      {/* New */}
      <button
        onClick={handleNew}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-slate-400
          hover:text-white hover:bg-white/5 border border-border hover:border-slate-500
          transition-all duration-150"
      >
        <FilePlus size={13} />
        <span>New</span>
      </button>

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
          <div className="absolute right-0 top-full mt-1.5 w-80 bg-surface border border-border
            rounded-xl shadow-2xl overflow-hidden z-50">
            <div className="px-3 py-2 border-b border-border text-[11px] text-slate-500 font-semibold uppercase tracking-wider flex items-center justify-between">
              <span>Saved pipelines</span>
              <span className="text-slate-700">{savedPipelines?.length ?? 0}</span>
            </div>
            <div className="max-h-72 overflow-y-auto">
              {!savedPipelines?.length && (
                <div className="px-4 py-4 text-xs text-slate-500 text-center">No saved pipelines yet</div>
              )}
              {savedPipelines?.map((p) => (
                <div key={p.id}
                  className={`flex items-center gap-2 border-b border-border/50 last:border-0 group
                    hover:bg-surface2 transition-colors
                    ${p.id === pipelineId ? "bg-indigo-500/5 border-l-2 border-l-indigo-500" : ""}`}
                >
                  <button
                    onClick={() => handleLoad(p)}
                    className="flex-1 text-left px-4 py-2.5 min-w-0"
                  >
                    <div className="font-medium text-slate-200 text-sm truncate">{p.name}</div>
                    <div className="flex items-center gap-2 mt-0.5 text-[10px] text-slate-600">
                      <span>{p.nodes.length} node{p.nodes.length !== 1 ? "s" : ""}</span>
                      {p.updated_at && (
                        <>
                          <span>·</span>
                          <span>{ts(p.updated_at)}</span>
                        </>
                      )}
                    </div>
                  </button>
                  <button
                    onClick={(e) => handleDelete(e, p.id)}
                    disabled={deletingId === p.id}
                    className="shrink-0 mr-3 p-1.5 rounded text-slate-700
                      hover:text-red-400 hover:bg-red-400/10 transition-colors
                      opacity-0 group-hover:opacity-100 disabled:opacity-40"
                    title="Delete pipeline"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
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

      {/* Terminal */}
      <button
        onClick={onOpenTerminal}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
          text-slate-400 hover:text-white border border-transparent
          hover:border-violet-500/40 hover:bg-violet-500/10 transition-all"
      >
        <Terminal size={13} />
        <span>Terminal</span>
      </button>

      {/* Library */}
      <button
        onClick={onOpenLibrary}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
          text-slate-400 hover:text-white border border-transparent
          hover:border-amber-500/40 hover:bg-amber-500/10 transition-all"
      >
        <BookOpen size={13} />
        <span>Library</span>
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
