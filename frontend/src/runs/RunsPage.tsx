import { useEffect, useState } from "react";
import {
  ArrowLeft, ChevronDown, ChevronRight, RefreshCw, RotateCcw, ExternalLink, XCircle, Trash2, FileBarChart, Repeat,
} from "lucide-react";
import { listRuns, getRun, rerunRun, forceFailRun, deleteRun } from "@/api/runs";
import { listLoopRuns, cancelLoopRun, type LoopRunSummary } from "@/api/loopRuns";
import type { NodeRun, NodeRunStatus, Run, RunStatus } from "@/types";

// ── status style maps ─────────────────────────────────────────────────────────

const STATUS_DOT: Record<string, string> = {
  queued:    "bg-amber-400",
  running:   "bg-sky-400 animate-pulse",
  succeeded: "bg-emerald-400",
  failed:    "bg-red-500",
  cancelled: "bg-slate-500",
};

const STATUS_BADGE: Record<RunStatus, string> = {
  queued:    "text-amber-400 bg-amber-400/10 border-amber-400/30",
  running:   "text-sky-400 bg-sky-400/10 border-sky-400/30",
  succeeded: "text-emerald-400 bg-emerald-400/10 border-emerald-400/30",
  failed:    "text-red-400 bg-red-500/10 border-red-500/30",
  cancelled: "text-slate-500 bg-slate-500/10 border-slate-500/30",
};

const NODE_STATUS_COLOR: Record<NodeRunStatus, string> = {
  pending:   "text-slate-600",
  queued:    "text-amber-400",
  running:   "text-sky-400",
  succeeded: "text-emerald-400",
  failed:    "text-red-400",
  skipped:   "text-slate-600",
};

// ── helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function nodeSummary(nodes: Record<string, NodeRun>): { total: number; succeeded: number; failed: number; running: number } {
  const vals = Object.values(nodes);
  return {
    total: vals.length,
    succeeded: vals.filter((n) => n.status === "succeeded").length,
    failed:    vals.filter((n) => n.status === "failed").length,
    running:   vals.filter((n) => n.status === "running").length,
  };
}

function pipelineName(run: Run): string {
  return (run.pipeline_snapshot as Record<string, unknown>)?.name as string ?? "Untitled pipeline";
}

// ── NodeChip — compact per-node status pill ───────────────────────────────────

