import { useState, useEffect, useRef } from "react";
import ReactDOM from "react-dom";
import { BookOpen, Search, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import {
  listCollections,
  getCollection,
  type SequenceCollection,
  type SequenceEntry,
} from "@/api/sequences";

function seqPreview(seq: string | null, len = 20): string {
  if (!seq) return "—";
  return seq.length <= len ? seq : `${seq.slice(0, 10)}…${seq.slice(-6)}`;
}

interface Props {
  onSelect: (entry: SequenceEntry) => void;
  onClose: () => void;
}

export function SequencePickerModal({ onSelect, onClose }: Props) {
  const [selectedCollId, setSelectedCollId] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const searchTimer = useRef<ReturnType<typeof setTimeout>>();

  const { data: collections } = useQuery({
    queryKey: ["seq-collections"],
    queryFn: listCollections,
  });

  const { data: detail } = useQuery({
    queryKey: ["seq-collection", selectedCollId, debouncedQ],
    queryFn: () => selectedCollId ? getCollection(selectedCollId) : Promise.resolve(null),
    enabled: !!selectedCollId,
  });

  useEffect(() => {
    if (collections?.length && !selectedCollId) {
      setSelectedCollId(collections[0].id);
    }
  }, [collections, selectedCollId]);

  function handleSearch(value: string) {
    setQ(value);
    clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => setDebouncedQ(value), 300);
  }

  const entries = debouncedQ
    ? (detail?.entries ?? []).filter(
        (e) =>
          (e.name ?? "").toLowerCase().includes(debouncedQ.toLowerCase()) ||
          e.heavy_chain.toLowerCase().includes(debouncedQ.toLowerCase())
      )
    : (detail?.entries ?? []);

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
          {/* Left: collections */}
          <div className="w-48 shrink-0 border-r border-border flex flex-col overflow-hidden">
            <div className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-slate-500 border-b border-border shrink-0">
              Collections
            </div>
            <div className="flex-1 overflow-y-auto">
              {!collections?.length && (
                <div className="px-3 py-4 text-xs text-slate-600 text-center leading-relaxed">
                  No collections yet.
                  <br />
                  <span className="text-amber-500/70">Create one in Datasets.</span>
                </div>
              )}
              {collections?.map((col: SequenceCollection) => (
                <button
                  key={col.id}
                  onClick={() => { setSelectedCollId(col.id); setQ(""); setDebouncedQ(""); }}
                  className={`w-full text-left px-3 py-2.5 border-b border-border/50 last:border-0
                    transition-colors text-xs
                    ${selectedCollId === col.id
                      ? "bg-amber-500/10 text-amber-300 border-l-2 border-l-amber-400"
                      : "text-slate-300 hover:bg-surface2"}`}
                >
                  <div className="font-medium truncate">{col.name}</div>
                  <div className="text-slate-600 mt-0.5">{col.entry_count} sequences</div>
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
              {!selectedCollId && (
                <div className="p-6 text-xs text-slate-600 text-center">Select a collection</div>
              )}
              {selectedCollId && entries.length === 0 && (
                <div className="p-6 text-xs text-slate-600 text-center">
                  {debouncedQ ? "No matches" : "No sequences in this collection"}
                </div>
              )}
              {entries.map((entry: SequenceEntry) => (
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
