import { useRef, useState } from "react";
import { Canvas } from "./canvas/Canvas";
import { ParamPanel } from "./canvas/ParamPanel";
import { Palette } from "./palette/Palette";
import { PipelineBar } from "./pipelines/PipelineBar";
import { RunPanel } from "./runs/RunPanel";
import { AnalysisPanel } from "./analysis/AnalysisPanel";
import { Playground } from "./playground/Playground";
import { ResultsPage } from "./results/ResultsPage";
import { submitRun } from "./api/runs";
import { useCanvasStore } from "./canvas/store";

export default function App() {
  const [pipelineName, setPipelineName] = useState("Untitled pipeline");
  const pipelineId = useRef(crypto.randomUUID()).current;
  const [runId, setRunId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [analysis, setAnalysis] = useState<{ runId: string; nodeId: string } | null>(null);
  const [page, setPage] = useState<"canvas" | "playground" | "results">("canvas");

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
    return <ResultsPage onBack={() => setPage("canvas")} />;
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-canvas">
      <PipelineBar
        name={pipelineName}
        onNameChange={setPipelineName}
        onRun={handleRun}
        running={running}
        pipelineId={pipelineId}
        onOpenPlayground={() => setPage("playground")}
        onOpenResults={() => setPage("results")}
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
              onClose={() => setRunId(null)}
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
