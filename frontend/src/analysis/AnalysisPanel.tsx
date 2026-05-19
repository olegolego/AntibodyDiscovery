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

// ── MegaDock: score bars + complex viewer ────────────────────────────────────

function MegaDockView({ data }: { data: NodeAnalysis }) {
  const scores   = (data.top_scores ?? []) as import("@/api/analysis").MegadockScore[];
  const pdbs     = (data.complex_pdbs ?? {}) as Record<string, string>;
  const meta     = data.docking_metadata as import("@/api/analysis").MegadockMetadata | null;
  const [selected, setSelected] = useState<number>(scores[0]?.rank ?? 1);

  const pdbText = pdbs[String(selected)] ?? data.structure ?? null;
  const maxScore = scores[0]?.score ?? 1;

  function downloadPdb() {
    if (!pdbText) return;
    const blob = new Blob([pdbText], { type: "text/plain" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url;
    a.download = `megadock_rank${selected}.pdb`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="pt-4 flex flex-col gap-5">
      {/* Stats row */}
      {meta && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard
            label="Best Score"
            value={meta.best_score?.toFixed(1) ?? "—"}
            sub="MEGADOCK convolution score"
          />
          <StatCard
            label="Poses"
            value={String(scores.length)}
            sub="top-ranked"
          />
          <StatCard
            label="Rotations"
            value={meta.rotational_sampling?.toLocaleString() ?? "—"}
            sub="sampled"
          />
          <StatCard
            label="Time"
            value={meta.elapsed_seconds != null ? `${meta.elapsed_seconds.toFixed(1)} s` : "—"}
            sub="wall time"
          />
        </div>
      )}

      {/* Score bars */}
      {scores.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-[11px] font-bold uppercase tracking-widest text-slate-500">
            Docking Scores — click to view
          </span>
          <div className="flex flex-col gap-1.5">
            {scores.map(({ rank, score }) => {
              const pct   = (score / maxScore) * 100;
              const isTop = rank === 1;
              const isSel = rank === selected;
              return (
                <button
                  key={rank}
                  onClick={() => setSelected(rank)}
                  className={`flex items-center gap-3 px-3 py-2 rounded-xl border transition-all text-left
                    ${isSel
                      ? "border-indigo-500/60 bg-indigo-500/10"
                      : "border-border hover:border-slate-500 hover:bg-white/[0.03]"
                    }`}
                >
                  <span className={`w-14 text-xs font-mono shrink-0 ${isTop ? "text-emerald-400" : "text-slate-500"}`}>
                    #{rank}
                  </span>
                  <div className="flex-1 h-2 bg-canvas rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{
                        width: `${pct}%`,
                        background: isTop
                          ? "linear-gradient(90deg,#34d399,#6ee7b7)"
                          : isSel
                          ? "linear-gradient(90deg,#818cf8,#a78bfa)"
                          : "linear-gradient(90deg,#475569,#64748b)",
                      }}
                    />
                  </div>
                  <span className={`w-20 text-xs font-mono text-right shrink-0 ${isTop ? "text-emerald-300" : "text-slate-400"}`}>
                    {score.toFixed(2)}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* 3-D viewer */}
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold uppercase tracking-widest text-slate-500">
          Rank #{selected} Complex
        </span>
        {pdbText && (
          <button
            onClick={downloadPdb}
            className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors font-medium
              px-3 py-1 rounded-lg border border-indigo-500/30 hover:border-indigo-400/50
              hover:bg-indigo-500/10"
          >
            Download PDB
          </button>
        )}
      </div>
      <div className="border border-border rounded-xl overflow-hidden" style={{ height: 560 }}>
        {pdbText ? (
          <StructureViewer key={selected} pdbText={pdbText} />
        ) : (
          <div className="flex items-center justify-center h-full text-slate-500 text-sm">
            No complex structure available
          </div>
        )}
      </div>

      {/* Optional: rendered image from MEGADOCK */}
      {data.image && (
        <div className="flex flex-col gap-2">
          <span className="text-[11px] font-bold uppercase tracking-widest text-slate-500">
            Docking Preview Image
          </span>
          <img
            src={data.image}
            alt="MEGADOCK docking preview"
            className="rounded-xl border border-border w-full"
          />
        </div>
      )}
    </div>
  );
}

// ── SuperWater: hydrated structure + water count ─────────────────────────────

function SuperWaterView({ data }: { data: NodeAnalysis }) {
  const waterCount = data.water_count as unknown as { waters_placed?: number } | null;

  function downloadPdb() {
    if (!data.structure) return;
    const blob = new Blob([data.structure], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "hydrated_structure.pdb";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="pt-4 flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-3">
        <StatCard
          label="Waters Placed"
          value={waterCount?.waters_placed != null ? String(waterCount.waters_placed) : "—"}
          sub="predicted binding-site waters"
        />
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold uppercase tracking-widest text-slate-500">
          Hydrated Structure
        </span>
        {data.structure && (
          <button
            onClick={downloadPdb}
            className="text-xs text-cyan-400 hover:text-cyan-300 transition-colors font-medium px-3 py-1 rounded-lg border border-cyan-500/30 hover:border-cyan-400/50 hover:bg-cyan-500/10"
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
            No hydrated structure available
          </div>
        )}
      </div>
    </div>
  );
}

// ── GROMACS MM/GBSA: ΔG bind + energy decomposition ─────────────────────────

function GROMACSView({ data }: { data: NodeAnalysis }) {
  const dg = data.delta_g_bind;
  const decomp = data.energy_decomposition as Record<string, number> | null;
  const conv = data.md_convergence as Record<string, number | string> | null;

  const conf =
    dg == null ? "—" :
    dg <= -10 ? "Strong" :
    dg <= -5  ? "Moderate" :
    "Weak";
  const confColor =
    dg == null ? "text-slate-500" :
    dg <= -10  ? "text-emerald-400" :
    dg <= -5   ? "text-amber-400" :
    "text-red-400";

  const DECOMP_LABELS: Record<string, string> = {
    "VDWAALS":       "Van der Waals",
    "EEL":           "Electrostatics",
    "EGB":           "Polar solvation (GB)",
    "ESURF":         "Non-polar solvation",
    "DELTA VDWAALS": "ΔVdW",
    "DELTA EEL":     "ΔElectrostatics",
    "DELTA EGB":     "ΔPolar solvation",
    "DELTA ESURF":   "ΔNon-polar solvation",
    "DELTA TOTAL":   "ΔG total",
  };

  return (
    <div className="pt-4 flex flex-col gap-5">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <StatCard
          label="ΔG bind"
          value={dg != null ? `${dg.toFixed(2)} kcal/mol` : "—"}
          sub="MM/GBSA binding free energy"
        />
        <StatCard label="Binding strength" value={conf} />
        {conv && (
          <StatCard
            label="MD Convergence"
            value={conv["status"] != null ? String(conv["status"]) : "—"}
            sub="RMSD-based assessment"
          />
        )}
      </div>

      {decomp && Object.keys(decomp).length > 0 && (
        <div className="border border-border rounded-xl overflow-hidden">
          <div className="px-4 py-2.5 border-b border-border bg-surface2">
            <span className="text-[11px] font-bold uppercase tracking-widest text-slate-500">
              Energy Decomposition
            </span>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-2 text-slate-500 font-semibold">Component</th>
                <th className="text-right px-4 py-2 text-slate-500 font-semibold">kcal/mol</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(decomp).map(([key, val]) => (
                <tr key={key} className="border-b border-border/50 hover:bg-white/[0.02]">
                  <td className="px-4 py-2 text-slate-300">
                    {DECOMP_LABELS[key] ?? key}
                  </td>
                  <td className={`px-4 py-2 text-right font-mono ${
                    key.startsWith("DELTA") ? "font-bold text-white" : "text-slate-400"
                  }`}>
                    {typeof val === "number" ? val.toFixed(2) : String(val)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className={`text-xs text-center py-2 font-medium ${confColor}`}>
        {dg != null
          ? `ΔG = ${dg.toFixed(2)} kcal/mol — ${conf} binding affinity`
          : "No binding free energy data"}
      </div>
    </div>
  );
}

// ── Generic output viewer (AbLang, AbMAP, ProteinMPNN, compute, etc.) ────────

function _renderValue(v: unknown): React.ReactNode {
  if (v === null || v === undefined) return <span className="text-slate-600">—</span>;
  if (typeof v === "boolean") return <span className={v ? "text-emerald-400" : "text-red-400"}>{String(v)}</span>;
  if (typeof v === "number") return <span className="font-mono text-sky-300">{v}</span>;
  if (typeof v === "string") {
    if (v.length === 0) return <span className="text-slate-600">—</span>;
    if (v.length <= 80) return <span className="font-mono text-slate-300 break-all">{v}</span>;
    return (
      <pre className="text-xs font-mono text-slate-300 bg-canvas border border-border rounded-lg p-3 whitespace-pre-wrap break-all max-h-48 overflow-y-auto">
        {v}
      </pre>
    );
  }
  if (Array.isArray(v)) {
    if (v.length === 0) return <span className="text-slate-600">[] (empty)</span>;
    // List of strings → numbered sequence list
    if (typeof v[0] === "string") {
      return (
        <div className="flex flex-col gap-1.5">
          {v.map((s, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="text-[10px] font-mono text-indigo-400 shrink-0 mt-0.5 w-6 text-right">{i + 1}</span>
              <span className="font-mono text-xs text-slate-300 break-all">{String(s)}</span>
            </div>
          ))}
        </div>
      );
    }
    // List of numbers → summarise
    if (typeof v[0] === "number") {
      const nums = v as number[];
      const mean = nums.reduce((a, b) => a + b, 0) / nums.length;
      return (
        <span className="font-mono text-xs text-slate-400">
          [{nums.length} values · min {Math.min(...nums).toFixed(3)} · mean {mean.toFixed(3)} · max {Math.max(...nums).toFixed(3)}]
        </span>
      );
    }
    return <span className="font-mono text-xs text-slate-400">[{v.length} items]</span>;
  }
  if (typeof v === "object") {
    return (
      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <tbody>
            {Object.entries(v as Record<string, unknown>).map(([k, val]) => (
              <tr key={k} className="border-b border-border/50 hover:bg-white/[0.02]">
                <td className="px-3 py-1.5 text-slate-500 font-medium w-36 shrink-0">{k}</td>
                <td className="px-3 py-1.5">{_renderValue(val)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return <span className="font-mono text-xs text-slate-400">{String(v)}</span>;
}

function DnnMldeView({ data }: { data: NodeAnalysis }) {
  const raw = data.raw_outputs ?? {} as Record<string, unknown>;
  const metrics    = (raw.metrics    ?? {}) as Record<string, unknown>;
  const artifact   = (raw.model_artifact ?? {}) as Record<string, unknown>;
  const topSeqs    = (raw.top_sequences ?? []) as string[];
  const acqScores  = (raw.acquisition_scores ?? {}) as Record<string, number>;
  const meanPred   = (raw.mean_predictions   ?? {}) as Record<string, number>;
  const epistemic  = (raw.epistemic_uncertainty ?? {}) as Record<string, number>;
  const confUnc    = (raw.conformational_uncertainty ?? {}) as Record<string, number>;

  const scores = Object.values(acqScores).filter((v) => typeof v === "number") as number[];
  const minScore = scores.length ? Math.min(...scores) : null;
  const maxScore = scores.length ? Math.max(...scores) : null;
  const meanScore = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null;

  const nRanks     = metrics.n_ranks     as number | undefined;
  const nCommittee = metrics.n_committee as number | undefined;
  const modelType  = metrics.model_type  as string | undefined;
  const epochs     = metrics.epochs      as number | undefined;
  const rankNames  = (artifact.rank_names ?? metrics.rank_names ?? []) as string[];
  const inDim      = artifact.in_dim as number | undefined;

  return (
    <div className="pt-4 flex flex-col gap-5">
      {/* Model summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Ranks" value={String(nRanks ?? "—")} sub={rankNames.slice(0,2).join(", ")} />
        <StatCard label="Ensemble" value={String(nCommittee ?? "—")} sub="committee members" />
        <StatCard label="Embedding dim" value={inDim ? `${inDim}d` : "—"} sub={modelType ?? undefined} />
        <StatCard label="Epochs" value={String(epochs ?? "—")} sub="training" />
      </div>

      {/* Acquisition score summary */}
      {scores.length > 0 && (
        <div>
          <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-2">
            Acquisition score distribution ({scores.length} sequences)
          </div>
          <div className="grid grid-cols-3 gap-3">
            <StatCard label="Min α" value={minScore!.toFixed(2)} />
            <StatCard label="Mean α" value={meanScore!.toFixed(2)} />
            <StatCard label="Max α" value={maxScore!.toFixed(2)} />
          </div>
        </div>
      )}

      {/* Top sequences table */}
      {topSeqs.length > 0 && (
        <div>
          <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-2">
            Top {topSeqs.length} candidates
          </div>
          <div className="border border-border rounded-lg overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border bg-white/[0.02]">
                    <th className="px-3 py-2 text-left text-slate-500 font-medium w-6">#</th>
                    <th className="px-3 py-2 text-left text-slate-500 font-medium">Sequence</th>
                    <th className="px-3 py-2 text-right text-slate-500 font-medium w-20">α score</th>
                    <th className="px-3 py-2 text-right text-slate-500 font-medium w-20">μ̄ pred</th>
                    <th className="px-3 py-2 text-right text-slate-500 font-medium w-20">σ epi</th>
                    <th className="px-3 py-2 text-right text-slate-500 font-medium w-20">σ conf</th>
                  </tr>
                </thead>
                <tbody>
                  {topSeqs.slice(0, 20).map((seq, i) => (
                    <tr key={i} className="border-b border-border/50 hover:bg-white/[0.02]">
                      <td className="px-3 py-1.5 text-slate-600">{i + 1}</td>
                      <td className="px-3 py-1.5 font-mono text-slate-400 max-w-xs truncate"
                          title={seq}>{seq}</td>
                      <td className="px-3 py-1.5 text-right font-mono text-sky-300">
                        {acqScores[seq] != null ? acqScores[seq].toFixed(2) : "—"}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono text-slate-400">
                        {meanPred[seq] != null ? (meanPred[seq] as number).toFixed(2) : "—"}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono text-amber-400/70">
                        {epistemic[seq] != null ? (epistemic[seq] as number).toFixed(3) : "—"}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono text-slate-500">
                        {confUnc[seq] != null ? (confUnc[seq] as number).toFixed(3) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Model artifact summary (no raw weights) */}
      <div>
        <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-2">Model artifact</div>
        <div className="bg-canvas border border-border rounded-lg px-4 py-3 text-xs text-slate-400 font-mono">
          {nRanks} rank{nRanks !== 1 ? "s" : ""} · {nCommittee} committee member{nCommittee !== 1 ? "s" : ""}
          {inDim ? ` · ${inDim}d embeddings` : ""}
          {rankNames.length ? ` · [${rankNames.join(", ")}]` : ""}
          <span className="ml-2 text-slate-600">(weights omitted from display)</span>
        </div>
      </div>
    </div>
  );
}

function GenericOutputView({ data }: { data: NodeAnalysis }) {
  const raw = data.raw_outputs ?? {};
  const entries = Object.entries(raw).filter(([, v]) => v !== null && v !== undefined);

  if (entries.length === 0) {
    return <div className="text-slate-500 text-sm text-center py-12">No output data stored for this node.</div>;
  }

  return (
    <div className="pt-4 flex flex-col gap-4">
      {entries.map(([key, value]) => (
        <div key={key}>
          <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-1.5">
            {key.replace(/_/g, " ")}
          </div>
          {_renderValue(value)}
        </div>
      ))}
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
  const isSuperWater    = toolId === "superwater";
  const isMegaDock      = toolId === "megadock";
  const isGromacs       = toolId === "gromacs_mmpbsa";
  const isStructure     = toolId === "esmfold" || toolId === "alphafold_monomer" || toolId === "equifold";
  const isDnnMlde       = toolId === "dnn_mlde";
  const isSpecialized   = isImmuneBuilder || isHaddock || isEquiDock || isSuperWater || isMegaDock || isGromacs || isStructure || isDnnMlde;

  const availableModels = modelQueries
    .map((q, i) => ({ index: i, data: q.data }))
    .filter((m) => m.data != null);

  const activeData = isImmuneBuilder ? null : singleQuery.data ?? null;

  const isLoading = isImmuneBuilder
    ? modelQueries.every((q) => q.isLoading)
    : singleQuery.isLoading;
  const hasError = !isLoading && !isImmuneBuilder && activeData == null && !availableModels.length;

  const _TOOL_TITLES: Record<string, string> = {
    immunebuilder: "ImmuneBuilder — Structure Predictions",
    haddock3: "HADDOCK3 — Docking Results",
    equidock: "EquiDock — Rigid Docking",
    superwater: "SuperWater — Hydration Analysis",
    megadock: "MEGADOCK — Docking Results",
    gromacs_mmpbsa: "GROMACS MM/GBSA — Binding Affinity",
    esmfold: "ESMFold — Structure Prediction",
    alphafold_monomer: "AlphaFold — Structure Prediction",
    equifold: "EquiFold — Structure Prediction",
    ablang: "AbLang — Antibody Language Model",
    abmap: "AbMAP — Antibody Embeddings",
    proteinmpnn: "ProteinMPNN — Sequence Design",
    rfdiffusion: "RFdiffusion — Structure Design",
    biophi: "BioPhi — Humanization",
    sequence_input: "Sequence Input — Antibody Sequences",
    sequence_db: "Sequence Library — Entry",
    target_input: "Target Input — Antigen Structure",
    compute: "Compute — Custom Code",
    dnn_mlde: "DNN-MLDE — Active Learning Results",
  };
  const headerTitle = _TOOL_TITLES[toolId ?? ""] ?? (toolId ? `${toolId} — Outputs` : "Node Outputs");

  const _TOOL_SUBS: Record<string, string> = {
    immunebuilder: `ABodyBuilder2 / NanoBodyBuilder2 · ${availableModels.length} model(s)`,
    haddock3: "Antibody–antigen complex · top cluster scores",
    equidock: "SE(3)-equivariant neural docking · ICLR 2022",
    superwater: "ML-predicted explicit water placement · binding-site hydration",
    megadock: "FFT-based rigid protein-protein docking · rotational search",
    gromacs_mmpbsa: "Molecular dynamics · MM/GBSA free energy perturbation",
    ablang: "Per-residue antibody language model embeddings",
    abmap: "Antibody structure-aware embeddings",
    proteinmpnn: "Inverse-folding sequence design",
    compute: "User-defined Python computation",
    dnn_mlde: "RCC acquisition · committee ensemble · top candidate ranking",
  };
  const _afGene = (activeData?.plddt as unknown as { gene?: string } | null)?.gene;
  const _afOrg  = (activeData?.plddt as unknown as { organism?: string } | null)?.organism;
  const headerSub = _TOOL_SUBS[toolId ?? ""]
    ?? (_afGene ? `${_afGene} — AlphaFold Analysis` : _afOrg ?? undefined);

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
          {isSuperWater && activeData && (
            <SuperWaterView data={activeData} />
          )}
          {isMegaDock && activeData && (
            <MegaDockView data={activeData} />
          )}
          {isGromacs && activeData && (
            <GROMACSView data={activeData} />
          )}
          {isStructure && activeData && (
            <ModelContent data={activeData} />
          )}
          {isDnnMlde && activeData && (
            <DnnMldeView data={activeData} />
          )}
          {!isSpecialized && activeData && (
            <GenericOutputView data={activeData} />
          )}
        </div>
      </div>
    </div>
  );
}
