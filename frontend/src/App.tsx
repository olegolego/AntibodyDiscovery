import { useState } from "react";
import { Canvas } from "./canvas/Canvas";
import { ParamPanel } from "./canvas/ParamPanel";
import { Palette } from "./palette/Palette";
import { PipelineBar } from "./pipelines/PipelineBar";
import { RunPanel } from "./runs/RunPanel";
import { AnalysisPanel } from "./analysis/AnalysisPanel";
import { Playground } from "./playground/Playground";
import { ResultsPage } from "./results/ResultsPage";
import { DatasetPage } from "./datasets/DatasetPage";
import { TerminalPage } from "./terminal/TerminalPage";
import { submitRun } from "./api/runs";
import { useCanvasStore } from "./canvas/store";
import { randomUUID } from "./utils";

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
  const [page, setPage] = useState<"canvas" | "playground" | "results" | "library" | "terminal">("canvas");

  const toPipeline = useCanvasStore((s) => s.toPipeline);
  const selectedNodeId = useCanvasStore((s) => s.selectedNodeId);
  const clearRunStatuses = useCanvasStore((s) => s.clearRunStatuses);

  async function handleRun() {
    setRunning(true);
    clearRunStatuses();
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
