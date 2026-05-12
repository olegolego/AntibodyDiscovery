import { useState } from "react";
import { Canvas } from "./canvas/Canvas";
import { ParamPanel } from "./canvas/ParamPanel";
import { Palette } from "./palette/Palette";
import { PipelineBar } from "./pipelines/PipelineBar";
import { RunPanel } from "./runs/RunPanel";
import { RunsPage } from "./runs/RunsPage";
import { RunReport } from "./runs/RunReport";
import { AnalysisPanel } from "./analysis/AnalysisPanel";
import { Playground } from "./playground/Playground";
import { ResultsPage } from "./results/ResultsPage";
import { DatasetPage } from "./datasets/DatasetPage";
import { TerminalPage } from "./terminal/TerminalPage";
import { submitRun } from "./api/runs";
import { useCanvasStore } from "./canvas/store";
import { useTools } from "./api/tools";
import { randomUUID } from "./utils";
import type { Pipeline, Run } from "./types";

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
  const [analysis, setAnalysis] = useState<{ runId: string; nodeId: string } | null>(null);
  const [page, setPage] = useState<"canvas" | "playground" | "results" | "library" | "terminal" | "runs" | "report">("canvas");
  const [reportRunId, setReportRunId] = useState<string | null>(null);

  const toPipeline = useCanvasStore((s) => s.toPipeline);
  const loadPipeline = useCanvasStore((s) => s.loadPipeline);
  const selectedNodeId = useCanvasStore((s) => s.selectedNodeId);
  const clearRunStatuses = useCanvasStore((s) => s.clearRunStatuses);
  const { data: tools } = useTools();

  async function handleRun() {
    setRunning(true);
    clearRunStatuses();
    // Cancel any active run before starting a new one. Idempotent on finished runs.
    if (runId) {
      fetch(`/api/runs/${runId}/cancel/`, { method: "POST" }).catch(() => {});
      setRunId(null);
      localStorage.removeItem(RUN_KEY);
    }
    try {
      const pipeline = { ...toPipeline(pipelineName), id: pipelineId };
      const run = await submitRun(pipeline);
      setRunId(run.id);
      localStorage.setItem(RUN_KEY, run.id);
    } catch (err) {
      console.error("Failed to submit run:", err);
    } finally {
      setRunning(false);
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

  if (page === "runs") {
    return (
      <RunsPage
        onBack={() => setPage("canvas")}
        onOpenRun={(run: Run) => {
          const snapshot = run.pipeline_snapshot as unknown as Pipeline;
          loadPipeline(snapshot, tools ?? []);
          setPipelineName(snapshot.name ?? "Untitled pipeline");
          setPipelineId(snapshot.id ?? run.pipeline_id);
          localStorage.setItem("pdp_pipeline_name", snapshot.name ?? "Untitled pipeline");
          localStorage.setItem(PIPELINE_ID_KEY, snapshot.id ?? run.pipeline_id);
          setRunId(run.id);
          localStorage.setItem(RUN_KEY, run.id);
          setPage("canvas");
        }}
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

  if (page === "results") {
    return (
      <ResultsPage
        onBack={() => setPage("canvas")}
        onOpenRun={(id) => {
          setRunId(id);
          localStorage.setItem(RUN_KEY, id);
          setPage("canvas");
        }}
      />
    );
  }

  if (page === "library") {
    return <DatasetPage onBack={() => setPage("canvas")} />;
  }

  if (page === "terminal") {
    return <TerminalPage onBack={() => setPage("canvas")} />;
  }

return (
    <div className="flex flex-col h-screen overflow-hidden bg-canvas">
      <PipelineBar
        name={pipelineName}
        onNameChange={(n) => { setPipelineName(n); localStorage.setItem("pdp_pipeline_name", n); }}
        onRun={handleRun}
        running={running}
        pipelineId={pipelineId}
        onOpenPlayground={() => setPage("playground")}
        onOpenResults={() => setPage("results")}
        onOpenLibrary={() => setPage("library")}
        onOpenTerminal={() => setPage("terminal")}
        onOpenRuns={() => setPage("runs")}
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

        {selectedNodeId && <ParamPanel />}

        {runId && (
          <div className="w-80 shrink-0 border-l border-border bg-surface overflow-hidden flex flex-col">
            <RunPanel
              runId={runId}
              onClose={() => { setRunId(null); localStorage.removeItem(RUN_KEY); }}
              onOpenAnalysis={(rId, nId) => setAnalysis({ runId: rId, nodeId: nId })}
              onViewReport={(id) => { setReportRunId(id); setPage("report"); }}
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
