import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Canvas } from "./canvas/Canvas";
import { ParamPanel } from "./canvas/ParamPanel";
import { Palette } from "./palette/Palette";
import { PipelineBar } from "./pipelines/PipelineBar";
import { RunPanel } from "./runs/RunPanel";
import { RunsPage } from "./runs/RunsPage";
import { RunReport } from "./runs/RunReport";
import { AnalysisPanel } from "./analysis/AnalysisPanel";
import { MLAnalysisPage } from "./analysis/MLAnalysisPage";
import { Playground } from "./playground/Playground";
import { WorkshopPage } from "./workshop/WorkshopPage";
import { ResultsPage } from "./results/ResultsPage";
import { DatasetPage } from "./datasets/DatasetPage";
import { TerminalPage } from "./terminal/TerminalPage";
import { DNNDesignerPage } from "./dnn_designer/DNNDesignerPage";
import { RLDesignerPage } from "./rl_designer/RLDesignerPage";
// three.js is heavy — lazy-load the MD Ground page so it ships as its own chunk.
const MDGroundPage = lazy(() => import("./md_ground/MDGroundPage").then((m) => ({ default: m.MDGroundPage })));
import { submitRun, getRun } from "./api/runs";
import { getLoopRun, type LoopRun } from "./api/loopRuns";
import { useCanvasStore } from "./canvas/store";
import { useTools } from "./api/tools";
import { randomUUID } from "./utils";
import type { Pipeline, Run } from "./types";
import type { ArchitectureSpec } from "./dnn_designer/store";
import type { RLSpec } from "./rl_designer/store";
import type { DNNContext } from "./canvas/ParamPanel";

const RUN_KEY = "pdp_last_run_id";
const PIPELINE_ID_KEY = "pdp_pipeline_id";

