import { useState, useRef, useEffect } from "react";
import ReactDOM from "react-dom";
import { Sparkles, X, Wand2, AlertCircle } from "lucide-react";
import { generatePipeline } from "@/api/pipelines";
import { useCanvasStore } from "@/canvas/store";
import { useTools } from "@/api/tools";
import { randomUUID } from "@/utils";

const EXAMPLES = [
  "Antibody–antigen docking pipeline: take a VH/VL sequence pair, predict structure with ImmuneBuilder, then dock against a target with HADDOCK",
  "CDR optimization loop: start from a seed sequence, generate 8 CDR variants, embed with AbMAP, score with RCC-MLDE, filter for developability, and repeat for 5 iterations",
  "De novo binder design: diffuse a 80-residue backbone against a target, design sequences with ProteinMPNN, fold with ESMFold, dock with HADDOCK",
  "Liability scan: input VH/VL, run liability scanner and developability filter, output a summary",
];

interface Props {
  onClose: () => void;
  onPipelineLoaded: (name: string, id: string) => void;
}

export function AIPipelineModal({ onClose, onPipelineLoaded }: Props) {
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { data: tools } = useTools();
  const loadPipeline = useCanvasStore((s) => s.loadPipeline);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  async function handleGenerate() {
    if (!prompt.trim() || loading) return;
    setLoading(true);
    setError("");
    try {
      const pipeline = await generatePipeline(prompt.trim());
      if (!tools) throw new Error("Tool registry not loaded yet — try again.");
      // Give it a fresh ID in case backend didn't
      pipeline.id = pipeline.id || randomUUID();
      loadPipeline(pipeline, tools);
      localStorage.setItem("pdp_pipeline_id", pipeline.id);
      localStorage.setItem("pdp_pipeline_name", pipeline.name);
      onPipelineLoaded(pipeline.name, pipeline.id);
      onClose();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err as { message?: string })?.message ??
        "Generation failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") onClose();
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") handleGenerate();
  }

  const modal = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="relative w-full max-w-2xl mx-4 bg-[#0e1425] border border-border rounded-2xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 px-6 pt-5 pb-4 border-b border-border">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600
            flex items-center justify-center shadow-lg">
            <Sparkles size={15} className="text-white" />
          </div>
          <div>
            <h2 className="text-white text-sm font-semibold">Generate pipeline with AI</h2>
            <p className="text-slate-500 text-xs mt-0.5">Describe what you want — Claude will build the pipeline</p>
          </div>
          <button
            onClick={onClose}
            className="ml-auto p-1.5 rounded-lg text-slate-600 hover:text-white hover:bg-white/10 transition-colors"
          >
            <X size={15} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          <textarea
            ref={textareaRef}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="e.g. Build an active-learning loop: start from a seed antibody, generate CDR variants, score with HADDOCK, rank by acquisition function, repeat for 5 iterations…"
            rows={5}
            className="w-full bg-[#111830] border border-border rounded-xl px-4 py-3
              text-sm text-slate-200 placeholder-slate-600 resize-none
              focus:outline-none focus:border-indigo-500/60 focus:ring-1 focus:ring-indigo-500/30
              transition-colors leading-relaxed"
          />

          {/* Example prompts */}
          <div>
            <p className="text-[11px] text-slate-600 uppercase tracking-wider font-semibold mb-2">
              Examples
            </p>
            <div className="space-y-1.5">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => { setPrompt(ex); textareaRef.current?.focus(); }}
                  className="w-full text-left px-3 py-2 rounded-lg text-xs text-slate-400
                    hover:text-slate-200 hover:bg-white/5 border border-transparent
                    hover:border-border transition-all leading-relaxed"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="flex items-start gap-2 px-3 py-2.5 rounded-lg bg-red-500/10 border border-red-500/20">
              <AlertCircle size={14} className="text-red-400 mt-0.5 shrink-0" />
              <p className="text-xs text-red-400 leading-relaxed">{error}</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 pb-5">
          <p className="text-[11px] text-slate-600">
            <kbd className="px-1 py-0.5 rounded bg-white/5 border border-border text-slate-500">⌘ Enter</kbd>
            {" "}to generate
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-1.5 rounded-lg text-sm text-slate-500 hover:text-white
                hover:bg-white/5 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleGenerate}
              disabled={!prompt.trim() || loading}
              className="flex items-center gap-2 px-5 py-1.5 rounded-lg text-sm font-semibold
                text-white disabled:opacity-40 disabled:cursor-not-allowed transition-all
                bg-gradient-to-r from-violet-600 to-indigo-600
                hover:from-violet-500 hover:to-indigo-500 shadow-lg"
              style={{ boxShadow: prompt.trim() && !loading ? "0 0 16px rgba(139,92,246,0.35)" : undefined }}
            >
              <Wand2 size={13} className={loading ? "animate-spin" : ""} />
              <span>{loading ? "Generating…" : "Generate"}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  return ReactDOM.createPortal(modal, document.body);
}
