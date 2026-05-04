import { useState, useEffect, useRef } from "react";
import { ArrowLeft, BookOpen, Check, Plus, Search, Trash2, X } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listCollections, getCollection, createCollection,
  deleteCollection, addEntry, deleteEntry, importFromMolecules,
  type SequenceCollection, type SequenceEntry,
} from "@/api/sequences";

// ── Helpers ───────────────────────────────────────────────────────────────────

function seqPreview(seq: string | null, len = 24): string {
  if (!seq) return "—";
  return seq.length <= len ? seq : `${seq.slice(0, 12)}…${seq.slice(-6)}`;
}

function ts(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// ── Import from Results modal ─────────────────────────────────────────────────

interface Molecule { id: string; name: string | null; heavy_chain: string | null; light_chain: string | null; created_at: string; }

function ImportModal({ collId, onClose }: { collId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [done, setDone] = useState(false);

  const { data: molecules } = useQuery<Molecule[]>({
    queryKey: ["molecules"],
    queryFn: async () => {
      const r = await fetch("/api/results/molecules/");
      if (!r.ok) return [];
      return r.json();
    },
  });

  const importMut = useMutation({
    mutationFn: () => importFromMolecules(collId, [...selected]),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["seq-collections"] });
      qc.invalidateQueries({ queryKey: ["seq-collection", collId] });
      setDone(true);
    },
  });

  function toggle(id: string) {
    setSelected((prev) => {
      const s = new Set(prev);
      s.has(id) ? s.delete(id) : s.add(id);
      return s;
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="bg-surface border border-border rounded-2xl shadow-2xl w-[540px] max-h-[520px] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border shrink-0">
          <span className="text-sm font-bold text-white">Import from Results DB</span>
          <button onClick={onClose} className="text-slate-500 hover:text-white p-1 rounded hover:bg-white/5"><X size={14} /></button>
        </div>

        {done ? (
          <div className="flex flex-col items-center justify-center p-10 gap-3">
            <Check size={32} className="text-emerald-400" />
            <span className="text-sm text-emerald-400 font-semibold">Imported {selected.size} sequence{selected.size !== 1 ? "s" : ""}</span>
            <button onClick={onClose} className="mt-2 px-4 py-1.5 rounded-lg text-xs border border-border text-slate-400 hover:text-white hover:bg-white/5 transition-colors">Close</button>
          </div>
        ) : (
          <>
            <div className="flex-1 overflow-y-auto">
              {(!molecules || molecules.length === 0) && (
                <div className="p-8 text-center text-slate-600 text-sm">No molecules in Results DB yet</div>
              )}
              {molecules?.map((mol) => (
                <button key={mol.id} onClick={() => toggle(mol.id)}
                  className={`w-full text-left flex items-center gap-3 px-4 py-2.5 border-b border-border/50 last:border-0 transition-colors
                    ${selected.has(mol.id) ? "bg-amber-500/10" : "hover:bg-surface2"}`}>
                  <div className={`w-4 h-4 rounded border-2 shrink-0 flex items-center justify-center transition-colors
                    ${selected.has(mol.id) ? "bg-amber-500 border-amber-500" : "border-slate-600"}`}>
                    {selected.has(mol.id) && <Check size={10} className="text-black" strokeWidth={3} />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-semibold text-white">{mol.name ?? "unnamed"}</div>
                    <div className="text-[10px] font-mono text-slate-500 truncate">
                      VH: {seqPreview(mol.heavy_chain)}
                      {mol.light_chain && <span className="ml-3">VL: {seqPreview(mol.light_chain)}</span>}
                    </div>
                  </div>
                  <span className="text-[10px] text-slate-600 shrink-0">{ts(mol.created_at)}</span>
                </button>
              ))}
            </div>

            <div className="flex items-center justify-between px-5 py-3 border-t border-border shrink-0">
              <span className="text-xs text-slate-500">{selected.size} selected</span>
              <button
                onClick={() => importMut.mutate()}
                disabled={selected.size === 0 || importMut.isPending}
                className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-amber-500 text-black hover:bg-amber-400
                  disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {importMut.isPending ? "Importing…" : `Import ${selected.size > 0 ? selected.size : ""}`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Collection list (left panel) ──────────────────────────────────────────────

function CollectionList({
  collections, selectedId, onSelect, onCreate, onDelete,
}: {
  collections: SequenceCollection[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreate: (name: string, description?: string) => void;
  onDelete: (id: string) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (creating) inputRef.current?.focus(); }, [creating]);

  function submit() {
    const name = newName.trim();
    if (name) { onCreate(name); setNewName(""); setCreating(false); }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
        <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Collections</span>
        <button onClick={() => setCreating(true)}
          className="flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300 transition-colors">
          <Plus size={12} /> New
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {creating && (
          <div className="px-3 py-2.5 border-b border-border bg-amber-500/5">
            <input ref={inputRef} value={newName} onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") submit(); if (e.key === "Escape") setCreating(false); }}
              placeholder="Collection name…"
              className="w-full bg-canvas border border-amber-500/40 rounded-lg px-2.5 py-1.5 text-xs text-white
                placeholder-slate-600 focus:outline-none focus:border-amber-400 mb-1.5" />
            <div className="flex gap-2">
              <button onClick={submit}
                className="px-2.5 py-1 rounded text-xs bg-amber-500 text-black font-semibold hover:bg-amber-400 transition-colors">
                Save
              </button>
              <button onClick={() => { setCreating(false); setNewName(""); }}
                className="px-2.5 py-1 rounded text-xs text-slate-400 hover:text-white border border-border transition-colors">
                Cancel
              </button>
            </div>
          </div>
        )}

        {collections.length === 0 && !creating && (
          <div className="p-6 text-center">
            <BookOpen size={24} className="text-slate-700 mx-auto mb-2" />
            <p className="text-xs text-slate-600">No collections yet</p>
          </div>
        )}

        {collections.map((col) => (
          <button key={col.id} onClick={() => onSelect(col.id)}
            className={`w-full text-left flex items-center gap-2 px-3 py-2.5 border-b border-border/50 last:border-0
              transition-colors group
              ${selectedId === col.id ? "bg-amber-500/10 border-l-2 border-l-amber-400" : "hover:bg-surface2"}`}>
            <div className="flex-1 min-w-0">
              <div className={`text-xs font-semibold truncate ${selectedId === col.id ? "text-amber-200" : "text-white"}`}>
                {col.name}
              </div>
              <div className="text-[10px] text-slate-600">{col.entry_count} sequences · {ts(col.created_at)}</div>
            </div>
            <button onClick={(e) => { e.stopPropagation(); onDelete(col.id); }}
              className="text-slate-700 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all shrink-0 p-0.5">
              <Trash2 size={11} />
            </button>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Entry list (right panel) ──────────────────────────────────────────────────

function EntryList({ collId }: { collId: string }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [form, setForm] = useState({ name: "", heavy_chain: "", light_chain: "", notes: "" });
  const searchTimer = useRef<ReturnType<typeof setTimeout>>();

  const { data: detail } = useQuery({
    queryKey: ["seq-collection", collId, debouncedQ],
    queryFn: () => getCollection(collId),
  });

  const addMut = useMutation({
    mutationFn: () => addEntry(collId, { name: form.name || undefined, heavy_chain: form.heavy_chain, light_chain: form.light_chain || undefined, notes: form.notes || undefined }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["seq-collection", collId] });
      qc.invalidateQueries({ queryKey: ["seq-collections"] });
      setForm({ name: "", heavy_chain: "", light_chain: "", notes: "" });
      setAdding(false);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteEntry(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["seq-collection", collId] });
      qc.invalidateQueries({ queryKey: ["seq-collections"] });
    },
  });

  function handleSearch(v: string) {
    setQ(v);
    clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => setDebouncedQ(v), 300);
  }

  const entries = debouncedQ
    ? (detail?.entries ?? []).filter(
        (e) =>
          (e.name ?? "").toLowerCase().includes(debouncedQ.toLowerCase()) ||
          e.heavy_chain.toLowerCase().includes(debouncedQ.toLowerCase())
      )
    : (detail?.entries ?? []);

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border shrink-0">
        <div className="flex items-center gap-2 flex-1 bg-canvas border border-border rounded-lg px-2.5 py-1.5">
          <Search size={11} className="text-slate-600 shrink-0" />
          <input value={q} onChange={(e) => handleSearch(e.target.value)} placeholder="Search sequences…"
            className="flex-1 bg-transparent text-xs text-slate-300 placeholder-slate-600 focus:outline-none" />
        </div>
        <button onClick={() => setImporting(true)}
          className="px-2.5 py-1.5 rounded-lg text-xs text-slate-400 border border-border hover:text-white hover:bg-white/5 transition-colors whitespace-nowrap">
          Import from Results
        </button>
        <button onClick={() => setAdding(true)}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-amber-500/20
            border border-amber-500/40 text-amber-300 hover:bg-amber-500/30 transition-colors">
          <Plus size={11} /> Add
        </button>
      </div>

      {/* Add form */}
      {adding && (
        <div className="px-4 py-3 border-b border-border bg-surface2 space-y-2 shrink-0">
          <div className="flex gap-2">
            <input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="Name (optional)"
              className="flex-1 bg-canvas border border-border rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-amber-400/60" />
          </div>
          <textarea value={form.heavy_chain} onChange={(e) => setForm((f) => ({ ...f, heavy_chain: e.target.value }))}
            placeholder="VH sequence (required)"
            rows={2}
            className="w-full bg-canvas border border-border rounded-lg px-2.5 py-1.5 text-xs font-mono text-slate-200
              placeholder-slate-600 resize-none focus:outline-none focus:border-amber-400/60" />
          <textarea value={form.light_chain} onChange={(e) => setForm((f) => ({ ...f, light_chain: e.target.value }))}
            placeholder="VL sequence (optional — leave empty for nanobody)"
            rows={2}
            className="w-full bg-canvas border border-border rounded-lg px-2.5 py-1.5 text-xs font-mono text-slate-200
              placeholder-slate-600 resize-none focus:outline-none focus:border-amber-400/40" />
          <div className="flex gap-2">
            <button onClick={() => addMut.mutate()} disabled={!form.heavy_chain.trim() || addMut.isPending}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-amber-500 text-black hover:bg-amber-400
                disabled:opacity-40 transition-colors">
              {addMut.isPending ? "Saving…" : "Save"}
            </button>
            <button onClick={() => { setAdding(false); setForm({ name: "", heavy_chain: "", light_chain: "", notes: "" }); }}
              className="px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white border border-border transition-colors">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Entry list */}
      <div className="flex-1 overflow-y-auto">
        {entries.length === 0 && (
          <div className="p-8 text-center text-slate-600 text-sm">
            {debouncedQ ? "No matches" : "No sequences yet — add one or import from Results"}
          </div>
        )}
        {entries.map((entry: SequenceEntry) => (
          <div key={entry.id}
            className="flex items-start gap-3 px-4 py-3 border-b border-border/50 last:border-0 group hover:bg-surface2 transition-colors">
            <div className="flex-1 min-w-0">
              <div className="text-xs font-semibold text-white mb-0.5">
                {entry.name ?? <span className="text-slate-500 italic font-normal">unnamed</span>}
                {entry.source_molecule_id && (
                  <span className="ml-2 text-[10px] text-amber-500/60 font-normal">imported</span>
                )}
              </div>
              <div className="font-mono text-[10px] text-slate-400">VH: {seqPreview(entry.heavy_chain, 32)}</div>
              {entry.light_chain && (
                <div className="font-mono text-[10px] text-slate-500">VL: {seqPreview(entry.light_chain, 32)}</div>
              )}
              <div className="text-[10px] text-slate-700 mt-0.5">{ts(entry.created_at)}</div>
            </div>
            <button onClick={() => deleteMut.mutate(entry.id)}
              className="text-slate-700 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all shrink-0 mt-0.5">
              <Trash2 size={12} />
            </button>
          </div>
        ))}
      </div>

      {importing && <ImportModal collId={collId} onClose={() => setImporting(false)} />}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

interface LibraryPageProps {
  onBack: () => void;
}

export function LibraryPage({ onBack }: LibraryPageProps) {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data: collections = [] } = useQuery({
    queryKey: ["seq-collections"],
    queryFn: listCollections,
    refetchInterval: 15_000,
  });

  useEffect(() => {
    if (collections.length > 0 && !selectedId) setSelectedId(collections[0].id);
  }, [collections, selectedId]);

  const createMut = useMutation({
    mutationFn: ({ name, description }: { name: string; description?: string }) =>
      createCollection(name, description),
    onSuccess: (col) => {
      qc.invalidateQueries({ queryKey: ["seq-collections"] });
      setSelectedId(col.id);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteCollection(id),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ["seq-collections"] });
      if (selectedId === id) setSelectedId(null);
    },
  });

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-canvas">
      {/* Header */}
      <div className="h-12 shrink-0 border-b border-border flex items-center px-4 gap-3"
        style={{ background: "linear-gradient(90deg, #0e1425 0%, #111830 100%)" }}>
        <button onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-white transition-colors">
          <ArrowLeft size={14} /> Back
        </button>
        <div className="w-px h-4 bg-border mx-1" />
        <BookOpen size={14} className="text-amber-400" />
        <span className="text-sm font-bold text-white">Datasets</span>
        {collections.length > 0 && (
          <span className="text-xs text-slate-600">{collections.length} collection{collections.length !== 1 ? "s" : ""}</span>
        )}
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: collection list */}
        <div className="w-64 shrink-0 border-r border-border overflow-hidden flex flex-col bg-surface">
          <CollectionList
            collections={collections}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onCreate={(name, description) => createMut.mutate({ name, description })}
            onDelete={(id) => deleteMut.mutate(id)}
          />
        </div>

        {/* Right: entries */}
        <div className="flex-1 overflow-hidden">
          {!selectedId ? (
            <div className="flex flex-col items-center justify-center h-full text-center gap-3">
              <BookOpen size={32} className="text-slate-700" />
              <p className="text-slate-500 text-sm font-medium">Select or create a collection</p>
              <p className="text-slate-700 text-xs">Collections hold named VH/VL sequence pairs<br />that you can reuse across pipelines.</p>
            </div>
          ) : (
            <EntryList collId={selectedId} />
          )}
        </div>
      </div>
    </div>
  );
}