export default function App() {
  const [pipelineName, setPipelineName] = useState(
    () => localStorage.getItem("pdp_pipeline_name") ?? "Untitled pipeline"
  );
  const [pipelineId, setPipelineId] = useState(() => {
    const stored = localStorage.getItem(PIPELINE_ID_KEY);
    if (stored) return stored;
    const fresh = randomUUID();
    localStorage.setItem(PIPELINE_ID_KEY, fresh);
    return fresh;
  });
  const [runId, setRunId] = useState<string | null>(() => localStorage.getItem(RUN_KEY));
  const [running, setRunning] = useState(false);
  const [loopRunId, setLoopRunId] = useState<string | null>(null);
  const [loopRunning, setLoopRunning] = useState(false);
  const [loopData, setLoopData] = useState<LoopRun | null>(null);
  const [analysis, setAnalysis] = useState<{ runId: string; nodeId: string } | null>(null);
  const [page, setPage] = useState<"canvas" | "playground" | "workshop" | "results" | "library" | "terminal" | "runs" | "report" | "dnn_designer" | "ml_analysis" | "rl_designer" | "md_ground">("canvas");
  const [dnnDesignerNodeId, setDnnDesignerNodeId] = useState<string | null>(null);
  const [dnnDesignerSpec, setDnnDesignerSpec] = useState<ArchitectureSpec | null>(null);
  const [dnnDesignerContext, setDnnDesignerContext] = useState<DNNContext | null>(null);
  const [rlDesignerNodeId, setRLDesignerNodeId] = useState<string | null>(null);
  const [rlDesignerSpec, setRLDesignerSpec] = useState<RLSpec | null>(null);
  // Callback for when DNN designer is opened from within RL designer (policy network)
  const [rlDNNSaveCallback, setRLDNNSaveCallback] = useState<((arch: ArchitectureSpec) => void) | null>(null);
  const [reportRunId, setReportRunId] = useState<string | null>(null);

  const toPipeline = useCanvasStore((s) => s.toPipeline);
  const loadPipeline = useCanvasStore((s) => s.loadPipeline);
  const selectedNodeId = useCanvasStore((s) => s.selectedNodeId);
  const clearRunStatuses = useCanvasStore((s) => s.clearRunStatuses);
  const updateNodeParams = useCanvasStore((s) => s.updateNodeParams);
  const nodes = useCanvasStore((s) => s.nodes);
  const { data: tools } = useTools();
  const _didSyncPipeline = useRef(false);

  // On startup, reload canvas from the DB copy of the current pipeline so that
  // any server-side fixes (e.g. corrected edges) are reflected immediately,
  // rather than serving the potentially stale localStorage-persisted canvas.
  // Retries every 2 s until the backend is reachable.
  useEffect(() => {
    if (_didSyncPipeline.current || !tools?.length || !pipelineId) return;
    let cancelled = false;
    async function trySync() {
      while (!cancelled) {
        try {
          const r = await fetch("/api/pipelines/");
          if (!r.ok) throw new Error("not ok");
          const pipelines: Pipeline[] = await r.json();
          const saved = pipelines.find((p) => p.id === pipelineId);
          if (saved) {
            loadPipeline(saved, tools!);
            setPipelineName(saved.name ?? "Untitled pipeline");
          }
          _didSyncPipeline.current = true;
          return;
        } catch {
          await new Promise((res) => setTimeout(res, 2000));
        }
      }
    }
    trySync();
    return () => { cancelled = true; };
  }, [tools, pipelineId]);

  async function handleRun() {
    setRunning(true);
    clearRunStatuses();
    // Cancel any in-progress run or loop before starting fresh
    if (loopRunId) {
      (loopData?.run_ids ?? [runId].filter(Boolean)).forEach((id) =>
        fetch(`/api/runs/${id}/cancel/`, { method: "POST" }).catch(() => {})
      );
      setLoopRunId(null);
      setLoopData(null);
      setLoopRunning(false);
    }
    if (runId && !loopRunId) {
      fetch(`/api/runs/${runId}/cancel/`, { method: "POST" }).catch(() => {});
      setRunId(null);
      localStorage.removeItem(RUN_KEY);
    }
    try {
      const pipeline = { ...toPipeline(pipelineName), id: pipelineId };
      const run = await submitRun(pipeline);
      setRunId(run.id);
      localStorage.setItem(RUN_KEY, run.id);
      // If the pipeline has a Loop node the backend auto-creates a loop campaign
      if (run.loop_id) {
        setLoopRunId(run.loop_id);
        setLoopRunning(true);
      }
    } catch (err) {
      console.error("Failed to submit run:", err);
    } finally {
      setRunning(false);
    }
  }

  // Poll loop status and keep runId in sync with the current iteration's run
  useEffect(() => {
    if (!loopRunId || !loopRunning) return;
    const id = setInterval(async () => {
      try {
        const loop = await getLoopRun(loopRunId);
        setLoopData(loop);
        // Show the latest iteration's run on the canvas
        if (loop.run_ids.length > 0) {
          const latestRunId = loop.run_ids[loop.run_ids.length - 1];
          if (latestRunId !== runId) {
            setRunId(latestRunId);
            localStorage.setItem(RUN_KEY, latestRunId);
          }
        }
        if (loop.status !== "running") {
          setLoopRunning(false);
          clearInterval(id);
        }
      } catch {
        // ignore transient errors
      }
    }, 2000);
    return () => clearInterval(id);
  }, [loopRunId, loopRunning]);

  // Open a run with full context: load its pipeline onto the canvas, re-sync from
  // the DB, and — if the run belongs to a loop campaign — restore the loop panel so
  // every iteration is visible (with this run selected). Shared by the Runs page and
  // the Results page so a result always reopens the real pipeline it ran through,
  // showing all iterations (not just the single one that produced the result).
  function openRun(run: Run) {
    const snapshot = run.pipeline_snapshot as unknown as Pipeline;
    const targetPipelineId = snapshot.id ?? run.pipeline_id;
    loadPipeline(snapshot, tools ?? []);
    setPipelineName(snapshot.name ?? "Untitled pipeline");
    setPipelineId(targetPipelineId);
    localStorage.setItem("pdp_pipeline_name", snapshot.name ?? "Untitled pipeline");
    localStorage.setItem(PIPELINE_ID_KEY, targetPipelineId);
    // Re-sync canvas from DB so any corrections (e.g. fixed edges) override the
    // potentially stale snapshot baked into the run record.
    fetch("/api/pipelines/")
      .then((r) => r.json())
      .then((pipelines: Pipeline[]) => {
        const saved = pipelines.find((p) => p.id === targetPipelineId);
        if (saved && tools?.length) {
          loadPipeline(saved, tools);
          setPipelineName(saved.name ?? "Untitled pipeline");
        }
      })
      .catch(() => {});
    setRunId(run.id);
    localStorage.setItem(RUN_KEY, run.id);
    // If this run belongs to a loop campaign, restore the loop panel so all
    // iterations show (with this run/iteration selected).
    if (run.loop_id) {
      setLoopRunId(run.loop_id);
      setLoopRunning(run.status === "running");
      getLoopRun(run.loop_id).then(setLoopData).catch(() => {});
    } else {
      setLoopRunId(null);
      setLoopRunning(false);
      setLoopData(null);
    }
    setPage("canvas");
  }

  // Same as openRun but starting from just a run id (the Results page only knows the
  // run id a given structure/docking/design result was produced in).
  async function openRunById(rid: string) {
    try {
      openRun(await getRun(rid));
    } catch (err) {
      console.error("Failed to open run", rid, err);
      setRunId(rid);
      localStorage.setItem(RUN_KEY, rid);
      setPage("canvas");
    }
  }

  if (page === "report" && reportRunId) {
    return (
      <RunReport
        runId={reportRunId}
        onBack={() => setPage("runs")}
        onOpenAnalysis={(rId, nId) => {
          setPage("canvas");
          setRunId(rId);
          localStorage.setItem(RUN_KEY, rId);
          setAnalysis({ runId: rId, nodeId: nId });
        }}
        onRerun={(id) => {
          setReportRunId(null);
          setPage("canvas");
          setRunId(id);
          localStorage.setItem(RUN_KEY, id);
        }}
      />
    );
  }

  if (page === "dnn_designer" && dnnDesignerNodeId) {
    return (
      <DNNDesignerPage
        nodeId={dnnDesignerNodeId}
        initialSpec={dnnDesignerSpec}
        context={dnnDesignerContext ?? undefined}
        onBack={() => {
          // If opened from RL designer, go back there instead of canvas
          if (rlDNNSaveCallback) {
            setRLDNNSaveCallback(null);
            setPage("rl_designer");
          } else {
            setPage("canvas");
          }
        }}
        onSave={(nId, spec) => {
          if (rlDNNSaveCallback) {
            // Save the policy network into RL store and go back to rl_designer
            rlDNNSaveCallback(spec);
            setRLDNNSaveCallback(null);
            setPage("rl_designer");
          } else {
            updateNodeParams(nId, {
              ...(nodes.find((n) => n.id === nId)?.data as { params: Record<string, unknown> })?.params ?? {},
              architecture_spec: spec,
            });
            setPage("canvas");
          }
        }}
      />
    );
  }

  if (page === "rl_designer" && rlDesignerNodeId) {
    return (
      <RLDesignerPage
        nodeId={rlDesignerNodeId}
        initialSpec={rlDesignerSpec}
        onBack={() => setPage("canvas")}
        onSave={(nId, spec) => {
          updateNodeParams(nId, {
            ...(nodes.find((n) => n.id === nId)?.data as { params: Record<string, unknown> })?.params ?? {},
            rl_spec: spec,
          });
          setPage("canvas");
        }}
        onOpenDNNDesigner={(archSpec, saveCallback) => {
          setDnnDesignerNodeId(rlDesignerNodeId);
          setDnnDesignerSpec(archSpec);
          setDnnDesignerContext(null);
          setRLDNNSaveCallback(() => saveCallback);
          setPage("dnn_designer");
        }}
      />
    );
  }

  // When returning from DNN designer that was opened from within RL designer,
  // handle the save and go back to rl_designer page.
  // (This is managed by the onSave callback in the dnn_designer branch above,
  //  which uses rlDNNSaveCallback if present.)

  if (page === "runs") {
    return (
      <RunsPage
        onBack={() => setPage("canvas")}
        onOpenRun={(run: Run) => openRun(run)}
        onViewReport={(id) => {
          setReportRunId(id);
          setPage("report");
        }}
      />
    );
  }

  if (page === "playground") {
    return <Playground onBack={() => setPage("canvas")} />;
  }

  if (page === "workshop") {
    return (
      <WorkshopPage
        onBack={() => setPage("canvas")}
        onGoToCanvas={() => setPage("canvas")}
      />
    );
  }

  if (page === "results") {
    return (
      <ResultsPage
        onBack={() => setPage("canvas")}
        onOpenRun={(id) => openRunById(id)}
      />
    );
  }

  if (page === "library") {
    return <DatasetPage onBack={() => setPage("canvas")} />;
  }

  if (page === "terminal") {
    return <TerminalPage onBack={() => setPage("canvas")} />;
  }

  if (page === "ml_analysis") {
    return <MLAnalysisPage onBack={() => setPage("canvas")} />;
  }

  if (page === "md_ground") {
    return (
      <Suspense fallback={<div className="h-screen flex items-center justify-center text-slate-500 bg-canvas">Loading MD Ground…</div>}>
        <MDGroundPage onBack={() => setPage("canvas")} />
      </Suspense>
    );
  }

return (
    <div className="flex flex-col h-screen overflow-hidden bg-canvas">
      <PipelineBar
        name={pipelineName}
        onNameChange={(n) => { setPipelineName(n); localStorage.setItem("pdp_pipeline_name", n); }}
        onRun={handleRun}
        running={running}
        loopRunning={loopRunning}
        pipelineId={pipelineId}
        onOpenPlayground={() => setPage("playground")}
        onOpenWorkshop={() => setPage("workshop")}
        onOpenResults={() => setPage("results")}
        onOpenLibrary={() => setPage("library")}
        onOpenTerminal={() => setPage("terminal")}
        onOpenRuns={() => setPage("runs")}
        onOpenMLAnalysis={() => setPage("ml_analysis")}
        onOpenMDGround={() => setPage("md_ground")}
        onNewPipeline={() => { setRunId(null); localStorage.removeItem("pdp_last_run_id"); }}
        onPipelineIdChange={(id) => {
          setPipelineId(id);
          localStorage.setItem(PIPELINE_ID_KEY, id);
        }}
      />

      <div className="flex flex-1 overflow-hidden relative">
        <Palette />

        <div className="flex-1 relative overflow-hidden">
          <Canvas onNodeClick={() => {}} />
        </div>

        {selectedNodeId && (
          <ParamPanel
            onOpenDNNDesigner={(nId, spec, ctx) => {
              setDnnDesignerNodeId(nId);
              setDnnDesignerSpec(spec);
              setDnnDesignerContext(ctx);
              setPage("dnn_designer");
            }}
            onOpenRLDesigner={(nId, spec) => {
              setRLDesignerNodeId(nId);
              setRLDesignerSpec(spec);
              setPage("rl_designer");
            }}
          />
        )}

        {(runId || loopRunId) && (
          <div className="w-[26rem] shrink-0 border-l border-border bg-surface overflow-hidden flex flex-col">
            <RunPanel
              runId={runId}
              loopRunId={loopRunId}
              loopData={loopData}
              onSelectIteration={(id) => { setRunId(id); localStorage.setItem(RUN_KEY, id); }}
              onClose={() => { setRunId(null); setLoopRunId(null); setLoopData(null); setLoopRunning(false); localStorage.removeItem(RUN_KEY); }}
              onOpenAnalysis={(rId, nId) => setAnalysis({ runId: rId, nodeId: nId })}
              onViewReport={(id) => { setReportRunId(id); setPage("report"); }}
              onContinueLoop={() => setLoopRunning(true)}
            />
          </div>
        )}
      </div>

      {analysis && (
        <AnalysisPanel
          runId={analysis.runId}
          nodeId={analysis.nodeId}
          onClose={() => setAnalysis(null)}
        />
      )}
    </div>
  );
}
