import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, X, FlaskConical, Square, FileBarChart, RefreshCw, Database } from "lucide-react";
import { useRunWebSocket } from "@/hooks/useRunWebSocket";
import { useCanvasStore } from "@/canvas/store";
import { createDatasetFromRun, listDatasets } from "@/api/datasets";
import type { Dataset } from "@/api/datasets";
import type { LoopRun } from "@/api/loopRuns";
import type { NodeRun, NodeRunStatus, Run, RunStatus } from "@/types";

const STATUS_COLOR: Record<RunStatus | NodeRunStatus, string> = {
  pending:   "text-slate-500",
  queued:    "text-amber-400",
  running:   "text-sky-400",
  succeeded: "text-emerald-400",
  failed:    "text-red-400",
  cancelled: "text-slate-500",
  skipped:   "text-slate-500",
};

const STATUS_DOT: Record<string, string> = {
  queued:    "bg-amber-400",
  running:   "bg-sky-400 animate-pulse",
  succeeded: "bg-emerald-400",
  failed:    "bg-red-500",
};

const RUN_BG: Record<RunStatus, string> = {
  queued:    "border-amber-400/30 bg-amber-400/5",
  running:   "border-sky-400/30 bg-sky-400/5",
  succeeded: "border-emerald-400/30 bg-emerald-400/5",
  failed:    "border-red-500/30 bg-red-500/5",
  cancelled: "border-slate-500/30 bg-slate-500/5",
};

interface NodeRunRowProps {
  nodeRun: NodeRun;
  onAnalysis?: () => void;
}

