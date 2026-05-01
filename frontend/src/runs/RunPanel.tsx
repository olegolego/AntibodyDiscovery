import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, X, FlaskConical, Square } from "lucide-react";
import { useRunWebSocket } from "@/hooks/useRunWebSocket";
import { useCanvasStore } from "@/canvas/store";
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
    nodeRun.outputs?.structure !== undefined ||
    nodeRun.outputs?.plddt !== undefined ||
    nodeRun.outputs?.structure_1 !== undefined ||
    nodeRun.outputs?.best_complex !== undefined
  );

  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <button
        onClick={() => hasDetail && setOpen((v) => !v)}
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

  const runningEntry = Object.entries(run.nodes).find(([, nr]) => nr.status === "running");
  const [runningId, runningNode] = runningEntry ?? [null, null];
  const isRunning = !!runningEntry;

  // Last node that has finished with logs/error — used as context when running node is silent
  const lastFinishedEntry = [...Object.entries(run.nodes)]
    .reverse()
    .find(([id, nr]) => id !== runningId && (nr.logs.length > 0 || nr.error));
  const [lastId, lastNode] = lastFinishedEntry ?? [null, null];

  // Running node lines (may be empty at startup)
  const runningLines: LogLine[] = runningNode
    ? [
        ...runningNode.logs.map((text) => ({ nodeId: runningId!, text, kind: "log" as const })),
        ...(runningNode.error ? [{ nodeId: runningId!, text: runningNode.error, kind: "error" as const }] : []),
      ]
    : [];

  // When the running node hasn't logged anything yet, show last finished node's output as context
  const showContext = isRunning && runningLines.length === 0 && !!lastNode;

  const displayLines: LogLine[] = showContext
    ? [
        ...lastNode!.logs.map((text) => ({ nodeId: lastId!, text, kind: "log" as const })),
        ...(lastNode!.error ? [{ nodeId: lastId!, text: lastNode!.error, kind: "error" as const }] : []),
      ]
    : runningLines.length > 0
    ? runningLines
    : !isRunning
    ? (lastNode
        ? [
            ...lastNode.logs.map((text) => ({ nodeId: lastId!, text, kind: "log" as const })),
            ...(lastNode.error ? [{ nodeId: lastId!, text: lastNode.error, kind: "error" as const }] : []),
          ]
        : [])
    : [];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [displayLines.length]);

  const titleId = showContext ? lastId : (runningId ?? lastId);

  return (
    <div className="shrink-0 border-t border-white/10 bg-[#0d0d0d] rounded-b-xl overflow-hidden">
      {/* Terminal title bar */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-white/5 bg-[#111]">
        <span className="text-[10px] text-slate-500 font-mono select-none">
          {titleId ?? "pipeline log"}
          {showContext && (
            <span className="text-slate-700 ml-1">(context)</span>
          )}
        </span>
        <div className="flex items-center gap-2">
          {isRunning && runningId && (
            <span className="text-[9px] text-sky-400 font-mono">
              {runningId} <span className="animate-pulse">●</span>
            </span>
          )}
        </div>
      </div>

      {/* Log body */}
      <div className="h-44 overflow-y-auto px-3 py-2 space-y-0.5 font-mono text-xs">
        {displayLines.length === 0 && !isRunning && (
          <span className="text-slate-700">no output yet</span>
        )}
        {displayLines.length === 0 && isRunning && !showContext && (
          <span className="text-slate-600 animate-pulse">starting {runningId}…</span>
        )}
        {displayLines.map((line, i) => (
          <div key={i} className={`leading-5 ${showContext ? "opacity-40" : ""}`}>
            <span className={line.kind === "error" ? "text-red-400" : "text-emerald-300"}>
              {line.text}
            </span>
          </div>
        ))}
        {isRunning && runningLines.length > 0 && (
          <div className="text-slate-500 animate-pulse leading-5">▊</div>
        )}
        {showContext && (
          <div className="mt-1 text-[10px] text-sky-600 animate-pulse">
            ↑ last output · waiting for {runningId}…
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

interface RunPanelProps {
  runId: string;
  onClose: () => void;
  onOpenAnalysis: (runId: string, nodeId: string) => void;
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

export function RunPanel({ runId, onClose, onOpenAnalysis }: RunPanelProps) {
  const [run, setRun] = useState<Run | null>(null);
  const setRunNodeStatuses = useCanvasStore((s) => s.setRunNodeStatuses);
  const setRunNodeOutputs = useCanvasStore((s) => s.setRunNodeOutputs);

  useEffect(() => {
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

  useRunWebSocket(runId, applyRun);

  const elapsed = useElapsed(run?.created_at, run?.status === "running" || run?.status === "queued");

  function handleClose() {
    onClose();
  }

  async function handleStop() {
    if (!runId) return;
    await fetch(`/api/runs/${runId}/cancel/`, { method: "POST" });
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <span className="text-sm font-bold text-white">Run Status</span>
        <div className="flex items-center gap-2">
          {run?.status === "running" && (
            <button
              onClick={handleStop}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium
                bg-red-950/60 border border-red-800/50 text-red-400 hover:bg-red-900/60
                hover:text-red-300 transition-colors"
            >
              <Square size={10} fill="currentColor" />
              Stop
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

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {!run && (
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
                  onAnalysis={() => onOpenAnalysis(runId, nodeRun.node_id)}
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
