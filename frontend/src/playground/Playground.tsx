import { useState } from "react";
import { ArrowLeft, BookOpen, ExternalLink, Save, Check } from "lucide-react";
import { useTools } from "@/api/tools";
import type { ToolSpec } from "@/types";
import { TOOL_PAPERS, type PaperInfo } from "./papers";

const CATEGORY_COLOR: Record<string, string> = {
  input:                "#fbbf24",
  structure_prediction: "#38bdf8",
  structure_design:     "#a78bfa",
  sequence_design:      "#34d399",
  sequence_embedding:   "#fb7185",
  docking:              "#f97316",
  toolbox:              "#e879f9",
  debug:                "#94a3b8",
};

function categoryColor(cat: string): string {
  return CATEGORY_COLOR[cat] ?? "#94a3b8";
}

const NOTES_KEY = (toolId: string) => `pdp-brainstorm-${toolId}`;

// ── Tool card grid ────────────────────────────────────────────────────────────

function ToolCard({ tool, onSelect }: { tool: ToolSpec; onSelect: () => void }) {
  const color = categoryColor(tool.category);
  const paper = TOOL_PAPERS[tool.id];

  return (
    <button
      onClick={onSelect}
      className="group text-left flex flex-col gap-3 p-5 rounded-2xl border border-border
        bg-surface hover:bg-surface2 hover:border-[color:var(--c)] transition-all duration-150
        focus:outline-none focus:ring-2 focus:ring-[color:var(--c)]/40"
      style={{ "--c": color } as React.CSSProperties}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span className="w-3 h-3 rounded-full shrink-0" style={{ background: color }} />
          <span className="text-xs font-semibold uppercase tracking-wider" style={{ color }}>
            {tool.category.replace(/_/g, " ")}
          </span>
        </div>
        {tool.wip && (
          <span className="shrink-0 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5
            rounded bg-fuchsia-950 text-fuchsia-400 border border-fuchsia-800">WIP</span>
        )}
      </div>

      <div>
        <div className="text-base font-bold text-white leading-tight mb-1">{tool.name}</div>
        <div className="text-xs text-slate-500 leading-snug line-clamp-2">{tool.description}</div>
      </div>

      {paper && (
        <div className="flex items-center gap-1.5 text-[10px] text-slate-600 group-hover:text-slate-500">
          <BookOpen size={10} />
          <span className="truncate">{paper.authors} · {paper.journal} {paper.year}</span>
        </div>
      )}

      <div className="text-[11px] font-medium mt-auto pt-1" style={{ color }}>
        {paper ? "View paper + brainstorm →" : "Open brainstorm →"}
      </div>
    </button>
  );
}

// ── PDF viewer ────────────────────────────────────────────────────────────────

