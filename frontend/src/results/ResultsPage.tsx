import { useState } from "react";
import ReactDOM from "react-dom";
import { ArrowLeft, BookOpen, Database, Dna, FlaskConical, Layers, Play, X, Zap } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listCollections, createCollection, addEntry } from "@/api/sequences";

// ── API ───────────────────────────────────────────────────────────────────────

interface MoleculeSummary {
  id: string;
  name: string | null;
  heavy_chain: string | null;
  light_chain: string | null;
  run_id: string | null;
  created_at: string;
  counts: { structures: number; docking_results: number; design_sequences: number };
}

interface MoleculeDetail extends MoleculeSummary {
  structures: Array<{
    id: string; tool_id: string; model_rank: number | null;
    has_pdb: boolean; confidence: Record<string, unknown>;
    run_id: string; node_id: string; created_at: string;
  }>;
  docking_results: Array<{
    id: string; antigen_label: string | null; scores: Record<string, number>;
    has_complex: boolean; run_id: string; node_id: string; created_at: string;
  }>;
  design_sequences: Array<{
    id: string; tool_id: string; sequences: string[];
    scores: Record<string, unknown>; has_backbone: boolean;
    run_id: string; created_at: string;
  }>;
  embeddings: Array<{ id: string; tool_id: string; run_id: string; created_at: string }>;
}

async function fetchMolecules(): Promise<MoleculeSummary[]> {
  const r = await fetch("/api/results/molecules/");
  if (!r.ok) throw new Error("Failed to fetch molecules");
  return r.json();
}

