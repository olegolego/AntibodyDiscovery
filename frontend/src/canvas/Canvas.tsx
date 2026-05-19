import { useCallback, useMemo } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type NodeMouseHandler,
  type Edge,
} from "reactflow";
import "reactflow/dist/style.css";

import { useCanvasStore } from "./store";
import { ToolNode, SequenceInputNode, SequenceDbNode, TargetInputNode, ImmuneBuilderNode, MegaDockNode, HADDOCK3Node, EquiDockNode, SuperWaterNode, ComputeNode, CDRMutatorNode, AbMAPNode, IgLMNode, ProGen2Node, LoopStartNode, LoopEndNode } from "./NodeRenderer";
import type { ToolSpec } from "@/types";

const NODE_TYPES = {
  toolNode: ToolNode,
  sequenceInputNode: SequenceInputNode,
  sequenceDbNode: SequenceDbNode,
  targetInputNode: TargetInputNode,
  immunebuilderNode: ImmuneBuilderNode,
  megadockNode: MegaDockNode,
  haddock3Node: HADDOCK3Node,
  equidockNode: EquiDockNode,
  superWaterNode: SuperWaterNode,
  computeNode:    ComputeNode,
  cdrMutatorNode: CDRMutatorNode,
  abmapNode:      AbMAPNode,
  iglmNode:       IgLMNode,
  progen2Node:    ProGen2Node,
  loopStartNode:  LoopStartNode,
  loopEndNode:    LoopEndNode,
};

interface CanvasProps {
  onNodeClick: (id: string) => void;
}

export function Canvas({ onNodeClick }: CanvasProps) {
  const {
    nodes, edges,
    onNodesChange, onEdgesChange, onConnect,
    addToolNode, selectNode,
  } = useCanvasStore();

  // Subscribe separately so edge styles react immediately when statuses / selection change
  const runNodeStatuses = useCanvasStore((s) => s.runNodeStatuses);
  const selectedNodeId  = useCanvasStore((s) => s.selectedNodeId);

  const styledEdges = useMemo<Edge[]>(() =>
    edges.map((e) => {
      const tgtRunning = runNodeStatuses[e.target] === "running";
      const srcRunning = runNodeStatuses[e.source] === "running";
      const srcDone    = runNodeStatuses[e.source] === "succeeded";

      const active   = tgtRunning || srcRunning;
      const done     = srcDone && !active;
      const selected = selectedNodeId !== null &&
                       (e.source === selectedNodeId || e.target === selectedNodeId);

      return {
        ...e,
        animated: active,
        style: selected ? { stroke: "#fbbf24", strokeWidth: 2.5 }
             : active   ? { stroke: "#93c5fd", strokeWidth: 3 }
             : done     ? { stroke: "#34d399", strokeWidth: 1.5 }
             :             { stroke: "#374151", strokeWidth: 1.5 },
      };
    }),
  [edges, runNodeStatuses, selectedNodeId]);

  const handleNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      selectNode(node.id);
      onNodeClick(node.id);
    },
    [selectNode, onNodeClick]
  );

  const handlePaneClick = useCallback(() => {
    selectNode(null);
  }, [selectNode]);

  const onDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const toolJson = event.dataTransfer.getData("application/tool-spec");
      if (!toolJson) return;
      const tool: ToolSpec = JSON.parse(toolJson);
      const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
      addToolNode(tool, {
        x: event.clientX - rect.left - 85,
        y: event.clientY - rect.top - 30,
      });
    },
    [addToolNode]
  );

  return (
    <div
      className="w-full h-full"
      onDrop={onDrop}
      onDragOver={(e) => e.preventDefault()}
    >
      <ReactFlow
        nodes={nodes}
        edges={styledEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        nodeTypes={NODE_TYPES}
        deleteKeyCode={["Backspace", "Delete"]}
        fitView
        fitViewOptions={{ padding: 0.2 }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} color="#2d3148" />
        <Controls className="!bottom-4 !left-4" />
        <MiniMap
          nodeColor={(n) => {
            const category = (n.data as { tool: ToolSpec })?.tool?.category;
            const colors: Record<string, string> = {
              input: "#fbbf24",
              structure_prediction: "#3b82f6",
              structure_design: "#a855f7",
              sequence_design: "#22c55e",
              sequence_embedding: "#fb7185",
              docking: "#f97316",
              molecular_dynamics: "#2dd4bf",
              toolbox: "#d946ef",
              mutagenesis: "#f59e0b",
              bioinformatics: "#2dd4bf",
              debug: "#6b7280",
            };
            return colors[category] ?? "#6b7280";
          }}
          maskColor="rgba(15,17,23,0.7)"
          className="!bg-surface !border-border"
        />
      </ReactFlow>
    </div>
  );
}
