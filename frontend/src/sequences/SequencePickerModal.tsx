import { useState, useEffect, useRef } from "react";
import ReactDOM from "react-dom";
import { BookOpen, Search, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { listDatasets, getDataset, type Dataset, type DatasetEntry } from "@/api/datasets";

function seqPreview(seq: string | null, len = 20): string {
  if (!seq) return "—";
  return seq.length <= len ? seq : `${seq.slice(0, 10)}…${seq.slice(-6)}`;
}

interface Props {
  onSelect: (entry: DatasetEntry) => void;
  onClose: () => void;
}

export function SequencePickerModal({ onSelect, onClose }: Props) {
  const [selectedDsId, setSelectedDsId] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const searchTimer = useRef<ReturnType<typeof setTimeout>>();

  const { data: datasets } = useQuery({
    queryKey: ["datasets"],
    queryFn: listDatasets,
  });

  const { data: detail } = useQuery({
    queryKey: ["dataset", selectedDsId],
    queryFn: () => selectedDsId ? getDataset(selectedDsId) : Promise.resolve(null),
    enabled: !!selectedDsId,
  });

  useEffect(() => {
    if (datasets?.length && !selectedDsId) {
      setSelectedDsId(datasets[0].id);
    }
  }, [datasets, selectedDsId]);

  function handleSearch(value: string) {
    setQ(value);
    clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => setDebouncedQ(value), 300);
  }

  const entries = (detail?.entries ?? []).filter((e) => {
    if (!e.heavy_chain) return false;
    if (!debouncedQ) return true;
    const q = debouncedQ.toLowerCase();
    return (e.name ?? "").toLowerCase().includes(q) || (e.heavy_chain ?? "").toLowerCase().includes(q);
  });

  const modal = (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="bg-surface border border-border rounded-2xl shadow-2xl w-[640px] max-h-[520px]
        flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border shrink-0">
          <div className="flex items-center gap-2">
            <BookOpen size={14} className="text-amber-400" />
            <span className="text-sm font-bold text-white">Pick from Datasets</span>
          </div>
          <button onClick={onClose}
            className="text-slate-500 hover:text-white transition-colors p-1 rounded hover:bg-white/5">
            <X size={15} />
          </button>
        </div>

        <div className="flex flex-1 overflow-hidden">
          {/* Left: dataset list */}
          <div className="w-48 shrink-0 border-r border-border flex flex-col overflow-hidden">
            <div className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-slate-500 border-b border-border shrink-0">
              Datasets
            </div>
            <div className="flex-1 overflow-y-auto">
              {!datasets?.length && (
                <div className="px-3 py-4 text-xs text-slate-600 text-center leading-relaxed">
                  No datasets yet.
                  <br />
                  <span className="text-amber-500/70">Create one in Datasets.</span>
                </div>
              )}
              {datasets?.map((ds: Dataset) => (
                <button
                  key={ds.id}
                  onClick={() => { setSelectedDsId(ds.id); setQ(""); setDebouncedQ(""); }}
                  className={`w-full text-left px-3 py-2.5 border-b border-border/50 last:border-0
                    transition-colors text-xs
                    ${selectedDsId === ds.id
                      ? "bg-amber-500/10 text-amber-300 border-l-2 border-l-amber-400"
                      : "text-slate-300 hover:bg-surface2"}`}
                >
                  <div className="font-medium truncate">{ds.name}</div>
                  <div className="text-slate-600 mt-0.5">{ds.entry_count} entries</div>
                </button>
              ))}
            </div>
          </div>

          {/* Right: entries */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Search */}
            <div className="px-3 py-2 border-b border-border shrink-0">
              <div className="flex items-center gap-2 bg-canvas border border-border rounded-lg px-2.5 py-1.5">
                <Search size={11} className="text-slate-600 shrink-0" />
                <input
                  value={q}
                  onChange={(e) => handleSearch(e.target.value)}
                  placeholder="Search name or sequence…"
                  className="flex-1 bg-transparent text-xs text-slate-300 placeholder-slate-600 focus:outline-none"
                />
              </div>
            </div>

            {/* Entry list */}
            <div className="flex-1 overflow-y-auto">
              {!selectedDsId && (
                <div className="p-6 text-xs text-slate-600 text-center">Select a dataset</div>
              )}
              {selectedDsId && entries.length === 0 && (
                <div className="p-6 text-xs text-slate-600 text-center">
                  {debouncedQ ? "No matches" : "No sequences with VH in this dataset"}
                </div>
              )}
              {entries.map((entry: DatasetEntry) => (
                <button
                  key={entry.id}
                  onClick={() => onSelect(entry)}
                  className="w-full text-left px-4 py-2.5 border-b border-border/50 last:border-0
                    hover:bg-amber-500/5 transition-colors group"
                >
                  <div className="flex items-center justify-between mb-0.5">
                    <span className="text-xs font-semibold text-white">
                      {entry.name ?? <span className="text-slate-500 italic">unnamed</span>}
                    </span>
                    <span className="text-[10px] text-amber-400 opacity-0 group-hover:opacity-100 transition-opacity">
                      Select →
                    </span>
                  </div>
                  <div className="font-mono text-[10px] text-slate-500">
                    VH: {seqPreview(entry.heavy_chain)}
                  </div>
                  {entry.light_chain && (
                    <div className="font-mono text-[10px] text-slate-600">
                      VL: {seqPreview(entry.light_chain)}
                    </div>
                  )}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  return ReactDOM.createPortal(modal, document.body);
}