async function fetchMolecule(id: string): Promise<MoleculeDetail> {
  const r = await fetch(`/api/results/molecules/${id}/`);
  if (!r.ok) throw new Error("Failed to fetch molecule");
  return r.json();
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function seqPreview(seq: string | null, len = 24): string {
  if (!seq) return "—";
  return seq.length <= len ? seq : `${seq.slice(0, 10)}…${seq.slice(-6)}`;
}

function ts(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// ── Molecule list ─────────────────────────────────────────────────────────────

function MoleculeRow({ mol, onClick }: { mol: MoleculeSummary; onClick: () => void }) {
  const { structures, docking_results, design_sequences } = mol.counts;
  return (
    <button
      onClick={onClick}
      className="w-full text-left flex items-center gap-4 px-4 py-3 border-b border-border
        hover:bg-surface2 transition-colors group"
    >
      <div className="w-8 h-8 rounded-lg bg-indigo-900/40 border border-indigo-700/30
        flex items-center justify-center shrink-0">
        <Dna size={14} className="text-indigo-400" />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-sm font-semibold text-white truncate">
            {mol.name ?? "unnamed"}
          </span>
          <span className="text-[10px] font-mono text-slate-600 truncate hidden sm:block">
            {mol.id.slice(0, 8)}
          </span>
        </div>
        <div className="text-xs font-mono text-slate-500 truncate">
          VH: {seqPreview(mol.heavy_chain)}
          {mol.light_chain && <span className="ml-3">VL: {seqPreview(mol.light_chain)}</span>}
        </div>
      </div>

      <div className="flex items-center gap-3 shrink-0 text-[11px]">
        {structures > 0 && (
          <span className="flex items-center gap-1 text-sky-400">
            <Layers size={10} /> {structures}
          </span>
        )}
        {docking_results > 0 && (
          <span className="flex items-center gap-1 text-orange-400">
            <FlaskConical size={10} /> {docking_results}
          </span>
        )}
        {design_sequences > 0 && (
          <span className="flex items-center gap-1 text-emerald-400">
            <Zap size={10} /> {design_sequences}
          </span>
        )}
        <span className="text-slate-600 group-hover:text-slate-400">{ts(mol.created_at)}</span>
      </div>
    </button>
  );
}

// ── Molecule detail panel ─────────────────────────────────────────────────────

function DetailSection({ title, count, color, children }: {
  title: string; count: number; color: string; children: React.ReactNode;
}) {
  if (count === 0) return null;
  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-2">
        <span className="w-2 h-2 rounded-full" style={{ background: color }} />
        <span className="text-xs font-bold uppercase tracking-wider" style={{ color }}>
          {title}
        </span>
        <span className="text-xs text-slate-600">{count}</span>
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function RunLink({ runId, onOpenRun }: { runId: string; onOpenRun: (id: string) => void }) {
  return (
    <button
      onClick={() => onOpenRun(runId)}
      className="inline-flex items-center gap-1 text-indigo-400 hover:text-indigo-300 transition-colors"
      title="Reopen run panel"
    >
      <Play size={10} fill="currentColor" />
      <span className="font-mono">{runId.slice(0, 8)}</span>
    </button>
  );
}

// ── Save-to-Library modal ─────────────────────────────────────────────────────

function SaveToLibraryModal({ mol, onClose }: { mol: MoleculeDetail; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { data: collections } = useQuery({ queryKey: ["seq-collections"], queryFn: listCollections });
  const [collId, setCollId] = useState<string>("");
  const [newName, setNewName] = useState("");
  const [savedOk, setSavedOk] = useState(false);
  const [errMsg, setErrMsg] = useState("");

  const saveMutation = useMutation({
    mutationFn: async () => {
      let targetCollId = collId;
      if (collId === "__new__") {
        if (!newName.trim()) throw new Error("Collection name is required");
        const coll = await createCollection(newName.trim());
        targetCollId = coll.id;
      }
      if (!targetCollId) throw new Error("Select a collection");
      return addEntry(targetCollId, {
        name: mol.name ?? undefined,
        heavy_chain: mol.heavy_chain!,
        light_chain: mol.light_chain ?? undefined,
        source_molecule_id: mol.id,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["seq-collections"] });
      setSavedOk(true);
      setErrMsg("");
    },
    onError: (e: Error) => setErrMsg(e.message),
  });

  const modal = (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="bg-surface border border-border rounded-2xl shadow-2xl w-[400px] overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border">
          <div className="flex items-center gap-2">
            <BookOpen size={14} className="text-amber-400" />
            <span className="text-sm font-bold text-white">Save to Datasets</span>
          </div>
          <button onClick={onClose}
            className="text-slate-500 hover:text-white p-1 rounded hover:bg-white/5 transition-colors">
            <X size={15} />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <div>
            <div className="text-xs text-slate-500 mb-1">Sequence</div>
            <div className="font-mono text-xs text-slate-400 truncate">
              VH: {mol.heavy_chain ? mol.heavy_chain.slice(0, 24) + (mol.heavy_chain.length > 24 ? "…" : "") : "—"}
            </div>
          </div>

          <div>
            <label className="text-xs text-slate-500 block mb-1">Collection</label>
            <select
              value={collId}
              onChange={(e) => { setCollId(e.target.value); setSavedOk(false); }}
              className="w-full bg-canvas border border-border rounded-lg px-3 py-2 text-sm text-slate-300 focus:outline-none focus:border-amber-500/60"
            >
              <option value="">— Select collection —</option>
              {collections?.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
              <option value="__new__">+ New collection…</option>
            </select>
          </div>

          {collId === "__new__" && (
            <div>
              <label className="text-xs text-slate-500 block mb-1">New collection name</label>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="e.g. Anti-PD-L1 candidates"
                className="w-full bg-canvas border border-border rounded-lg px-3 py-2 text-sm text-slate-300 placeholder-slate-600 focus:outline-none focus:border-amber-500/60"
              />
            </div>
          )}

          {errMsg && <p className="text-xs text-red-400">{errMsg}</p>}
          {savedOk && <p className="text-xs text-emerald-400">Saved ✓</p>}

          <div className="flex justify-end gap-2 pt-1">
            <button onClick={onClose}
              className="px-4 py-1.5 rounded-lg text-sm text-slate-400 hover:text-white hover:bg-white/5 border border-border transition-all">
              {savedOk ? "Close" : "Cancel"}
            </button>
            {!savedOk && (
              <button
                onClick={() => saveMutation.mutate()}
                disabled={saveMutation.isPending || !collId}
                className="px-4 py-1.5 rounded-lg text-sm font-semibold text-white
                  bg-amber-600 hover:bg-amber-500 disabled:opacity-40 transition-all"
              >
                {saveMutation.isPending ? "Saving…" : "Save"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );

  return ReactDOM.createPortal(modal, document.body);
}

function MoleculeDetail({ id, onBack, onOpenRun }: { id: string; onBack: () => void; onOpenRun: (runId: string) => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["molecule", id],
    queryFn: () => fetchMolecule(id),
  });
  const [saveOpen, setSaveOpen] = useState(false);

  if (isLoading || !data) {
    return <div className="p-8 text-slate-600 animate-pulse">Loading…</div>;
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="shrink-0 flex items-center gap-3 px-4 py-3 border-b border-border bg-surface">
        <button onClick={onBack}
          className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-white transition-colors">
          <ArrowLeft size={13} /> All molecules
        </button>
        <span className="text-slate-700">/</span>
        <Dna size={13} className="text-indigo-400" />
        <span className="text-sm font-semibold text-white">{data.name ?? "unnamed"}</span>
        <span className="text-[10px] font-mono text-slate-600">{data.id}</span>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        {/* Sequences */}
        <div className="mb-6 p-4 rounded-xl border border-border bg-surface2">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2">Sequence</div>
          <div className="font-mono text-xs text-slate-300 break-all mb-1">
            <span className="text-amber-400 mr-2">VH</span>{data.heavy_chain ?? "—"}
          </div>
          {data.light_chain && (
            <div className="font-mono text-xs text-slate-300 break-all">
              <span className="text-amber-400/60 mr-2">VL</span>{data.light_chain}
            </div>
          )}
          <div className="mt-2 text-[10px] text-slate-600 flex items-center gap-2">
            Run:{" "}
            {data.run_id
              ? <RunLink runId={data.run_id} onOpenRun={onOpenRun} />
              : <span>—</span>}
            · Created: {ts(data.created_at)}
          </div>
          {data.heavy_chain && (
            <button
              onClick={() => setSaveOpen(true)}
              className="mt-3 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                text-amber-400 hover:text-white border border-amber-700/30 hover:border-amber-500/60
                hover:bg-amber-500/10 transition-all"
            >
              <BookOpen size={11} />
              Save to Datasets
            </button>
          )}
        </div>

        {saveOpen && <SaveToLibraryModal mol={data} onClose={() => setSaveOpen(false)} />}

        {/* Structures */}
        <DetailSection title="Predicted Structures" count={data.structures.length} color="#38bdf8">
          {data.structures.map((s) => (
            <div key={s.id}
              className="flex items-center gap-3 px-3 py-2 rounded-lg bg-surface border border-border text-xs">
              <span className="w-5 h-5 rounded bg-sky-900/40 text-sky-400 flex items-center
                justify-center text-[10px] font-bold shrink-0">
                {s.model_rank ?? "—"}
              </span>
              <span className="text-slate-400 font-medium">{s.tool_id}</span>
              <RunLink runId={s.run_id} onOpenRun={onOpenRun} />
              {s.has_pdb && <span className="text-emerald-400 ml-auto">● PDB ready</span>}
              <a href={`/api/results/structures/${s.id}/pdb`} target="_blank"
                className="text-indigo-400 hover:text-indigo-300 ml-2">download</a>
            </div>
          ))}
        </DetailSection>

        {/* Docking */}
        <DetailSection title="Docking Results" count={data.docking_results.length} color="#f97316">
          {data.docking_results.map((d) => (
            <div key={d.id}
              className="px-3 py-2.5 rounded-lg bg-surface border border-border text-xs space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">vs <span className="text-orange-300">{d.antigen_label}</span></span>
                <div className="flex items-center gap-3">
                  <RunLink runId={d.run_id} onOpenRun={onOpenRun} />
                  {d.has_complex && (
                    <a href={`/api/results/docking/${d.id}/pdb`} target="_blank"
                      className="text-indigo-400 hover:text-indigo-300">download</a>
                  )}
                </div>
              </div>
              {Object.keys(d.scores).length > 0 && (
                <div className="flex flex-wrap gap-x-4 gap-y-0.5 font-mono text-slate-500">
                  {["score", "vdw", "desolv", "air"].map((k) =>
                    d.scores[k] !== undefined ? (
                      <span key={k}>{k}: <span className="text-slate-300">{d.scores[k]}</span></span>
                    ) : null
                  )}
                </div>
              )}
            </div>
          ))}
        </DetailSection>

        {/* Design sequences */}
        <DetailSection title="Designed Sequences" count={data.design_sequences.length} color="#34d399">
          {data.design_sequences.map((ds) => (
            <div key={ds.id}
              className="px-3 py-2 rounded-lg bg-surface border border-border text-xs">
              <span className="text-emerald-400 font-medium mr-2">{ds.tool_id}</span>
              <span className="text-slate-500">{Array.isArray(ds.sequences) ? ds.sequences.length : 0} sequence(s)</span>
              {ds.has_backbone && <span className="text-violet-400 ml-2">+ backbone PDB</span>}
            </div>
          ))}
        </DetailSection>

        {/* Embeddings */}
        <DetailSection title="Embeddings" count={data.embeddings.length} color="#fb7185">
          {data.embeddings.map((e) => (
            <div key={e.id}
              className="px-3 py-2 rounded-lg bg-surface border border-border text-xs flex items-center gap-3">
              <span className="text-rose-400 font-medium">{e.tool_id}</span>
              <span className="text-slate-600 font-mono text-[10px]">{e.id.slice(0, 8)}</span>
            </div>
          ))}
        </DetailSection>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

interface ResultsPageProps {
  onBack: () => void;
  onOpenRun: (runId: string) => void;
}

export function ResultsPage({ onBack, onOpenRun }: ResultsPageProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data: molecules, isLoading } = useQuery({
    queryKey: ["molecules"],
    queryFn: fetchMolecules,
    refetchInterval: 10_000,
  });

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-canvas">
      <div
        className="h-12 shrink-0 border-b border-border flex items-center px-4 gap-4"
        style={{ background: "linear-gradient(90deg, #0e1425 0%, #111830 100%)" }}
      >
        <button onClick={onBack}
          className="flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors">
          <ArrowLeft size={15} /> Back to Canvas
        </button>
        <div className="w-px h-4 bg-border" />
        <Database size={14} className="text-indigo-400" />
        <span className="text-sm font-bold text-white">Results Database</span>
        {molecules && (
          <span className="text-xs text-slate-600">{molecules.length} molecule{molecules.length !== 1 ? "s" : ""}</span>
        )}

        {/* Legend */}
        <div className="ml-auto flex items-center gap-4 text-[11px] text-slate-600">
          <span className="flex items-center gap-1"><Layers size={10} className="text-sky-400" /> structures</span>
          <span className="flex items-center gap-1"><FlaskConical size={10} className="text-orange-400" /> docking</span>
          <span className="flex items-center gap-1"><Zap size={10} className="text-emerald-400" /> designed seqs</span>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left: molecule list */}
        <div className={`flex flex-col border-r border-border overflow-hidden
          ${selectedId ? "w-96 shrink-0" : "flex-1"}`}>
          <div className="shrink-0 px-4 py-2.5 border-b border-border bg-surface">
            <span className="text-xs font-bold uppercase tracking-widest text-slate-500">Molecules</span>
          </div>
          <div className="flex-1 overflow-y-auto">
            {isLoading && (
              <div className="p-8 text-center text-slate-600 animate-pulse text-sm">Loading…</div>
            )}
            {!isLoading && (!molecules || molecules.length === 0) && (
              <div className="p-8 text-center">
                <Database size={32} className="text-slate-700 mx-auto mb-3" />
                <p className="text-slate-500 text-sm font-medium">No results yet</p>
                <p className="text-slate-700 text-xs mt-1">
                  Run a pipeline with Sequence Input — the results appear here automatically.
                </p>
              </div>
            )}
            {molecules?.map((mol) => (
              <MoleculeRow
                key={mol.id}
                mol={mol}
                onClick={() => setSelectedId(mol.id)}
              />
            ))}
          </div>
        </div>

        {/* Right: detail */}
        {selectedId && (
          <div className="flex-1 overflow-hidden flex flex-col">
            <MoleculeDetail
              id={selectedId}
              onBack={() => setSelectedId(null)}
              onOpenRun={(runId) => { onOpenRun(runId); onBack(); }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
