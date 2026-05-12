import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FlaskConical, RotateCcw } from "lucide-react";
import { fetchRunReport } from "@/api/runs";
import type { NodeReport, NodeReportMetrics, ReportMetricValue } from "@/api/runs";

// ── Status / confidence maps ──────────────────────────────────────────────────

const RUN_STATUS_BADGE: Record<string, string> = {
  succeeded: "text-emerald-400 bg-emerald-400/10 border-emerald-400/30",
  failed:    "text-red-400 bg-red-500/10 border-red-500/30",
  running:   "text-sky-400 bg-sky-400/10 border-sky-400/30",
  queued:    "text-amber-400 bg-amber-400/10 border-amber-400/30",
  cancelled: "text-slate-500 bg-slate-500/10 border-slate-500/30",
};

const CONFIDENCE_BADGE: Record<string, string> = {
  high:    "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  medium:  "bg-amber-500/15 text-amber-400 border-amber-500/30",
  low:     "bg-red-500/15 text-red-400 border-red-500/30",
  neutral: "bg-slate-500/15 text-slate-500 border-slate-500/20",
  error:   "bg-red-900/30 text-red-400 border-red-700/40",
};

const CONFIDENCE_LABEL: Record<string, string> = {
  high:    "High",
  medium:  "Medium",
  low:     "Low",
  neutral: "—",
  error:   "Failed",
};

// Tool category → left-border color (matches canvas NodeRenderer)
const TOOL_CATEGORY: Record<string, string> = {
  immunebuilder:    "border-l-sky-400",
  esmfold:          "border-l-sky-400",
  alphafold_monomer:"border-l-sky-400",
  equifold:         "border-l-sky-400",
  haddock3:         "border-l-orange-400",
  megadock:         "border-l-orange-400",
  equidock:         "border-l-orange-400",
  gromacs_mmpbsa:   "border-l-orange-400",
  proteinmpnn:      "border-l-emerald-400",
  rfdiffusion:      "border-l-violet-400",
  superwater:       "border-l-fuchsia-400",
  biophi:           "border-l-fuchsia-400",
  sequence_input:   "border-l-amber-400",
  sequence_db:      "border-l-amber-400",
  target_input:     "border-l-amber-400",
  ablang:           "border-l-rose-400",
  abmap:            "border-l-rose-400",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function fmtValue(v: ReportMetricValue): string {
  if (v.value === null || v.value === undefined) return "—";
  const val = typeof v.value === "number"
    ? (Number.isInteger(v.value) ? String(v.value) : v.value.toFixed(v.value < 1 ? 3 : 2))
    : String(v.value);
  return v.unit ? `${val} ${v.unit}` : val;
}

// ── SkeletonCard ──────────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div className="rounded-xl border border-border bg-surface animate-pulse overflow-hidden">
      <div className="h-1 bg-slate-700/60" />
      <div className="p-4 space-y-3">
        <div className="h-3 w-1/3 bg-slate-700/60 rounded" />
        <div className="h-8 w-1/2 bg-slate-700/40 rounded" />
        <div className="grid grid-cols-2 gap-2">
          <div className="h-3 bg-slate-700/30 rounded" />
          <div className="h-3 bg-slate-700/30 rounded" />
        </div>
      </div>
    </div>
  );
}

// ── ToolCard ──────────────────────────────────────────────────────────────────

interface ToolCardProps {
  node: NodeReport;
  onOpenAnalysis: (nodeId: string) => void;
}

