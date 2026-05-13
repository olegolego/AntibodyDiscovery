import { useEffect, useState } from "react";
import { Plus, Wrench, CheckCircle2, Loader2 } from "lucide-react";
import { workshopApi, type CustomTool, type CustomToolSummary } from "../api/workshop";

interface ToolListProps {
  selectedId: string | null;
  onSelect: (tool: CustomTool) => void;
  refreshKey?: number;
}

export function ToolList({ selectedId, onSelect, refreshKey = 0 }: ToolListProps) {
  const [tools, setTools] = useState<CustomToolSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  async function load() {
    try {
      setTools(await workshopApi.listTools());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [refreshKey]);

  async function handleCreate() {
    setCreating(true);
    try {
      const tool = await workshopApi.createTool({ name: "New Tool" });
      await load();
      onSelect(tool);
    } finally {
      setCreating(false);
    }
  }

  async function handleSelect(id: string) {
    const full = await workshopApi.getTool(id);
    onSelect(full);
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 flex items-center justify-between border-b border-border">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
          My Tools
        </span>
        <button
          onClick={handleCreate}
          disabled={creating}
          className="p-1 rounded hover:bg-white/5 text-slate-400 hover:text-white transition-colors"
          title="New tool"
        >
          {creating ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {loading && (
          <p className="text-slate-600 text-xs text-center py-4 animate-pulse">Loading…</p>
        )}
        {!loading && tools.length === 0 && (
          <p className="text-slate-600 text-xs text-center py-6 px-3 leading-relaxed">
            No tools yet.{" "}
            <button onClick={handleCreate} className="text-indigo-400 hover:text-indigo-300 underline">
              Create one
            </button>
          </p>
        )}
        {tools.map((t) => (
          <button
            key={t.id}
            onClick={() => handleSelect(t.id)}
            className={`w-full text-left px-3 py-2 flex items-center gap-2 transition-colors
              ${selectedId === t.id
                ? "bg-white/8 text-white"
                : "text-slate-400 hover:text-white hover:bg-white/4"
              }`}
          >
            {t.status === "published"
              ? <CheckCircle2 size={12} className="text-emerald-400 flex-shrink-0" />
              : <Wrench size={12} className="flex-shrink-0 opacity-60" />
            }
            <span className="text-xs truncate flex-1">{t.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
