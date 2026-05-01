import { useState } from "react";
import { ChevronDown, ChevronRight, Menu, X, FlaskConical, Code2 } from "lucide-react";
import { useTools } from "@/api/tools";
import { useCanvasStore } from "@/canvas/store";
import type { ToolSpec } from "@/types";

// Category display config
const CATEGORY_META: Record<string, { label: string; color: string; order: number }> = {
  input:                { label: "Input",               color: "#fbbf24", order: 0 },
  structure_design:     { label: "Structure Design",    color: "#a78bfa", order: 1 },
  structure_prediction: { label: "Structure Prediction",color: "#38bdf8", order: 2 },
  sequence_design:      { label: "Sequence Design",     color: "#34d399", order: 3 },
  sequence_embedding:   { label: "Sequence Embedding",  color: "#fb7185", order: 4 },
  docking:              { label: "Docking",             color: "#f97316", order: 5 },
  molecular_dynamics:   { label: "Molecular Dynamics",  color: "#2dd4bf", order: 6 },
  compute:              { label: "Compute",             color: "#818cf8", order: 80 },
  toolbox:              { label: "Toolbox",             color: "#e879f9", order: 90 },
  debug:                { label: "Debug",               color: "#94a3b8", order: 99 },
};

function categoryMeta(cat: string) {
  return CATEGORY_META[cat] ?? { label: cat.replace(/_/g, " "), color: "#94a3b8", order: 50 };
}

function PaletteItem({ tool }: { tool: ToolSpec }) {
  const addToolNode = useCanvasStore((s) => s.addToolNode);
  const meta = categoryMeta(tool.category);

  const onDragStart = (e: React.DragEvent) => {
    e.dataTransfer.setData("application/tool-spec", JSON.stringify(tool));
    e.dataTransfer.effectAllowed = "move";
  };

  const onDoubleClick = () => {
    addToolNode(tool, { x: 300 + Math.random() * 120, y: 180 + Math.random() * 80 });
  };

  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDoubleClick={onDoubleClick}
      title={tool.wip ? "Coming soon — drag to preview" : "Drag onto canvas · Double-click to add"}
      className="group flex items-center gap-2.5 px-3 py-2 rounded-lg cursor-grab active:cursor-grabbing
        border border-border hover:border-[color:var(--cat-color)] bg-surface
        hover:bg-surface2 transition-all duration-150 select-none"
      style={{ "--cat-color": meta.color } as React.CSSProperties}
    >
      <span
        className="shrink-0 w-2 h-2 rounded-full"
        style={{ background: meta.color }}
      />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-slate-200 leading-tight truncate">{tool.name}</div>
      </div>
      {tool.wip && (
        <span className="shrink-0 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded
          bg-fuchsia-950 text-fuchsia-400 border border-fuchsia-800">
          WIP
        </span>
      )}
    </div>
  );
}

function CategorySection({ category, tools }: { category: string; tools: ToolSpec[] }) {
  const meta = categoryMeta(category);
  const [open, setOpen] = useState(true);
  const isToolbox = category === "toolbox";
  const isCompute = category === "compute";

  return (
    <div>
      {(isToolbox || isCompute) && (
        <div className="mx-2 mt-3 mb-1 border-t border-border" />
      )}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md
          hover:bg-surface2 transition-colors group"
      >
        <span className="text-slate-500 group-hover:text-slate-400 transition-colors">
          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </span>
        <span
          className="text-[11px] font-bold uppercase tracking-widest flex items-center gap-1.5"
          style={{ color: meta.color }}
        >
          {isToolbox && <FlaskConical size={11} />}
          {isCompute && <Code2 size={11} />}
          {meta.label}
        </span>
        <span className="ml-auto text-[11px] text-slate-600">{tools.length}</span>
      </button>

      {open && (
        <div className="mt-1 mb-3 flex flex-col gap-1 pl-1">
          {isToolbox && (
            <p className="px-2 pb-1 text-[10px] text-fuchsia-700 leading-snug">
              Custom model playground — coming soon
            </p>
          )}
          {isCompute && (
            <p className="px-2 pb-1 text-[10px] text-indigo-500 leading-snug">
              Write Python to combine or transform upstream outputs
            </p>
          )}
          {tools.map((tool) => (
            <PaletteItem key={tool.id} tool={tool} />
          ))}
        </div>
      )}
    </div>
  );
}

export function Palette() {
  const [expanded, setExpanded] = useState(true);
  const { data: tools, isLoading, error } = useTools();

  const grouped = tools
    ? [...new Set(tools.map((t) => t.category))]
        .sort((a, b) => categoryMeta(a).order - categoryMeta(b).order)
        .map((cat) => ({ cat, tools: tools.filter((t) => t.category === cat) }))
    : [];

  return (
    <>
      {/* ── Collapsed: floating hamburger button ─────────────── */}
      {!expanded && (
        <button
          onClick={() => setExpanded(true)}
          className="absolute left-3 top-16 z-20 flex items-center justify-center w-9 h-9
            bg-surface border border-border rounded-lg text-slate-400 hover:text-white
            hover:border-indigo-500 shadow-lg transition-all"
          title="Open tool palette"
        >
          <Menu size={18} />
        </button>
      )}

      {/* ── Expanded panel ───────────────────────────────────── */}
      {expanded && (
        <div className="w-56 shrink-0 border-r border-border bg-surface flex flex-col overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-3 border-b border-border">
            <span className="text-xs font-bold uppercase tracking-widest text-slate-400">
              Tools
            </span>
            <button
              onClick={() => setExpanded(false)}
              className="text-slate-500 hover:text-white transition-colors p-0.5 rounded"
              title="Collapse palette"
            >
              <X size={14} />
            </button>
          </div>

          {/* Hint */}
          <p className="px-3 pt-2 pb-1 text-[11px] text-slate-600 leading-tight">
            Drag onto canvas · Double-click to add
          </p>

          {/* Tool list */}
          <div className="flex-1 overflow-y-auto px-2 pt-1 pb-4 flex flex-col gap-0.5">
            {isLoading && (
              <div className="text-xs text-slate-500 px-2 py-3 animate-pulse">Loading…</div>
            )}
            {error && (
              <div className="text-xs text-red-400 px-2 py-3">Failed to load tools</div>
            )}
            {grouped.map(({ cat, tools }) => (
              <CategorySection key={cat} category={cat} tools={tools} />
            ))}
          </div>
        </div>
      )}
    </>
  );
}
