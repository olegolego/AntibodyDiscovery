import { useCallback, useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type NodeTypes,
  type EdgeTypes,
  type Node,
  type Edge,
  BackgroundVariant,
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import { LayerNode } from "./LayerNode";
import { useDNNStore } from "./store";
import type { ShapeMap } from "./shapeInference";
import { shapeLabel, isShapeError } from "./shapeInference";
import { LAYER_BY_TYPE } from "./layers";

// Bezier edge with shape tensor label at midpoint — Netron style
function ShapeEdge({
  id, sourceX, sourceY, targetX, targetY,
  sourcePosition, targetPosition,
  data,
}: EdgeProps & { data?: { label?: string; hasError?: boolean } }) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition,
    targetX, targetY, targetPosition,
  });
  const label    = data?.label    ?? "";
  const hasError = data?.hasError ?? false;

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: hasError ? "#ef4444" : "#2d3a4f",
          strokeWidth: 1.5,
          strokeDasharray: hasError ? "5 3" : undefined,
        }}
        markerEnd={hasError ? undefined : "url(#netron-arrow)"}
      />
      {label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: "none",
            }}
            className={`text-[8px] font-mono px-1 py-[2px] rounded border ${
              hasError
                ? "bg-[#1a0a0a] border-red-900/60 text-red-400"
                : "bg-[#0d1117] border-[#21293a] text-slate-500"
            }`}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

interface DNNCanvasProps {
  shapeMap: ShapeMap;
  onDrop?: (e: React.DragEvent) => void;
  onDragOver?: (e: React.DragEvent) => void;
}

const NODE_TYPES: NodeTypes  = { layerNode: LayerNode };
const EDGE_TYPES: EdgeTypes  = { shapeEdge: ShapeEdge };

export function DNNCanvas({ shapeMap, onDrop, onDragOver }: DNNCanvasProps) {
  const {
    nodes: rawNodes, edges: rawEdges,
    onNodesChange, onEdgesChange, onConnect, selectNode,
  } = useDNNStore();

  // Inject shapeMap into every node's data so LayerNode can render shapes live
  const nodes = useMemo(
    () => rawNodes.map((n) => ({ ...n, data: { ...n.data, shapeMap } })),
    [rawNodes, shapeMap],
  );

  // Annotate each edge with the tensor shape flowing out of its source node
  const edges = useMemo(
    () => rawEdges.map((e) => {
      const srcInfo  = shapeMap.get(e.source);
      const outShape = srcInfo?.outputShape;
      const hasError = outShape ? isShapeError(outShape) : false;
      const label    = outShape
        ? isShapeError(outShape) ? "err" : shapeLabel(outShape as number[])
        : "";
      return { ...e, type: "shapeEdge", data: { label, hasError } };
    }),
    [rawEdges, shapeMap],
  );

  const handleNodeClick  = useCallback((_: React.MouseEvent, node: Node) => selectNode(node.id),  [selectNode]);
  const handlePaneClick  = useCallback(() => selectNode(null), [selectNode]);

  return (
    <div
      className="flex-1 relative overflow-hidden"
      style={{ background: "#080b10" }}
      onDrop={onDrop}
      onDragOver={onDragOver}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges as Edge[]}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        deleteKeyCode={["Backspace", "Delete"]}
        fitView
        fitViewOptions={{ padding: 0.35 }}
        minZoom={0.15}
        maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
        connectionLineStyle={{ stroke: "#3b4f6b", strokeWidth: 1.5 }}
      >
        {/* Arrow marker for directed edges */}
        <svg style={{ position: "absolute", width: 0, height: 0 }}>
          <defs>
            <marker
              id="netron-arrow"
              markerWidth="6" markerHeight="6"
              refX="5" refY="3"
              orient="auto"
            >
              <path d="M0,0 L0,6 L6,3 z" fill="#2d3a4f" />
            </marker>
          </defs>
        </svg>

        <Background
          variant={BackgroundVariant.Lines}
          gap={32}
          size={0.5}
          color="#0f1620"
        />
        <Controls
          className="!bg-[#0d1117] !border-[#21293a]
            [&_button]:!bg-[#0d1117] [&_button]:!border-[#21293a]
            [&_button]:!text-slate-500 [&_button:hover]:!text-white"
        />
        <MiniMap
          nodeColor={(n) => {
            const nd = n.data as { layerType?: string };
            return LAYER_BY_TYPE.get(nd.layerType ?? "")?.color ?? "#374151";
          }}
          style={{ background: "#0d1117", border: "1px solid #21293a" }}
          maskColor="rgba(4,6,10,0.7)"
        />
      </ReactFlow>

      {rawNodes.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="text-center space-y-1">
            <div className="text-[13px] text-slate-600 font-medium">
              Drag layers onto the canvas
            </div>
            <div className="text-[11px] text-slate-700">
              Connect top → bottom to build the graph
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