function ToolCard({ node, onOpenAnalysis }: ToolCardProps) {
  const borderColor = TOOL_CATEGORY[node.tool_id] ?? "border-l-slate-500";
  const m: NodeReportMetrics | null = node.metrics;
  const conf = m?.confidence ?? "neutral";
  const isSkipped = node.status === "skipped" || node.status === "pending";
  const isFailed = node.status === "failed";
  const isSucceeded = node.status === "succeeded";

  return (
    <div className={`rounded-xl border border-border bg-surface overflow-hidden
      flex flex-col border-l-4 ${borderColor}
      ${isSkipped ? "opacity-40" : ""}`}
    >
      {/* card header */}
      <div className="flex items-start justify-between px-4 pt-3 pb-1 gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-white truncate">{node.tool_name}</div>
          <div className="text-[10px] font-mono text-slate-600 mt-0.5">{node.node_id}</div>
        </div>
        <span className={`shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded border ${CONFIDENCE_BADGE[conf]}`}>
          {CONFIDENCE_LABEL[conf]}
        </span>
      </div>

      {/* primary metric */}
      <div className="px-4 py-2">
        {m?.primary ? (
          <div>
            <div className="text-2xl font-bold text-white tabular-nums leading-tight">
              {fmtValue(m.primary)}
            </div>
            <div className="text-[10px] text-slate-500 mt-0.5">{m.primary.label}</div>
          </div>
        ) : isSkipped ? (
          <div className="text-sm text-slate-600 italic">Not run</div>
        ) : isFailed ? (
          <div className="text-sm text-red-500 font-medium">Node failed</div>
        ) : (
          <div className="text-sm text-slate-600">—</div>
        )}
      </div>

      {/* secondary metrics */}
      {m && m.secondary.length > 0 && (
        <div className="px-4 pb-2 grid grid-cols-2 gap-x-4 gap-y-1">
          {m.secondary.map((s, i) => (
            <div key={i} className="flex items-baseline gap-1 min-w-0">
              <span className="text-xs font-medium text-slate-300 tabular-nums truncate">
                {s.value !== null && s.value !== undefined ? fmtValue(s) : "—"}
              </span>
              <span className="text-[10px] text-slate-600 truncate">{s.label}</span>
            </div>
          ))}
        </div>
      )}

      {/* error excerpt */}
      {isFailed && node.error_excerpt && (
        <div className="mx-4 mb-2 px-3 py-2 rounded-lg bg-red-950/40 border border-red-500/20">
          <div className="text-[10px] font-mono text-red-400 leading-relaxed line-clamp-3">
            {node.error_excerpt}
          </div>
        </div>
      )}

      {/* footer */}
      {isSucceeded && (
        <div className="mt-auto border-t border-border px-4 py-2 bg-canvas">
          <button
            onClick={() => onOpenAnalysis(node.node_id)}
            className="flex items-center gap-1.5 text-xs font-medium text-indigo-400
              hover:text-indigo-300 transition-colors"
          >
            <FlaskConical size={11} />
            View Full Analysis
          </button>
        </div>
      )}
    </div>
  );
}

// ── RunReport ─────────────────────────────────────────────────────────────────

interface RunReportProps {
  runId: string;
  onBack: () => void;
  onOpenAnalysis: (runId: string, nodeId: string) => void;
  onRerun: (runId: string) => void;
}

export function RunReport({ runId, onBack, onOpenAnalysis, onRerun }: RunReportProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["report", runId],
    queryFn: () => fetchRunReport(runId),
  });

  const succeeded = data?.nodes.filter((n) => n.status === "succeeded").length ?? 0;
  const failed    = data?.nodes.filter((n) => n.status === "failed").length ?? 0;
  const total     = data?.nodes.length ?? 0;

  return (
    <div className="flex flex-col h-screen bg-canvas overflow-hidden">
      {/* top bar */}
      <div className="h-12 border-b border-border shrink-0 flex items-center px-4 gap-3"
        style={{ background: "linear-gradient(90deg, #0e1425 0%, #111830 100%)" }}
      >
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={14} />
          Back
        </button>
        <div className="h-4 w-px bg-border" />

        {data ? (
          <>
            <span className="text-sm font-semibold text-white truncate">{data.pipeline_name}</span>
            <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border ${RUN_STATUS_BADGE[data.status] ?? ""}`}>
              {data.status.toUpperCase()}
            </span>
            <span className="text-[11px] font-mono text-slate-600">{runId.slice(0, 12)}…</span>
          </>
        ) : (
          <span className="text-sm text-slate-600 animate-pulse">Loading…</span>
        )}

        <div className="flex-1" />

        {data && (
          <>
            <span className="text-xs text-slate-500">{fmtDate(data.created_at)}</span>
            <button
              onClick={() => onRerun(runId)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                text-indigo-300 bg-indigo-500/10 border border-indigo-500/30
                hover:bg-indigo-500/20 transition-colors"
            >
              <RotateCcw size={11} />
              Rerun
            </button>
          </>
        )}
      </div>

      {/* summary strip */}
      {data && (
        <div className="shrink-0 border-b border-border bg-surface px-6 py-2 flex items-center gap-6 text-xs">
          <span className="text-emerald-400 font-semibold">{succeeded} succeeded</span>
          {failed > 0 && <span className="text-red-400 font-semibold">{failed} failed</span>}
          <span className="text-slate-600">{total} nodes total</span>
        </div>
      )}

      {/* content */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading && (
          <div className="max-w-6xl mx-auto grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
          </div>
        )}

        {data && (
          <div className="max-w-6xl mx-auto grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.nodes.map((node) => (
              <ToolCard
                key={node.node_id}
                node={node}
                onOpenAnalysis={(nodeId) => onOpenAnalysis(runId, nodeId)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
