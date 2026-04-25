import { X, Atom, BarChart2, Grid3x3, Info } from "lucide-react";
import { useQuery, useQueries } from "@tanstack/react-query";
import { fetchNodeAnalysis, type NodeAnalysis } from "@/api/analysis";
import { StructureViewer } from "./StructureViewer";
import { PLDDTChart } from "./PLDDTChart";
import { PAEHeatmap } from "./PAEHeatmap";
import { RMSDChart } from "./RMSDChart";
import { useState } from "react";

interface Props {
  runId: string;
  nodeId: string;
  onClose: () => void;
}

const CONTENT_TABS = [
  { id: "overview", label: "Overview", icon: Info },
  { id: "structure", label: "3D Structure", icon: Atom },
  { id: "plddt", label: "Confidence", icon: BarChart2 },
  { id: "pae", label: "PAE", icon: Grid3x3, requiresPAE: true },
] as const;

type ContentTab = (typeof CONTENT_TABS)[number]["id"];

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-canvas border border-border rounded-xl px-4 py-3 flex flex-col gap-0.5">
      <div className="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">{label}</div>
      <div className="text-xl font-bold text-white">{value}</div>
      {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
    </div>
  );
}

function ConfidenceBand({ label, pct, color }: { label: string; pct: number; color: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
      <span className="text-slate-400 w-40 shrink-0">{label}</span>
      <div className="flex-1 bg-canvas rounded-full h-1.5 overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="text-slate-400 w-10 text-right">{pct.toFixed(0)}%</span>
    </div>
  );
}

// ── Single-model content (non-ImmuneBuilder) ─────────────────────────────────

