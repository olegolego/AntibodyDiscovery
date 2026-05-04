import { X, Atom, BarChart2, Grid3x3, Info } from "lucide-react";
import { useQuery, useQueries } from "@tanstack/react-query";
import { fetchNodeAnalysis, type NodeAnalysis } from "@/api/analysis";
import { StructureViewer } from "./StructureViewer";
import { PLDDTChart } from "./PLDDTChart";
import { PAEHeatmap } from "./PAEHeatmap";
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
              <div className="border border-border rounded-xl overflow-hidden" style={{ height: 420 }}>
                <StructureViewer pdbText={data.structure} />
              </div>
            )}
          </div>
        )}

        {tab === "structure" && (
          <div className="border border-border rounded-xl overflow-hidden" style={{ height: 640 }}>
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

// ── ImmuneBuilder: confidence chart (RMSD → confidence) ─────────────────────

function rmsdToConfidence(rmsd: number[]): number[] {
  // Map per-residue RMSD (Å) to 0–100 confidence: 0Å→100, 1Å→50, 2Å→0
  return rmsd.map((v) => Math.max(0, Math.min(100, 100 - v * 50)));
}

import {
  CartesianGrid, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

function IbConfidenceChart({ rmsd }: { rmsd: number[] }) {
  const confidence = rmsdToConfidence(rmsd);
  const step = confidence.length > 500 ? Math.ceil(confidence.length / 500) : 1;
  const data = confidence
    .filter((_, i) => i % step === 0)
    .map((v, i) => ({ res: i * step + 1, conf: parseFloat(v.toFixed(1)) }));

  function confColor(v: number) {
    if (v >= 85) return "#38bdf8";
    if (v >= 60) return "#34d399";
    if (v >= 40) return "#fbbf24";
    return "#f87171";
  }

  const CustomDot = (props: { cx?: number; cy?: number; payload?: { conf: number } }) => {
    const { cx = 0, cy = 0, payload } = props;
    if (!payload) return null;
    return <circle cx={cx} cy={cy} r={2} fill={confColor(payload.conf)} />;
  };

  return (
    <ResponsiveContainer width="100%" height={140}>
      <LineChart data={data} margin={{ top: 4, right: 8, bottom: 16, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e2d54" />
        <XAxis dataKey="res" tick={{ fill: "#64748b", fontSize: 9 }}
          label={{ value: "Residue", position: "insideBottom", offset: -4, fill: "#64748b", fontSize: 10 }} />
        <YAxis domain={[0, 100]} tick={{ fill: "#64748b", fontSize: 9 }} width={28} />
        <Tooltip
          contentStyle={{ background: "#0e1425", border: "1px solid #1e2d54", borderRadius: 6, fontSize: 11 }}
          labelStyle={{ color: "#94a3b8" }}
          itemStyle={{ color: "#e2e8f0" }}
          formatter={(v) => [`${Number(v).toFixed(1)}`, "Confidence"]}
          labelFormatter={(l) => `Residue ${l}`}
        />
        <ReferenceLine y={85} stroke="#38bdf8" strokeDasharray="4 2" strokeOpacity={0.4} />
        <ReferenceLine y={60} stroke="#34d399" strokeDasharray="4 2" strokeOpacity={0.4} />
        <Line type="monotone" dataKey="conf" stroke="#a78bfa" strokeWidth={1.5}
          dot={<CustomDot />} activeDot={{ r: 4 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── ImmuneBuilder: 2×2 structure grid + per-model confidence ─────────────────

function ImmuneBuilderGrid({ models }: { models: Array<{ index: number; data: NodeAnalysis | undefined | null }> }) {
  const rmsd = (
    models.find((m) => m.data)?.data?.plddt as unknown as { per_residue_rmsd?: number[] } | null
  )?.per_residue_rmsd ?? [];

  return (
    <div className="pt-4 flex flex-col gap-4">
      {/* 2-column structure grid — model label is an overlay inside the viewer */}
      <div className="grid grid-cols-2 gap-4">
        {models.map((m) => (
          <div key={m.index} className="relative border border-border rounded-xl overflow-hidden" style={{ height: 420 }}>
            {m.data?.structure
              ? <StructureViewer pdbText={m.data.structure} />
              : <div className="flex items-center justify-center h-full text-slate-500 text-xs">No structure</div>
            }
            {/* Model badge — top-left overlay, doesn't interfere with the toolbar */}
            <div className="absolute top-2 left-2 z-20 px-2 py-0.5 rounded-md
              bg-black/60 backdrop-blur-sm border border-violet-500/30
              text-[10px] font-semibold text-violet-300 pointer-events-none">
              Model {m.index + 1}
            </div>
          </div>
        ))}
      </div>
      {/* Confidence chart shown once below the grid */}
      {rmsd.length > 0 && (
        <div className="border border-border rounded-xl p-3">
          <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-2">
            Per-Residue Confidence (all models)
          </div>
          <IbConfidenceChart rmsd={rmsd} />
          <div className="flex items-center gap-3 mt-1 text-[10px] text-slate-600 px-1">
            <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-sky-400 inline-block" />≥ 85 very high</span>
            <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-emerald-400 inline-block" />≥ 60 confident</span>
            <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-red-400 inline-block" />&lt; 40 uncertain</span>
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
        <div className="border border-border rounded-xl overflow-hidden" style={{ height: 600 }}>
          {data.structure
            ? <StructureViewer pdbText={data.structure} />
            : <div className="flex items-center justify-center h-full text-slate-500 text-sm">No structure</div>
          }
        </div>
      </div>
    </div>
  );
}

// ── EquiDock: docked complex viewer + metadata table ─────────────────────────

const EQUIDOCK_METRICS: { key: string; label: string; hint: string; format?: (v: unknown) => string }[] = [
  { key: "ligand_residues",        label: "Ligand residues",       hint: "number of antibody residues docked" },
  { key: "translation_magnitude_A",label: "Translation",           hint: "Å",   format: (v) => `${Number(v).toFixed(2)} Å` },
  { key: "dataset",                label: "Model checkpoint",       hint: "dips = 8-layer general · db5 = 5-layer Ab/Ag" },
  { key: "remove_clashes",         label: "Clash removal",         hint: "gradient-descent post-processing", format: (v) => v ? "enabled" : "disabled" },
];

function EquiDockView({ data }: { data: NodeAnalysis }) {
  const meta = data.plddt as unknown as Record<string, unknown> | null;

  function downloadPdb() {
    if (!data.structure) return;
    const blob = new Blob([data.structure], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "equidock_complex.pdb";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="pt-4 flex flex-col gap-5">
      {/* Metadata table */}
      {meta && Object.keys(meta).length > 0 && (
        <div className="border border-border rounded-xl overflow-hidden">
          <div className="px-4 py-2.5 border-b border-border bg-surface2 flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-widest text-slate-500">
              Docking Summary
            </span>
            <span className="text-[10px] text-orange-400 font-semibold uppercase tracking-wider">
              EquiDock · SE(3)-equivariant
            </span>
          </div>
          <table className="w-full text-xs">
            <tbody>
              {EQUIDOCK_METRICS.map(({ key, label, hint, format }) => {
                const val = meta[key];
                if (val === undefined || val === null) return null;
                return (
                  <tr key={key} className="border-b border-border/50 hover:bg-white/[0.02]">
                    <td className="px-4 py-2.5 text-slate-400 font-medium w-44">{label}</td>
                    <td className="px-4 py-2.5 font-mono text-white font-semibold">
                      {format ? format(val) : String(val)}
                    </td>
                    <td className="px-4 py-2.5 text-slate-600 text-[11px]">{hint}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Stat cards */}
      {meta && (
        <div className="grid grid-cols-3 gap-3">
          <StatCard
            label="Ligand Residues"
            value={meta.ligand_residues != null ? String(meta.ligand_residues) : "—"}
            sub="antibody residues"
          />
          <StatCard
            label="Translation"
            value={meta.translation_magnitude_A != null ? `${Number(meta.translation_magnitude_A).toFixed(1)} Å` : "—"}
            sub="rigid body shift"
          />
          <StatCard
            label="Checkpoint"
            value={meta.dataset ? String(meta.dataset).toUpperCase() : "—"}
            sub={meta.dataset === "dips" ? "8-layer · general" : "5-layer · Ab/Ag"}
          />
        </div>
      )}

      {/* Download + complex viewer */}
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold uppercase tracking-widest text-slate-500">
          Docked Complex
        </span>
        {data.structure && (
          <button
            onClick={downloadPdb}
            className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors font-medium px-3 py-1 rounded-lg border border-indigo-500/30 hover:border-indigo-400/50 hover:bg-indigo-500/10"
          >
            Download PDB
          </button>
        )}
      </div>
      <div className="border border-border rounded-xl overflow-hidden" style={{ height: 600 }}>
        {data.structure ? (
          <StructureViewer pdbText={data.structure} />
        ) : (
          <div className="flex items-center justify-center h-full text-slate-500 text-sm">
            No complex structure available
          </div>
        )}
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
  const isEquiDock      = toolId === "equidock";

  const availableModels = modelQueries
    .map((q, i) => ({ index: i, data: q.data }))
    .filter((m) => m.data != null);

  const activeData = isImmuneBuilder ? null : singleQuery.data ?? null;

  const isLoading = isImmuneBuilder
    ? modelQueries.every((q) => q.isLoading)
    : singleQuery.isLoading;
  const hasError = !isLoading && !isImmuneBuilder && activeData == null && !availableModels.length && !isEquiDock;

  const headerTitle = isImmuneBuilder
    ? "ImmuneBuilder — Structure Predictions"
    : isHaddock
      ? "HADDOCK3 — Docking Results"
      : isEquiDock
        ? "EquiDock — Rigid Docking"
        : (activeData?.plddt as unknown as { gene?: string })?.gene
          ? `${(activeData?.plddt as unknown as { gene: string }).gene} — AlphaFold Analysis`
          : "Structure Analysis";

  const headerSub = isImmuneBuilder
    ? `ABodyBuilder2 / NanoBodyBuilder2 · ${availableModels.length} model(s)`
    : isHaddock
      ? "Antibody–antigen complex · top cluster scores"
      : isEquiDock
        ? "SE(3)-equivariant neural docking · ICLR 2022"
        : (activeData?.plddt as unknown as { organism?: string })?.organism;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div
        className="w-full max-w-5xl max-h-[94vh] flex flex-col rounded-2xl overflow-hidden border border-border shadow-2xl"
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
          {isEquiDock && activeData && (
            <EquiDockView data={activeData} />
          )}
          {!isImmuneBuilder && !isHaddock && !isEquiDock && activeData && (
            <ModelContent data={activeData} />
          )}
        </div>
      </div>
    </div>
  );
}
