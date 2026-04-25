import { useEffect, useRef, useState } from "react";
import { X, Play, RefreshCw, Code2 } from "lucide-react";
import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { oneDark } from "@codemirror/theme-one-dark";
import type { Edge, Node } from "reactflow";
import { useCanvasStore, type NodeData } from "./store";

const WS_URL = "ws://localhost:8000/ws/compute/execute";

type OutputLine =
  | { kind: "stdout"; text: string }
  | { kind: "result"; value: unknown }
  | { kind: "error"; text: string };

const TYPE_STYLE: Record<string, { label: string; cls: string }> = {
  pdb:          { label: "pdb",     cls: "text-orange-400 bg-orange-950/60 border-orange-800/40" },
  fasta:        { label: "fasta",   cls: "text-amber-400  bg-amber-950/60  border-amber-800/40"  },
  json:         { label: "json",    cls: "text-sky-400    bg-sky-950/60    border-sky-800/40"    },
  str:          { label: "str",     cls: "text-emerald-400 bg-emerald-950/60 border-emerald-800/40" },
  int:          { label: "int",     cls: "text-violet-400 bg-violet-950/60 border-violet-800/40" },
  float:        { label: "float",   cls: "text-violet-400 bg-violet-950/60 border-violet-800/40" },
  bool:         { label: "bool",    cls: "text-slate-400  bg-slate-800/60  border-slate-700/40"  },
  python_code:  { label: "code",    cls: "text-indigo-400 bg-indigo-950/60 border-indigo-800/40" },
};

function TypeBadge({ type }: { type: string }) {
  const style = TYPE_STYLE[type.toLowerCase()] ?? {
    label: type,
    cls: "text-slate-400 bg-slate-800/60 border-slate-700/40",
  };
  return (
    <span className={`text-[9px] font-bold uppercase tracking-wide px-1 py-px rounded
      border leading-4 ${style.cls}`}>
      {style.label}
    </span>
  );
}

function ResultValue({ value }: { value: unknown }) {
  if (value === null || value === undefined)
    return <span className="text-slate-500 italic">None</span>;
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <pre className="text-xs font-mono text-emerald-300 whitespace-pre-wrap break-all leading-relaxed max-h-48 overflow-y-auto">
      {text}
    </pre>
  );
}

// ── Inner component (hooks always run) ───────────────────────────────────────