function ModelContent({ data }: { data: NodeAnalysis }) {
  const [tab, setTab] = useState<ContentTab>("overview");
  const tabs = CONTENT_TABS.filter((t) => !("requiresPAE" in t && t.requiresPAE && !data.pae));

  return (
    <div className="flex flex-col gap-0">
      <div className="flex items-center gap-1 py-2 border-b border-border shrink-0 bg-canvas px-1">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              tab === id
                ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
                : "text-slate-500 hover:text-slate-300 hover:bg-white/5"
            }`}
          >
            <Icon size={12} />
            {label}
          </button>
        ))}
      </div>

      <div className="pt-4">
        {tab === "overview" && data.plddt && (
          <div className="flex flex-col gap-6">
            {(data.plddt as unknown as { description?: string }).description && (
              <p className="text-sm text-slate-400 leading-relaxed">
                {(data.plddt as unknown as { description: string }).description}
              </p>
            )}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <StatCard label="Mean pLDDT" value={(data.plddt as unknown as { mean_plddt?: number }).mean_plddt?.toFixed(1) ?? "—"} sub="higher = more confident" />
              <StatCard label="Residues" value={(data.plddt as unknown as { sequence_length?: number }).sequence_length?.toString() ?? "—"} sub="amino acids predicted" />
              <StatCard label="High Confidence" value={`${(data.plddt as unknown as { high_confidence_pct?: number }).high_confidence_pct?.toFixed(0) ?? "—"}%`} sub="pLDDT ≥ 70" />
              <StatCard label="Very High" value={`${(data.plddt as unknown as { very_high_confidence_pct?: number }).very_high_confidence_pct?.toFixed(0) ?? "—"}%`} sub="pLDDT ≥ 90" />
            </div>
            {(data.plddt as unknown as { high_confidence_pct?: number }).high_confidence_pct !== undefined && (
              <div className="bg-canvas border border-border rounded-xl p-4 flex flex-col gap-3">
                <div className="text-[11px] font-bold uppercase tracking-widest text-slate-600">Confidence Breakdown</div>
                <ConfidenceBand label="Very high (≥ 90)" pct={(data.plddt as unknown as { very_high_confidence_pct: number }).very_high_confidence_pct} color="#38bdf8" />
                <ConfidenceBand
                  label="Confident (70–90)"
                  pct={Math.max(0, (data.plddt as unknown as { high_confidence_pct: number }).high_confidence_pct - (data.plddt as unknown as { very_high_confidence_pct: number }).very_high_confidence_pct)}
                  color="#34d399"
                />
              </div>
            )}
            {data.structure && (
              <div className="border border-border rounded-xl overflow-hidden" style={{ height: 280 }}>
                <StructureViewer pdbText={data.structure} />
              </div>
            )}
          </div>
        )}

        {tab === "structure" && (
          <div className="border border-border rounded-xl overflow-hidden" style={{ height: 500 }}>
            {data.structure ? (
              <StructureViewer pdbText={data.structure} />
            ) : (
              <div className="flex items-center justify-center h-full text-slate-500 text-sm">No structure available</div>
            )}
          </div>
        )}

        {tab === "plddt" && (
          <div className="flex flex-col gap-4">
            {data.plddt ? (
              <>
                <div className="bg-canvas border border-border rounded-xl p-4">
                  <div className="text-[11px] font-bold uppercase tracking-widest text-slate-600 mb-3">
                    Per-Residue pLDDT
                  </div>
                  <PLDDTChart plddt={data.plddt} />
                </div>
                <div className="flex items-center gap-4 text-[11px] text-slate-500 px-1">
                  <span className="flex items-center gap-1.5"><span className="w-2 h-0.5 bg-sky-400 inline-block" /> Very high (≥90)</span>
                  <span className="flex items-center gap-1.5"><span className="w-2 h-0.5 bg-emerald-400 inline-block" /> Confident (≥70)</span>
                  <span className="flex items-center gap-1.5"><span className="w-2 h-0.5 bg-amber-400 inline-block" /> Low (≥50)</span>
                  <span className="flex items-center gap-1.5"><span className="w-2 h-0.5 bg-red-400 inline-block" /> Very low (&lt;50)</span>
                </div>
              </>
            ) : (
              <div className="text-slate-500 text-sm text-center py-12">No confidence data</div>
            )}
          </div>
        )}

        {tab === "pae" && (
          <div className="flex flex-col gap-4">
            {(data.pae as unknown as { predicted_aligned_error?: number[][] } | null)?.predicted_aligned_error ? (
              <div className="bg-canvas border border-border rounded-xl p-4">
                <div className="text-[11px] font-bold uppercase tracking-widest text-slate-600 mb-1">PAE</div>
                <PAEHeatmap pae={data.pae!} />
              </div>
            ) : (
              <div className="text-slate-500 text-sm text-center py-12">No PAE data</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── ImmuneBuilder: 2×2 structure grid + RMSD plot ───────────────────────────

function ImmuneBuilderGrid({ models }: { models: Array<{ index: number; data: NodeAnalysis | undefined | null }> }) {
  // RMSD is per-ensemble, same for all models — read from the first available model
  const rmsd = (
    models.find((m) => m.data)?.data?.plddt as unknown as { per_residue_rmsd?: number[] } | null
  )?.per_residue_rmsd ?? [];

  return (
    <div className="pt-4 flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-4">
        {models.map((m) => (
          <div key={m.index} className="flex flex-col gap-2">
            <span className="text-xs font-semibold text-violet-300">Model {m.index + 1}</span>
            <div className="border border-border rounded-xl overflow-hidden" style={{ height: 260 }}>
              {m.data?.structure
                ? <StructureViewer pdbText={m.data.structure} />
                : <div className="flex items-center justify-center h-full text-slate-500 text-xs">No structure</div>
              }
            </div>
          </div>
        ))}
      </div>

      {rmsd.length > 0 && (
        <div className="border border-border rounded-xl p-4">
          <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-1">
            Per-Residue RMSD (Å) — ensemble disagreement
          </div>
          <div className="text-[11px] text-slate-600 mb-3">
            Lower = models agree (confident) · Higher = models disagree (flexible/uncertain)
          </div>
          <RMSDChart rmsd={rmsd} />
          <div className="flex items-center gap-4 mt-2 text-[11px] text-slate-500 px-1">
            <span className="flex items-center gap-1.5"><span className="w-2 h-0.5 bg-emerald-400 inline-block" /> &lt; 0.5 Å confident</span>
            <span className="flex items-center gap-1.5"><span className="w-2 h-0.5 bg-amber-400 inline-block" /> 0.5–1.0 Å moderate</span>
            <span className="flex items-center gap-1.5"><span className="w-2 h-0.5 bg-red-400 inline-block" /> &gt; 1.0 Å uncertain</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── HADDOCK3: scores table + best complex viewer ─────────────────────────────

const HADDOCK_METRICS = [
  { key: "score",  label: "HADDOCK score", hint: "lower = better" },
  { key: "vdw",    label: "Van der Waals", hint: "Å" },
  { key: "desolv", label: "Desolvation",   hint: "kcal/mol" },
  { key: "air",    label: "AIR energy",    hint: "ambiguous restraints" },
  { key: "bsa",    label: "BSA",           hint: "buried surface area Å²" },
];

function HADDOCK3View({ data }: { data: NodeAnalysis }) {
  const scores = data.plddt as unknown as Record<string, number> | null;
  return (
    <div className="pt-4 flex flex-col gap-4">
      {scores && Object.keys(scores).length > 0 && (
        <div className="border border-border rounded-xl overflow-hidden">
          <div className="px-4 py-2 border-b border-border bg-surface2">
            <span className="text-[11px] font-bold uppercase tracking-widest text-slate-500">
              Top Cluster · {scores.n_models ?? "?"} models
            </span>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-2 text-slate-500 font-semibold">Metric</th>
                <th className="text-right px-4 py-2 text-slate-500 font-semibold">Mean</th>
                <th className="text-right px-4 py-2 text-slate-500 font-semibold">± Std</th>
                <th className="text-left px-4 py-2 text-slate-600 font-normal">Unit</th>
              </tr>
            </thead>
            <tbody>
              {HADDOCK_METRICS.map(({ key, label, hint }) => {
                const mean = scores[key];
                const std  = scores[`${key}_std`];
                if (mean === undefined) return null;
                return (
                  <tr key={key} className="border-b border-border/50 hover:bg-white/[0.02]">
                    <td className="px-4 py-2 text-slate-300 font-medium">{label}</td>
                    <td className="px-4 py-2 text-right font-mono text-white">
                      {mean.toFixed(2)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-slate-500">
                      {std !== undefined ? `± ${std.toFixed(2)}` : "—"}
                    </td>
                    <td className="px-4 py-2 text-slate-600">{hint}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <span className="text-[11px] font-bold uppercase tracking-widest text-slate-500">
          Best Complex
        </span>
        <div className="border border-border rounded-xl overflow-hidden" style={{ height: 480 }}>
          {data.structure
            ? <StructureViewer pdbText={data.structure} />
            : <div className="flex items-center justify-center h-full text-slate-500 text-sm">No structure</div>
          }
        </div>
      </div>
    </div>
  );
}

// ── Main panel ───────────────────────────────────────────────────────────────

export function AnalysisPanel({ runId, nodeId, onClose }: Props) {
  const singleQuery = useQuery({
    queryKey: ["analysis", runId, nodeId],
    queryFn: () => fetchNodeAnalysis(runId, nodeId),
    retry: false,
  });

  const modelQueries = useQueries({
    queries: [1, 2, 3, 4].map((i) => ({
      queryKey: ["analysis", runId, `${nodeId}_model_${i}`],
      queryFn: () => fetchNodeAnalysis(runId, `${nodeId}_model_${i}`),
      retry: false,
    })),
  });

  const toolId = singleQuery.data?.tool_id
    ?? modelQueries.find((q) => q.data)?.data?.tool_id;

  const isImmuneBuilder = toolId === "immunebuilder";
  const isHaddock       = toolId === "haddock3";

  const availableModels = modelQueries
    .map((q, i) => ({ index: i, data: q.data }))
    .filter((m) => m.data != null);

  const activeData = isImmuneBuilder ? null : singleQuery.data ?? null;

  const isLoading = isImmuneBuilder
    ? modelQueries.every((q) => q.isLoading)
    : singleQuery.isLoading;
  const hasError = !isLoading && !isImmuneBuilder && activeData == null && !availableModels.length;

  const headerTitle = isImmuneBuilder
    ? "ImmuneBuilder — Structure Predictions"
    : isHaddock
      ? "HADDOCK3 — Docking Results"
      : (activeData?.plddt as unknown as { gene?: string })?.gene
        ? `${(activeData?.plddt as unknown as { gene: string }).gene} — AlphaFold Analysis`
        : "Structure Analysis";

  const headerSub = isImmuneBuilder
    ? `ABodyBuilder2 / NanoBodyBuilder2 · ${availableModels.length} model(s)`
    : isHaddock
      ? "Antibody–antigen complex · top cluster scores"
      : (activeData?.plddt as unknown as { organism?: string })?.organism;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div
        className="w-full max-w-5xl max-h-[90vh] flex flex-col rounded-2xl overflow-hidden border border-border shadow-2xl"
        style={{ background: "#0e1425" }}
      >
        <div
          className="flex items-center gap-3 px-6 py-4 border-b border-border shrink-0"
          style={{ background: "linear-gradient(90deg, #0e1425 0%, #111830 100%)" }}
        >
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center text-white"
            style={{ background: "linear-gradient(135deg, #38bdf8, #818cf8)" }}
          >
            <Atom size={16} />
          </div>
          <div>
            <div className="text-sm font-bold text-white">{headerTitle}</div>
            <div className="text-xs text-slate-500 mt-0.5">{headerSub}</div>
          </div>
          <button
            onClick={onClose}
            className="ml-auto text-slate-500 hover:text-white transition-colors p-1.5 rounded-lg hover:bg-white/5"
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 pb-6">
          {isLoading && (
            <div className="flex items-center justify-center h-48 text-slate-500 text-sm animate-pulse">
              Loading analysis…
            </div>
          )}
          {hasError && (
            <div className="text-red-400 text-sm text-center py-12">
              No analysis data found for this node.
            </div>
          )}
          {isImmuneBuilder && !isLoading && (
            <ImmuneBuilderGrid models={availableModels} />
          )}
          {isHaddock && activeData && (
            <HADDOCK3View data={activeData} />
          )}
          {!isImmuneBuilder && !isHaddock && activeData && (
            <ModelContent data={activeData} />
          )}
        </div>
      </div>
    </div>
  );
}