function NodeChip({ node }: { node: NodeRun }) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono
      bg-white/5 border border-white/5 ${NODE_STATUS_COLOR[node.status]}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${STATUS_DOT[node.status] ?? "bg-slate-700"}`} />
      {node.node_id}
    </span>
  );
}

// ── RunCard ───────────────────────────────────────────────────────────────────

interface RunCardProps {
  run: Run;
  onOpen: (runId: string) => void;
  onRerun: (runId: string) => void;
  onForceFail: (runId: string) => void;
  onDelete: (runId: string) => void;
  onViewReport: (runId: string) => void;
  rerunning: boolean;
  forceFailing: boolean;
  deleting: boolean;
}

function RunCard({ run, onOpen, onRerun, onForceFail, onDelete, onViewReport, rerunning, forceFailing, deleting }: RunCardProps) {
  const [expanded, setExpanded] = useState(run.status === "failed");
  const summary = nodeSummary(run.nodes);
  const name = pipelineName(run);
  const nodeList = Object.values(run.nodes);

  return (
    <div className={`rounded-xl border overflow-hidden transition-colors
      ${run.status === "running"
        ? "border-sky-500/30 bg-sky-500/5"
        : run.status === "failed"
        ? "border-red-500/20 bg-red-500/5"
        : "border-border bg-surface"}`}
    >
      {/* ── header row ── */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/5 transition-colors text-left"
      >
        {/* status dot */}
        <span className={`shrink-0 w-2.5 h-2.5 rounded-full ${STATUS_DOT[run.status] ?? "bg-slate-600"}`} />

        {/* pipeline name + run id */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-white truncate">{name}</span>
            <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border ${STATUS_BADGE[run.status]}`}>
              {run.status.toUpperCase()}
            </span>
            {run.loop_id && run.iteration != null && (
              <span className="text-[10px] px-1.5 py-0.5 rounded border border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-400 font-medium">
                Loop iter {run.iteration}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5 text-[11px] text-slate-500 font-mono">
            <span>{run.id.slice(0, 14)}…</span>
            <span>·</span>
            <span>
              {summary.succeeded}/{summary.total} nodes
              {summary.failed > 0 && <span className="text-red-500 ml-1">· {summary.failed} failed</span>}
              {summary.running > 0 && <span className="text-sky-400 ml-1 animate-pulse">· running</span>}
            </span>
          </div>
        </div>

        {/* date */}
        <span className="shrink-0 text-[11px] text-slate-500 hidden sm:block">{fmtDate(run.created_at)}</span>

        {/* chevron */}
        <span className="shrink-0 text-slate-600 ml-1">
          {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </span>
      </button>

      {/* ── expanded body ── */}
      {expanded && (
        <div className="border-t border-border px-4 py-3 space-y-3">

          {/* node chips */}
          <div className="flex flex-wrap gap-1.5">
            {nodeList.map((n) => <NodeChip key={n.node_id} node={n} />)}
          </div>

          {/* failed node error excerpts */}
          {nodeList.filter((n) => n.status === "failed" && n.error).map((n) => (
            <div key={n.node_id} className="rounded-lg bg-red-950/30 border border-red-500/20 px-3 py-2">
              <div className="text-[10px] text-red-400 font-mono font-semibold mb-1">{n.node_id}</div>
              <div className="text-[11px] text-red-300 font-mono leading-relaxed line-clamp-3">{n.error}</div>
            </div>
          ))}

          {/* action buttons */}
          <div className="flex items-center gap-2 pt-1 flex-wrap">
            <button
              onClick={() => onOpen(run.id)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                text-slate-300 bg-white/5 border border-border hover:bg-white/10 hover:text-white
                transition-colors"
            >
              <ExternalLink size={11} />
              Open in Canvas
            </button>
            {(run.status === "succeeded" || run.status === "failed") && (
              <button
                onClick={() => onViewReport(run.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                  text-slate-300 bg-white/5 border border-border hover:bg-white/10 hover:text-white
                  transition-colors"
              >
                <FileBarChart size={11} />
                Report
              </button>
            )}
            <button
              onClick={() => onRerun(run.id)}
              disabled={rerunning || forceFailing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                text-indigo-300 bg-indigo-500/10 border border-indigo-500/30
                hover:bg-indigo-500/20 hover:text-white transition-colors
                disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <RotateCcw size={11} className={rerunning ? "animate-spin" : ""} />
              {rerunning ? "Starting…" : "Rerun"}
            </button>
            {(run.status === "running" || run.status === "queued") && (
              <button
                onClick={() => onForceFail(run.id)}
                disabled={forceFailing}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                  text-red-400 bg-red-500/10 border border-red-500/30
                  hover:bg-red-500/20 hover:text-white transition-colors
                  disabled:opacity-40 disabled:cursor-not-allowed"
                title="Mark this stuck run as failed"
              >
                <XCircle size={11} />
                {forceFailing ? "Clearing…" : "Mark as failed"}
              </button>
            )}
            {run.status !== "running" && run.status !== "queued" && (
              <button
                onClick={() => onDelete(run.id)}
                disabled={deleting}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                  text-slate-500 hover:text-red-400 hover:bg-red-500/10 hover:border-red-500/30
                  border border-transparent transition-colors
                  disabled:opacity-40 disabled:cursor-not-allowed ml-auto"
                title="Delete this run from the database"
              >
                <Trash2 size={11} />
                {deleting ? "Deleting…" : "Delete"}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── LoopCard ──────────────────────────────────────────────────────────────────

const LOOP_STATUS_BADGE: Record<LoopRunSummary["status"], string> = {
  running:   "text-sky-400 bg-sky-400/10 border-sky-400/30",
  succeeded: "text-emerald-400 bg-emerald-400/10 border-emerald-400/30",
  failed:    "text-red-400 bg-red-500/10 border-red-500/30",
  cancelled: "text-slate-500 bg-slate-500/10 border-slate-500/30",
};

function LoopCard({ loop, onCancel, cancelling, onOpen }: {
  loop: LoopRunSummary;
  onCancel: (id: string) => void;
  cancelling: boolean;
  onOpen?: (runId: string) => void;
}) {
  const progress = Math.round((loop.run_ids_count / loop.max_iterations) * 100);
  const latestRunId = loop.latest_run_id;
  return (
    <div
      className={`rounded-xl border overflow-hidden transition-colors ${
        loop.status === "running" ? "border-sky-500/30 bg-sky-500/5" :
        loop.status === "failed"  ? "border-red-500/20 bg-red-500/5" :
        "border-border bg-surface"
      } ${latestRunId && onOpen ? "cursor-pointer hover:border-slate-600" : ""}`}
      onClick={latestRunId && onOpen ? () => onOpen(latestRunId) : undefined}
    >
      <div className="flex items-center gap-3 px-4 py-3">
        <Repeat size={14} className={loop.status === "running" ? "text-sky-400 animate-spin" : "text-slate-600"} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-slate-400 truncate">{loop.loop_id.slice(0, 12)}…</span>
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${LOOP_STATUS_BADGE[loop.status]}`}>
              {loop.status.toUpperCase()}
            </span>
          </div>
          <div className="flex items-center gap-3 mt-1.5">
            <div className="flex-1 h-1 bg-canvas rounded-full overflow-hidden">
              <div className="h-full bg-emerald-500 rounded-full transition-all" style={{ width: `${progress}%` }} />
            </div>
            <span className="text-[10px] font-mono text-slate-500 shrink-0">
              {loop.run_ids_count} / {loop.max_iterations} iter
            </span>
          </div>
          {loop.best_score != null && (
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[10px] text-slate-600">Best:</span>
              <span className="text-[10px] font-mono font-semibold text-emerald-400">
                {loop.best_score.toFixed(1)}
              </span>
              {loop.best_iter != null && (
                <span className="text-[10px] text-slate-600">@ iter {loop.best_iter}</span>
              )}
              {loop.score_count != null && loop.score_count > 1 && (
                <span className="text-[10px] text-slate-700">({loop.score_count} scored)</span>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0" onClick={e => e.stopPropagation()}>
          <span className="text-[10px] text-slate-600 font-mono">{fmtDate(loop.created_at)}</span>
          {loop.status === "running" && (
            <button
              onClick={() => onCancel(loop.loop_id)}
              disabled={cancelling}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium
                text-red-400 hover:bg-red-500/10 border border-red-500/30 transition-colors
                disabled:opacity-40 disabled:cursor-not-allowed"
              title="Cancel this loop"
            >
              <XCircle size={11} />
              {cancelling ? "Cancelling…" : "Cancel"}
            </button>
          )}
          {loop.stop_reason && (
            <span className="text-[10px] text-slate-600 italic truncate max-w-[100px]" title={loop.stop_reason}>
              {loop.stop_reason}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// ── RunsPage ──────────────────────────────────────────────────────────────────

type Tab = "runs" | "loops";

interface RunsPageProps {
  onBack: () => void;
  onOpenRun: (run: Run) => void;
  onViewReport: (runId: string) => void;
}

export function RunsPage({ onBack, onOpenRun, onViewReport }: RunsPageProps) {
  const [tab, setTab] = useState<Tab>("runs");
  const [runs, setRuns] = useState<Run[]>([]);
  const [loops, setLoops] = useState<LoopRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [rerunningId, setRerunningId] = useState<string | null>(null);
  const [forceFailingId, setForceFailingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [cancellingLoopId, setCancellingLoopId] = useState<string | null>(null);

  async function fetchRuns() {
    try {
      const data = await listRuns();
      setRuns(data);
    } catch {
      // silently ignore; stale data stays visible
    } finally {
      setLoading(false);
    }
  }

  async function fetchLoops() {
    try {
      const data = await listLoopRuns();
      setLoops(data);
    } catch {
      // endpoint may not be available on older backend
    }
  }

  // initial load
  useEffect(() => {
    fetchRuns();
    fetchLoops();
  }, []);

  // poll every 5 s only while there are active runs/loops; stop when everything is terminal
  const hasActive = runs.some((r) => r.status === "running" || r.status === "queued")
    || loops.some((l) => l.status === "running");
  useEffect(() => {
    if (!hasActive) return;
    const id = setInterval(() => { fetchRuns(); fetchLoops(); }, 5000);
    return () => clearInterval(id);
  }, [hasActive]);

  async function handleRerun(runId: string) {
    setRerunningId(runId);
    try {
      const newRun = await rerunRun(runId);
      onOpenRun(newRun);
    } catch (err) {
      console.error("Rerun failed:", err);
      setRerunningId(null);
    }
  }

  async function handleForceFail(runId: string) {
    setForceFailingId(runId);
    try {
      await forceFailRun(runId);
      await fetchRuns();
    } catch (err) {
      console.error("Force-fail failed:", err);
    } finally {
      setForceFailingId(null);
    }
  }

  async function handleDelete(runId: string) {
    setDeletingId(runId);
    try {
      await deleteRun(runId);
      setRuns((prev) => prev.filter((r) => r.id !== runId));
    } catch (err) {
      console.error("Delete failed:", err);
    } finally {
      setDeletingId(null);
    }
  }

  async function handleOpenRun(runId: string) {
    try { onOpenRun(await getRun(runId)); } catch { /* ignore */ }
  }

  async function handleCancelLoop(loopId: string) {
    setCancellingLoopId(loopId);
    try {
      await cancelLoopRun(loopId);
      await fetchLoops();
    } catch (err) {
      console.error("Cancel loop failed:", err);
    } finally {
      setCancellingLoopId(null);
    }
  }

  return (
    <div className="flex flex-col h-screen bg-canvas overflow-hidden">
      {/* top bar */}
      <div className="h-12 border-b border-border bg-surface flex items-center px-4 gap-3 shrink-0"
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
        <span className="text-sm font-semibold text-white">History</span>
        <div className="flex items-center gap-1 bg-canvas border border-border rounded-lg p-0.5">
          {(["runs", "loops"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-colors ${
                tab === t ? "bg-surface text-white shadow" : "text-slate-500 hover:text-slate-300"
              }`}
            >
              {t === "loops" && <Repeat size={10} />}
              {t === "runs" ? `Runs (${runs.length})` : `Loops (${loops.length})`}
            </button>
          ))}
        </div>
        <div className="flex-1" />
        {hasActive && (
          <span className="text-xs text-sky-400 animate-pulse font-medium">● Live</span>
        )}
        <button
          onClick={() => { fetchRuns(); fetchLoops(); }}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-slate-400
            hover:text-white hover:bg-white/5 border border-border transition-colors"
        >
          <RefreshCw size={11} />
          Refresh
        </button>
      </div>

      {/* content */}
      <div className="flex-1 overflow-y-auto p-6">
        {loading && (
          <div className="text-center pt-20 text-slate-600 text-sm animate-pulse">Loading…</div>
        )}

        {/* ── Runs tab ── */}
        {!loading && tab === "runs" && (
          <>
            {runs.length === 0 ? (
              <div className="text-center pt-20 space-y-3">
                <div className="text-slate-500 text-base font-medium">No runs yet</div>
                <div className="text-slate-600 text-sm">
                  Build a pipeline on the canvas and click Run to get started.
                </div>
                <button
                  onClick={onBack}
                  className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm
                    font-medium text-indigo-300 bg-indigo-500/10 border border-indigo-500/30
                    hover:bg-indigo-500/20 transition-colors"
                >
                  <ArrowLeft size={13} />
                  Go to Canvas
                </button>
              </div>
            ) : (
              <div className="max-w-3xl mx-auto space-y-2">
                <div className="flex items-center gap-4 pb-3 text-[11px] text-slate-500 font-mono">
                  {(["succeeded", "failed", "running", "cancelled"] as RunStatus[]).map((s) => {
                    const count = runs.filter((r) => r.status === s).length;
                    if (count === 0) return null;
                    return (
                      <span key={s} className={`font-semibold ${
                        s === "succeeded" ? "text-emerald-500" :
                        s === "failed"    ? "text-red-500" :
                        s === "running"   ? "text-sky-400" : "text-slate-600"
                      }`}>
                        {count} {s}
                      </span>
                    );
                  })}
                </div>
                {runs.map((run) => (
                  <RunCard
                    key={run.id}
                    run={run}
                    onOpen={handleOpenRun}
                    onRerun={handleRerun}
                    onForceFail={handleForceFail}
                    onDelete={handleDelete}
                    onViewReport={onViewReport}
                    rerunning={rerunningId === run.id}
                    forceFailing={forceFailingId === run.id}
                    deleting={deletingId === run.id}
                  />
                ))}
              </div>
            )}
          </>
        )}

        {/* ── Loops tab ── */}
        {!loading && tab === "loops" && (
          <div className="max-w-3xl mx-auto space-y-2">
            {loops.length === 0 ? (
              <div className="text-center pt-20 text-slate-500 text-sm">No loop campaigns found</div>
            ) : (
              <>
                <div className="flex items-center gap-4 pb-3 text-[11px] text-slate-500 font-mono">
                  {(["running", "succeeded", "failed", "cancelled"] as LoopRunSummary["status"][]).map((s) => {
                    const count = loops.filter((l) => l.status === s).length;
                    if (count === 0) return null;
                    return (
                      <span key={s} className={`font-semibold ${
                        s === "succeeded" ? "text-emerald-500" :
                        s === "failed"    ? "text-red-500" :
                        s === "running"   ? "text-sky-400" : "text-slate-600"
                      }`}>
                        {count} {s}
                      </span>
                    );
                  })}
                </div>
                {loops.map((loop) => (
                  <LoopCard
                    key={loop.loop_id}
                    loop={loop}
                    onCancel={handleCancelLoop}
                    cancelling={cancellingLoopId === loop.loop_id}
                    onOpen={handleOpenRun}
                  />
                ))}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