function NodeRunRow({ nodeRun, onAnalysis }: NodeRunRowProps) {
  const [open, setOpen] = useState(nodeRun.status === "failed");
  const hasDetail = nodeRun.logs.length > 0 || nodeRun.error;
  const hasAnalysis = nodeRun.status === "succeeded" && (
    nodeRun.outputs?.structure != null ||
    nodeRun.outputs?.plddt != null ||
    nodeRun.outputs?.structure_1 != null ||
    nodeRun.outputs?.best_complex != null ||
    nodeRun.outputs?.hydrated_structure != null ||
    nodeRun.outputs?.top_scores != null ||
    nodeRun.outputs?.delta_g_bind != null
  );

  const selectNode    = useCanvasStore((s) => s.selectNode);
  const selectedNodeId = useCanvasStore((s) => s.selectedNodeId);
  const isSelected    = selectedNodeId === nodeRun.node_id;

  function handleRowClick() {
    // Toggle selection: clicking the selected node deselects it
    selectNode(isSelected ? null : nodeRun.node_id);
    if (hasDetail) setOpen((v) => !v);
  }

  return (
    <div className={`border rounded-xl overflow-hidden transition-colors
      ${isSelected ? "border-amber-400/60 bg-amber-400/5" : "border-border"}`}>
      <button
        onClick={handleRowClick}
        className="w-full flex items-center gap-2 px-3 py-2.5 hover:bg-surface2 transition-colors"
      >
        <span className={`shrink-0 w-2 h-2 rounded-full ${STATUS_DOT[nodeRun.status] ?? "bg-slate-600"}`} />
        <span className="text-xs font-mono text-slate-300 flex-1 text-left truncate">{nodeRun.node_id}</span>
        <span className={`text-xs font-medium ${STATUS_COLOR[nodeRun.status]}`}>{nodeRun.status}</span>
        {hasDetail && (
          <span className="text-slate-600 shrink-0">
            {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </span>
        )}
      </button>

      {open && (
        <div className="border-t border-border bg-canvas px-3 py-2.5 space-y-0.5 max-h-44 overflow-y-auto">
          {nodeRun.logs.map((line, i) => (
            <div key={i} className="text-xs text-slate-400 font-mono">{line}</div>
          ))}
          {nodeRun.error && (
            <div className="text-xs text-red-400 font-mono mt-1 leading-relaxed">{nodeRun.error}</div>
          )}
        </div>
      )}

      {hasAnalysis && onAnalysis && (
        <div className="border-t border-border px-3 py-2 bg-canvas">
          <button
            onClick={onAnalysis}
            className="flex items-center gap-1.5 text-xs font-medium text-indigo-400
              hover:text-indigo-300 transition-colors"
          >
            <FlaskConical size={11} />
            View Analysis
          </button>
        </div>
      )}
    </div>
  );
}

// ── Terminal log ─────────────────────────────────────────────────────────────

interface LogLine {
  nodeId: string;
  text: string;
  kind: "log" | "error";
}

function TerminalLog({ run }: { run: Run }) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  const runningEntry = Object.entries(run.nodes).find(([, nr]) => nr.status === "running");
  const [runningId] = runningEntry ?? [null, null];
  const isRunning = !!runningEntry;

  // Build a continuous stream: all completed nodes in order, then the running node last.
  // Each line is prefixed with the node id so you always know who emitted it.
  const allLines: LogLine[] = [];
  for (const [nodeId, nr] of Object.entries(run.nodes)) {
    if (nr.status === "running") continue; // append running node at the end
    for (const text of nr.logs) allLines.push({ nodeId, text, kind: "log" });
    if (nr.error) allLines.push({ nodeId, text: nr.error, kind: "error" });
  }
  if (runningEntry) {
    const [rId, rNr] = runningEntry;
    for (const text of rNr.logs) allLines.push({ nodeId: rId, text, kind: "log" });
    if (rNr.error) allLines.push({ nodeId: rId, text: rNr.error, kind: "error" });
  }

  const totalLines = allLines.length;

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [totalLines, autoScroll]);

  function handleScroll(e: React.UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setAutoScroll(atBottom);
  }

  return (
    <div className="shrink-0 border-t border-white/10 bg-[#0d0d0d] rounded-b-xl overflow-hidden">
      {/* Title bar */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-white/5 bg-[#111]">
        <span className="text-[10px] text-slate-500 font-mono select-none">pipeline log</span>
        <div className="flex items-center gap-2">
          {isRunning && runningId && (
            <span className="text-[9px] text-sky-400 font-mono">
              {runningId} <span className="animate-pulse">●</span>
            </span>
          )}
          {!autoScroll && (
            <button
              onClick={() => { setAutoScroll(true); bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }}
              className="text-[9px] text-slate-500 hover:text-slate-300 font-mono transition-colors"
            >
              ↓ tail
            </button>
          )}
        </div>
      </div>

      {/* Log body */}
      <div
        className="h-44 overflow-y-auto px-3 py-2 font-mono text-xs"
        onScroll={handleScroll}
      >
        {allLines.length === 0 && !isRunning && (
          <span className="text-slate-700">no output yet</span>
        )}
        {allLines.length === 0 && isRunning && (
          <span className="text-slate-600 animate-pulse">starting {runningId}…</span>
        )}
        {allLines.map((line, i) => {
          const isRunningNode = line.nodeId === runningId;
          return (
            <div key={i} className="leading-5 flex gap-1.5 min-w-0">
              <span className={`shrink-0 text-[10px] ${isRunningNode ? "text-sky-600" : "text-slate-600"}`}>
                {line.nodeId}
              </span>
              <span className={`break-all ${line.kind === "error" ? "text-red-400" : isRunningNode ? "text-emerald-300" : "text-slate-400"}`}>
                {line.text}
              </span>
            </div>
          );
        })}
        {isRunning && runningEntry && runningEntry[1].logs.length > 0 && (
          <div className="text-slate-600 animate-pulse leading-5 pl-1">▊</div>
        )}
        {isRunning && runningEntry && runningEntry[1].logs.length === 0 && (
          <div className="leading-5 flex gap-1.5">
            <span className="shrink-0 text-[10px] text-sky-600">{runningId}</span>
            <span className="text-slate-600 animate-pulse">running…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

interface RunPanelProps {
  runId: string | null;
  loopRunId?: string | null;
  loopData?: LoopRun | null;
  onSelectIteration?: (runId: string) => void;
  onClose: () => void;
  onOpenAnalysis: (runId: string, nodeId: string) => void;
  onViewReport?: (runId: string) => void;
}

function useElapsed(createdAt: string | undefined, active: boolean): string {
  const [elapsed, setElapsed] = useState("");
  useEffect(() => {
    if (!active || !createdAt) { setElapsed(""); return; }
    function tick() {
      const secs = Math.floor((Date.now() - new Date(createdAt!).getTime()) / 1000);
      if (secs < 60) setElapsed(`${secs}s`);
      else setElapsed(`${Math.floor(secs / 60)}m ${secs % 60}s`);
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [createdAt, active]);
  return elapsed;
}

export function RunPanel({ runId, loopRunId, loopData, onSelectIteration, onClose, onOpenAnalysis, onViewReport }: RunPanelProps) {
  const [run, setRun] = useState<Run | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const setRunNodeStatuses = useCanvasStore((s) => s.setRunNodeStatuses);
  const setRunNodeOutputs = useCanvasStore((s) => s.setRunNodeOutputs);
  const runNodeStatuses = useCanvasStore((s) => s.runNodeStatuses);

  // ── Save-to-dataset state ────────────────────────────────────────────────────
  const [showSave, setShowSave] = useState(false);
  const [saveMode, setSaveMode] = useState<"new" | "existing">("new");
  const [saveName, setSaveName] = useState("");
  const [saveTargetId, setSaveTargetId] = useState("");
  const [savingDs, setSavingDs] = useState(false);
  const [saveResult, setSaveResult] = useState<{ name: string; count: number } | null>(null);
  const [saveError, setSaveError] = useState("");
  const [existingDs, setExistingDs] = useState<Dataset[]>([]);

  useEffect(() => {
    if (!showSave) return;
    listDatasets().then(setExistingDs).catch(() => {});
  }, [showSave]);

  async function handleSaveDataset() {
    setSavingDs(true);
    setSaveError("");
    try {
      const result = await createDatasetFromRun({
        loop_run_id: loopRunId ?? null,
        run_id: !loopRunId ? (runId ?? null) : null,
        dataset_id: saveMode === "existing" ? (saveTargetId || null) : null,
        name: saveMode === "new" ? (saveName.trim() || "Dataset from run") : undefined,
      });
      setSaveResult({ name: result.name, count: result.added_count });
    } catch (err: unknown) {
      setSaveError((err as { message?: string })?.message ?? "Failed to save dataset");
    } finally {
      setSavingDs(false);
    }
  }

  useEffect(() => {
    if (!runId) return;
    fetch(`/api/runs/${runId}/`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (data) applyRun(data); })
      .catch(() => {});
  }, [runId]);

  function applyRun(updated: Run) {
    setRun(updated);
    const statuses = Object.fromEntries(
      Object.entries(updated.nodes).map(([id, nr]) => [id, nr.status])
    );
    setRunNodeStatuses(statuses);
    const outputs = Object.fromEntries(
      Object.entries(updated.nodes)
        .filter(([, nr]) => Object.keys(nr.outputs ?? {}).length > 0)
        .map(([id, nr]) => [id, nr.outputs])
    );
    setRunNodeOutputs(outputs);
  }

  useRunWebSocket(runId ?? "", applyRun);

  const elapsed = useElapsed(run?.created_at, run?.status === "running" || run?.status === "queued");

  function handleClose() {
    onClose();
  }

  function markCancelling() {
    const updated = Object.fromEntries(
      Object.entries(runNodeStatuses).map(([id, s]) => [
        id, (s === "running" || s === "queued") ? "cancelling" : s,
      ])
    ) as Record<string, NodeRunStatus>;
    setRunNodeStatuses(updated);
  }

  async function handleStop() {
    if (!runId || cancelling) return;
    setCancelling(true);
    markCancelling();
    try {
      await fetch(`/api/runs/${runId}/cancel/`, { method: "POST" });
    } finally {
      setCancelling(false);
    }
  }

  async function handleCancelLoop() {
    if (cancelling || !loopData?.run_ids.length) return;
    setCancelling(true);
    markCancelling();
    try {
      await Promise.all(
        loopData.run_ids.map((id) =>
          fetch(`/api/runs/${id}/cancel/`, { method: "POST" }).catch(() => {})
        )
      );
    } finally {
      setCancelling(false);
    }
  }

  const isLoop = !!loopRunId && !!loopData;
  const loopDone = loopData?.status !== "running";
  const canSave = isLoop
    ? loopDone && (loopData?.run_ids.length ?? 0) > 0
    : run?.status === "succeeded" || run?.status === "failed";
  const loopProgress = loopData
    ? Math.round((loopData.run_ids.length / loopData.max_iterations) * 100)
    : 0;
  const LOOP_STATUS_COLOR: Record<string, string> = {
    running:   "text-sky-400",
    succeeded: "text-emerald-400",
    failed:    "text-red-400",
    cancelled: "text-slate-500",
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <span className="text-sm font-bold text-white">
          {isLoop ? "Loop Run" : "Run Status"}
        </span>
        <div className="flex items-center gap-2">
          {!isLoop && (run?.status === "succeeded" || run?.status === "failed") && onViewReport && runId && (
            <button
              onClick={() => onViewReport(runId)}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium
                text-slate-300 bg-white/5 border border-border hover:bg-white/10 hover:text-white
                transition-colors"
            >
              <FileBarChart size={10} />
              Report
            </button>
          )}
          {canSave && (
            <button
              onClick={() => { setShowSave((v) => !v); setSaveResult(null); setSaveError(""); }}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium
                transition-colors border
                ${showSave
                  ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
                  : "text-slate-300 bg-white/5 border-border hover:bg-white/10 hover:text-white"
                }`}
            >
              <Database size={10} />
              Dataset
            </button>
          )}
          {!isLoop && run?.status === "running" && (
            <button
              onClick={handleStop}
              disabled={cancelling}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium
                bg-red-950/60 border border-red-800/50 text-red-400 hover:bg-red-900/60
                hover:text-red-300 transition-colors disabled:opacity-60"
            >
              {cancelling
                ? <RefreshCw size={10} className="animate-spin" />
                : <Square size={10} fill="currentColor" />}
              {cancelling ? "Cancelling…" : "Stop"}
            </button>
          )}
          {isLoop && !loopDone && (
            <button
              onClick={handleCancelLoop}
              disabled={cancelling}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium
                bg-red-950/60 border border-red-800/50 text-red-400 hover:bg-red-900/60
                hover:text-red-300 transition-colors disabled:opacity-60"
            >
              {cancelling
                ? <RefreshCw size={10} className="animate-spin" />
                : <Square size={10} fill="currentColor" />}
              {cancelling ? "Cancelling…" : "Cancel Loop"}
            </button>
          )}
          <button
            onClick={handleClose}
            className="text-slate-500 hover:text-white transition-colors p-1 rounded hover:bg-white/5"
          >
            <X size={15} />
          </button>
        </div>
      </div>

      {/* ── Save-to-dataset panel ── */}
      {showSave && (
        <div className="shrink-0 border-b border-border bg-[#0e1425] px-4 py-3 space-y-2.5">
          <div className="text-xs font-semibold text-white">Save to Dataset</div>

          {/* Mode toggle */}
          <div className="flex gap-1 p-0.5 bg-canvas rounded-lg w-fit">
            {(["new", "existing"] as const).map((m) => (
              <button
                key={m}
                onClick={() => { setSaveMode(m); setSaveResult(null); }}
                className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors
                  ${saveMode === m ? "bg-indigo-600 text-white" : "text-slate-500 hover:text-slate-300"}`}
              >
                {m === "new" ? "New dataset" : "Add to existing"}
              </button>
            ))}
          </div>

          {saveMode === "new" && (
            <input
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="Dataset name…"
              className="w-full bg-canvas border border-border rounded-lg px-3 py-1.5 text-sm
                text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500/60"
            />
          )}

          {saveMode === "existing" && (
            <select
              value={saveTargetId}
              onChange={(e) => setSaveTargetId(e.target.value)}
              className="w-full bg-canvas border border-border rounded-lg px-3 py-1.5 text-sm
                text-white focus:outline-none focus:border-indigo-500/60"
            >
              <option value="">Select dataset…</option>
              {existingDs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} ({d.entry_count} rows)
                </option>
              ))}
            </select>
          )}

          {saveResult && (
            <div className="text-xs text-emerald-400 font-medium">
              ✓ Added {saveResult.count} rows to "{saveResult.name}"
            </div>
          )}
          {saveError && (
            <div className="text-xs text-red-400 leading-snug">{saveError}</div>
          )}

          <div className="flex gap-2 pt-0.5">
            <button
              onClick={() => { setShowSave(false); setSaveResult(null); setSaveError(""); }}
              className="flex-1 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white
                border border-border transition-colors"
            >
              {saveResult ? "Close" : "Cancel"}
            </button>
            {!saveResult && (
              <button
                onClick={handleSaveDataset}
                disabled={savingDs || (saveMode === "existing" && !saveTargetId)}
                className="flex-1 px-3 py-1.5 rounded-lg text-xs font-semibold
                  bg-emerald-600 hover:bg-emerald-500 text-white
                  disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {savingDs ? "Saving…" : "Save"}
              </button>
            )}
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {/* ── Loop summary banner ── */}
        {isLoop && loopData && (
          <div className="rounded-xl border border-border bg-surface2 px-4 py-3 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <RefreshCw size={13} className={loopData.status === "running" ? "animate-spin text-sky-400" : "text-slate-500"} />
                <span className="text-xs font-semibold text-slate-300">
                  Iteration {Math.min(loopData.current_iteration + 1, loopData.max_iterations)} / {loopData.max_iterations}
                </span>
              </div>
              <span className={`text-xs font-bold ${LOOP_STATUS_COLOR[loopData.status] ?? "text-slate-400"}`}>
                {loopData.status.toUpperCase()}
              </span>
            </div>
            <div className="w-full h-1.5 bg-canvas rounded-full overflow-hidden">
              <div
                className="h-full bg-emerald-500 rounded-full transition-all duration-500"
                style={{ width: `${loopProgress}%` }}
              />
            </div>
          </div>
        )}

        {/* ── Score history table ── */}
        {isLoop && loopData && (loopData.score_history?.length ?? 0) > 0 && (() => {
          const history = loopData.score_history!;
          const bestScore = Math.min(...history.filter(e => e.best_score !== null).map(e => e.best_score as number));
          const showPending = loopData.status === "running";
          return (
            <div className="space-y-1.5">
              <div className="text-[10px] font-bold uppercase tracking-widest text-slate-600 px-1">Score History</div>
              <div className="rounded-xl border border-border bg-surface2 overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left px-3 py-1.5 text-[10px] text-slate-600 font-medium">Iter</th>
                      <th className="text-left px-3 py-1.5 text-[10px] text-slate-600 font-medium">CDR3</th>
                      <th className="text-right px-3 py-1.5 text-[10px] text-slate-600 font-medium">HADDOCK</th>
                      <th className="w-6" />
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((entry, i) => {
                      const prev = i > 0 ? history[i - 1].best_score : null;
                      const isBest = entry.best_score !== null && entry.best_score === bestScore;
                      const improved = prev !== null && entry.best_score !== null && entry.best_score < prev;
                      const regressed = prev !== null && entry.best_score !== null && entry.best_score > prev;
                      return (
                        <tr key={entry.iteration} className={`border-b border-border/40 last:border-0 ${isBest ? "bg-emerald-500/5" : ""}`}>
                          <td className="px-3 py-1.5 text-slate-500 font-mono">{entry.iteration}</td>
                          <td className="px-3 py-1.5 text-slate-400 font-mono truncate max-w-[80px]" title={entry.vh_prefix}>
                            {entry.vh_cdr3 ?? `…${entry.vh_prefix.slice(-14)}`}
                          </td>
                          <td
                            className={`px-3 py-1.5 text-right font-mono font-semibold ${isBest ? "text-emerald-300" : "text-emerald-500"}`}
                            title={Object.entries(entry.scores_by_rank).map(([r, v]) => `${r}: ${v.toFixed(1)}`).join("  ")}
                          >
                            {entry.best_score !== null ? entry.best_score.toFixed(1) : "—"}
                          </td>
                          <td className="px-1 py-1.5 text-right">
                            {improved && <span className="text-emerald-400 text-[10px]">↓</span>}
                            {regressed && <span className="text-red-400 text-[10px]">↑</span>}
                            {isBest && <span className="text-emerald-300 text-[9px] font-bold">★</span>}
                          </td>
                        </tr>
                      );
                    })}
                    {showPending && (
                      <tr className="border-t border-border/40">
                        <td className="px-3 py-1.5 text-slate-600 font-mono">{loopData.current_iteration}</td>
                        <td className="px-3 py-1.5 text-slate-700 font-mono italic" colSpan={2}>running…</td>
                        <td className="px-1 py-1.5">
                          <span className="inline-block w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })()}

        {/* ── Loop iteration list ── */}
        {isLoop && loopData && loopData.run_ids.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[10px] font-bold uppercase tracking-widest text-slate-600 px-1">Iterations</div>
            {loopData.run_ids.map((rid, i) => {
              const isActive = rid === runId;
              const isLast = i === loopData.run_ids.length - 1;
              const iterStatus = isLast && loopData.status === "running" ? "running" : "succeeded";
              return (
                <button
                  key={rid}
                  onClick={() => onSelectIteration?.(rid)}
                  className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs
                    border transition-colors
                    ${isActive
                      ? "border-sky-500/40 bg-sky-500/10 text-sky-300"
                      : "border-border hover:bg-surface2 text-slate-400 hover:text-slate-200"
                    }`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${STATUS_DOT[iterStatus] ?? "bg-slate-600"}`} />
                    <span className="font-mono">Iteration {i + 1}</span>
                  </div>
                  <span className="text-[10px] text-slate-600 font-mono truncate max-w-[80px]">{rid.slice(0, 8)}…</span>
                </button>
              );
            })}
          </div>
        )}

        {/* ── Divider when both loop + run are shown ── */}
        {isLoop && run && <div className="border-t border-border" />}

        {/* ── Regular run detail ── */}
        {!run && !isLoop && (
          <div className="text-xs text-slate-600 animate-pulse text-center pt-6">Connecting…</div>
        )}

        {run && (
          <>
            <div className={`flex items-center justify-between rounded-xl px-4 py-3 border ${RUN_BG[run.status]}`}>
              <span className="text-[11px] font-mono text-slate-600 truncate mr-3">
                {run.id.slice(0, 12)}…
              </span>
              <div className="flex items-center gap-2 shrink-0">
                {elapsed && (
                  <span className="text-[11px] font-mono text-slate-500">{elapsed}</span>
                )}
                <span className={`text-sm font-bold ${STATUS_COLOR[run.status]}`}>
                  {run.status.toUpperCase()}
                </span>
              </div>
            </div>

            <div className="space-y-2">
              {Object.values(run.nodes).map((nodeRun) => (
                <NodeRunRow
                  key={nodeRun.node_id}
                  nodeRun={nodeRun}
                  onAnalysis={() => runId && onOpenAnalysis(runId, nodeRun.node_id)}
                />
              ))}
            </div>
          </>
        )}
      </div>

      {run && <TerminalLog run={run} />}
    </div>
  );
}