function PdfViewer({ paper, toolName }: { paper: PaperInfo | undefined; toolName: string }) {
  const [failed, setFailed] = useState(false);

  if (!paper) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-8">
        <BookOpen size={40} className="text-slate-700" />
        <div>
          <p className="text-slate-400 font-medium mb-1">No paper linked for {toolName}</p>
          <p className="text-xs text-slate-600">
            Add a <code className="bg-surface2 px-1 py-0.5 rounded text-slate-400">paper_url</code> field
            to <code className="bg-surface2 px-1 py-0.5 rounded text-slate-400">tools/{toolName.toLowerCase()}/tool.yaml</code>
          </p>
        </div>
      </div>
    );
  }

  const isLocal = paper.pdfUrl.startsWith("/");
  const viewerUrl = isLocal
    ? paper.pdfUrl
    : `https://docs.google.com/viewer?url=${encodeURIComponent(paper.pdfUrl)}&embedded=true`;

  return (
    <div className="flex flex-col h-full">
      {/* Paper metadata bar */}
      <div className="shrink-0 px-4 py-3 border-b border-border bg-surface2">
        <p className="text-[11px] text-slate-500 mb-0.5">{paper.authors} · {paper.journal} · {paper.year}</p>
        <p className="text-sm font-semibold text-white leading-snug">{paper.title}</p>
        <a
          href={paper.abstractUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 mt-1.5 text-[11px] text-indigo-400 hover:text-indigo-300"
        >
          <ExternalLink size={10} />
          Open original
        </a>
      </div>

      {/* PDF iframe */}
      {!failed ? (
        <iframe
          key={paper.pdfUrl}
          src={viewerUrl}
          className="flex-1 w-full border-0 bg-[#1a1a1a]"
          title={`${toolName} paper`}
          onError={() => setFailed(true)}
        />
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center px-8">
          <p className="text-slate-500 text-sm">PDF preview unavailable for this paper.</p>
          <a
            href={paper.pdfUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500
              text-white text-sm font-medium transition-colors"
          >
            <ExternalLink size={14} />
            Open PDF
          </a>
        </div>
      )}
    </div>
  );
}

// ── Brainstorm notebook ───────────────────────────────────────────────────────

function BrainstormNotebook({ tool }: { tool: ToolSpec }) {
  const [notes, setNotes] = useState(() => {
    try { return localStorage.getItem(NOTES_KEY(tool.id)) ?? ""; } catch { return ""; }
  });
  const [saved, setSaved] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(() => {
    try { return localStorage.getItem(NOTES_KEY(tool.id) + "-ts") ?? null; } catch { return null; }
  });
  const color = categoryColor(tool.category);

  function handleSave() {
    try {
      localStorage.setItem(NOTES_KEY(tool.id), notes);
      const ts = new Date().toLocaleTimeString();
      localStorage.setItem(NOTES_KEY(tool.id) + "-ts", ts);
      setSavedAt(ts);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {}
  }

  const placeholder = `Brainstorm ideas for ${tool.name}…

Ideas:
-

Questions:
-

Notes:
- `;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="shrink-0 px-4 py-3 border-b border-border bg-surface2">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full" style={{ background: color }} />
          <span className="text-sm font-bold text-white">Brainstorm — {tool.name}</span>
        </div>
        <p className="text-[11px] text-slate-600 mt-0.5">
          Your ideas, hypotheses, and questions about this tool. Saved locally.
        </p>
      </div>

      {/* Textarea */}
      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder={placeholder}
        className="flex-1 w-full bg-[#0d0d0d] text-slate-200 text-sm font-mono leading-relaxed
          px-4 py-4 resize-none focus:outline-none placeholder-slate-700 border-0"
        spellCheck={false}
      />

      {/* Save bar */}
      <div className="shrink-0 flex items-center justify-between px-4 py-3
        border-t border-border bg-surface2">
        <span className="text-[11px] text-slate-600">
          {savedAt ? `Last saved ${savedAt}` : "Not yet saved"}
        </span>
        <button
          onClick={handleSave}
          className="flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium
            transition-all duration-150"
          style={{
            background: saved ? "#064e3b" : color + "22",
            border: `1px solid ${saved ? "#34d399" : color + "55"}`,
            color: saved ? "#34d399" : color,
          }}
        >
          {saved ? <Check size={13} /> : <Save size={13} />}
          {saved ? "Saved!" : "Save"}
        </button>
      </div>
    </div>
  );
}

// ── Split view ────────────────────────────────────────────────────────────────

function SplitView({ tool, onBack }: { tool: ToolSpec; onBack: () => void }) {
  const color = categoryColor(tool.category);
  const paper = TOOL_PAPERS[tool.id];

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Sub-header */}
      <div className="shrink-0 flex items-center gap-3 px-4 py-2.5 border-b border-border bg-surface">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-white transition-colors"
        >
          <ArrowLeft size={13} />
          All tools
        </button>
        <span className="text-slate-700">/</span>
        <span className="w-2 h-2 rounded-full" style={{ background: color }} />
        <span className="text-sm font-semibold text-white">{tool.name}</span>
        <span className="text-xs text-slate-600">{tool.category.replace(/_/g, " ")}</span>
      </div>

      {/* Split panes */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: PDF */}
        <div className="flex-1 border-r border-border overflow-hidden flex flex-col">
          <PdfViewer paper={paper} toolName={tool.name} />
        </div>

        {/* Right: Brainstorm */}
        <div className="flex-1 overflow-hidden flex flex-col">
          <BrainstormNotebook tool={tool} />
        </div>
      </div>
    </div>
  );
}

// ── Main Playground ───────────────────────────────────────────────────────────

interface PlaygroundProps {
  onBack: () => void;
}

export function Playground({ onBack }: PlaygroundProps) {
  const { data: tools, isLoading } = useTools();
  const [selectedTool, setSelectedTool] = useState<ToolSpec | null>(null);

  const visibleTools = tools?.filter((t) => t.category !== "debug") ?? [];

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-canvas">
      {/* Top bar */}
      <div
        className="h-12 shrink-0 border-b border-border flex items-center px-4 gap-4"
        style={{ background: "linear-gradient(90deg, #0e1425 0%, #111830 100%)" }}
      >
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={15} />
          Back to Canvas
        </button>
        <div className="w-px h-4 bg-border" />
        <span className="text-sm font-bold text-white">Playground</span>
        {!selectedTool && (
          <span className="text-xs text-slate-600">
            Click a tool to preview its paper and brainstorm ideas
          </span>
        )}
      </div>

      {selectedTool ? (
        <SplitView tool={selectedTool} onBack={() => setSelectedTool(null)} />
      ) : (
        <div className="flex-1 overflow-y-auto p-8">
          {isLoading && (
            <div className="text-slate-600 animate-pulse text-center pt-16">Loading tools…</div>
          )}

          {!isLoading && (
            <div className="max-w-5xl mx-auto">
              <div className="mb-8 text-center">
                <h1 className="text-2xl font-bold text-white mb-2">Tool Playground</h1>
                <p className="text-slate-500 text-sm">
                  Explore the science behind each tool, read the original paper, and capture your ideas.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {visibleTools.map((tool) => (
                  <ToolCard key={tool.id} tool={tool} onSelect={() => setSelectedTool(tool)} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