function ComputePanelInner({
  node,
  nodes,
  edges,
  runNodeOutputs,
  selectNode,
  updateNodeParams,
}: {
  node: Node;
  nodes: Node[];
  edges: Edge[];
  runNodeOutputs: Record<string, Record<string, unknown>>;
  selectNode: (id: string | null) => void;
  updateNodeParams: (id: string, params: Record<string, unknown>) => void;
}) {
  const data = node.data as NodeData;
  const code = String(
    data.params.code ??
      "# upstream outputs are available as variables\n# assign your result to `result`\nresult = None\n"
  );

  const [output, setOutput] = useState<OutputLine[]>([]);
  const [running, setRunning] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const outputEndRef = useRef<HTMLDivElement>(null);

  // Build variable list: each var is prefixed with the source node ID.
  // e.g. ablang_1_embedding, ablang_2_embedding — always unique, always traceable.
  const incomingVars = (() => {
    const vars: { varName: string; type: string; sourceNodeName: string }[] = [];
    const connectedSourceIds = [...new Set(
      edges.filter((e) => e.target === node.id).map((e) => e.source)
    )];
    for (const srcId of connectedSourceIds) {
      const srcNode = nodes.find((n) => n.id === srcId);
      const srcTool = (srcNode?.data as NodeData | undefined)?.tool;
      if (!srcTool) continue;
      for (const port of srcTool.outputs) {
        vars.push({
          varName: `${srcId}_${port.name}`,
          type: port.type,
          sourceNodeName: srcTool.name,
        });
      }
    }
    return vars;
  })();

  function buildInjectedInputs(): Record<string, unknown> {
    const result: Record<string, unknown> = {};
    const connectedSourceIds = [...new Set(
      edges.filter((e) => e.target === node.id).map((e) => e.source)
    )];
    for (const srcId of connectedSourceIds) {
      const srcOutputs = runNodeOutputs[srcId] ?? {};
      for (const [k, v] of Object.entries(srcOutputs)) {
        if (v !== undefined && v !== null) result[`${srcId}_${k}`] = v;
      }
    }
    return result;
  }

  useEffect(() => {
    outputEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [output]);

  function setCode(newCode: string) {
    updateNodeParams(node.id, { ...data.params, code: newCode });
  }

  function handleRun() {
    if (running) return;
    setOutput([]);
    setRunning(true);

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ code, inputs: buildInjectedInputs() }));
    };

    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data as string);
      if (msg.type === "stdout") {
        setOutput((prev) => [...prev, { kind: "stdout", text: msg.text as string }]);
      } else if (msg.type === "done") {
        if (msg.error) {
          setOutput((prev) => [...prev, { kind: "error", text: msg.error as string }]);
        } else {
          setOutput((prev) => [...prev, { kind: "result", value: msg.result }]);
        }
        setRunning(false);
        ws.close();
      } else if (msg.type === "error") {
        setOutput((prev) => [...prev, { kind: "error", text: msg.message as string }]);
        setRunning(false);
        ws.close();
      }
    };

    ws.onerror = () => {
      setOutput((prev) => [...prev, { kind: "error", text: "WebSocket connection failed" }]);
      setRunning(false);
    };

    ws.onclose = () => setRunning(false);
  }

  function handleStop() {
    wsRef.current?.close();
    setRunning(false);
  }

  const nodeResult = runNodeOutputs[node.id]?.result;
  const injected = buildInjectedInputs();
  const missingLiveData =
    incomingVars.length > 0 &&
    incomingVars.some(({ varName }) => injected[varName] === undefined);

  return (
    <div
      className="w-[480px] shrink-0 border-l border-border bg-surface flex flex-col overflow-hidden"
      style={{ borderTopColor: "#818cf8", borderTopWidth: 2 }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <Code2 size={15} className="text-indigo-400" />
          <div>
            <div className="text-sm font-bold text-white">Compute · Python</div>
            <div className="text-xs text-slate-500">Write Python to process upstream outputs</div>
          </div>
        </div>
        <button
          onClick={() => selectNode(null)}
          className="text-slate-500 hover:text-white transition-colors p-1 rounded hover:bg-white/5"
        >
          <X size={15} />
        </button>
      </div>

      <div className="flex-1 overflow-hidden flex flex-col">
        {/* Available variables */}
        <div className="px-4 py-2.5 border-b border-border/60 shrink-0">
          <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-1.5">
            Available variables
          </div>
          {incomingVars.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {incomingVars.map(({ varName, type, sourceNodeName }) => (
                <span
                  key={varName}
                  title={`from ${sourceNodeName}`}
                  className="inline-flex items-center gap-1.5 pl-2 pr-1.5 py-0.5 rounded-md
                    bg-indigo-950/60 border border-indigo-700/40 cursor-default"
                >
                  <span className="text-xs font-mono text-indigo-300">{varName}</span>
                  <TypeBadge type={type} />
                </span>
              ))}
            </div>
          ) : (
            <p className="text-[11px] text-slate-600">
              Connect upstream nodes to inject their outputs as Python variables.
            </p>
          )}
        </div>

        {/* Code editor */}
        <div className="flex-1 overflow-hidden min-h-0">
          <CodeMirror
            value={code}
            onChange={setCode}
            theme={oneDark}
            extensions={[python()]}
            height="100%"
            style={{ fontSize: 12, height: "100%" }}
            basicSetup={{
              lineNumbers: true,
              foldGutter: false,
              highlightActiveLine: true,
              autocompletion: true,
            }}
          />
        </div>

        {/* Toolbar */}
        <div className="px-3 py-2 border-t border-border flex items-center gap-2 shrink-0">
          <button
            onClick={running ? handleStop : handleRun}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
              transition-all ${
                running
                  ? "bg-red-900/50 text-red-300 border border-red-700/50 hover:bg-red-900/80"
                  : "bg-indigo-600 text-white hover:bg-indigo-500 shadow-lg shadow-indigo-900/40"
              }`}
          >
            {running ? (
              <>
                <RefreshCw size={11} className="animate-spin" />
                <span>Stop</span>
              </>
            ) : (
              <>
                <Play size={11} fill="white" />
                <span>Run</span>
              </>
            )}
          </button>
          {output.length > 0 && !running && (
            <button
              onClick={() => setOutput([])}
              className="text-xs text-slate-600 hover:text-slate-400 transition-colors"
            >
              Clear
            </button>
          )}
          {missingLiveData && (
            <span className="text-[10px] text-amber-500/80 ml-auto">
              Run the pipeline first to inject live data
            </span>
          )}
        </div>

        {/* Output panel */}
        {(output.length > 0 || nodeResult !== undefined) && (
          <div
            className="border-t border-border max-h-48 overflow-y-auto p-3 shrink-0 font-mono text-xs"
            style={{ background: "#080d1a" }}
          >
            {output.map((line, i) => (
              <div key={i}>
                {line.kind === "stdout" && (
                  <span className="text-slate-300 whitespace-pre-wrap">{line.text}</span>
                )}
                {line.kind === "result" && (
                  <div className="mt-1">
                    <span className="text-slate-500">result = </span>
                    <ResultValue value={line.value} />
                  </div>
                )}
                {line.kind === "error" && (
                  <pre className="text-red-400 whitespace-pre-wrap">{line.text}</pre>
                )}
              </div>
            ))}
            {nodeResult !== undefined && output.length === 0 && (
              <div>
                <span className="text-slate-500 text-[10px] uppercase tracking-wider">
                  Last run result ·{" "}
                </span>
                <ResultValue value={nodeResult} />
              </div>
            )}
            <div ref={outputEndRef} />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Public export (null-guard) ───────────────────────────────────────────────

export function ComputePanel() {
  const { nodes, edges, selectedNodeId, selectNode, updateNodeParams, runNodeOutputs } =
    useCanvasStore();
  const node = nodes.find((n) => n.id === selectedNodeId);
  if (!node) return null;
  return (
    <ComputePanelInner
      node={node}
      nodes={nodes}
      edges={edges}
      runNodeOutputs={runNodeOutputs}
      selectNode={selectNode}
      updateNodeParams={updateNodeParams}
    />
  );
}
