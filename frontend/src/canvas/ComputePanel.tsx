import { useEffect, useRef, useState } from "react";
import { X, Play, RefreshCw, Code2, Sparkles, Loader2, RotateCcw, Info } from "lucide-react";
import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { oneDark } from "@codemirror/theme-one-dark";
import type { Edge, Node } from "reactflow";
import { useCanvasStore, type NodeData } from "./store";

const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/compute/execute`;

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
  dataset:      { label: "dataset", cls: "text-amber-400  bg-amber-950/60  border-amber-800/40"  },
  model:        { label: "model",   cls: "text-indigo-400 bg-indigo-950/60 border-indigo-800/40" },
};

interface _DatasetCol { id: string; name: string; type: string }
interface _DatasetInfo {
  name?: string;
  entry_count?: number;
  sequence_count?: number;
  columns?: _DatasetCol[];
}

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

  const [aiOpen, setAiOpen] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  // Dataset schema cache: srcId → metadata fetched from /api/datasets/{id}
  const [datasetSchemas, setDatasetSchemas] = useState<Record<string, _DatasetInfo>>({});

  useEffect(() => {
    const connectedSourceIds = [...new Set(
      edges.filter((e) => e.target === node.id).map((e) => e.source)
    )];
    for (const srcId of connectedSourceIds) {
      const srcNode = nodes.find((n) => n.id === srcId);
      const srcData = srcNode?.data as NodeData | undefined;
      if (srcData?.tool?.id !== "dataset") continue;
      const datasetId = String(srcData.params?.dataset_id ?? "");
      if (!datasetId || datasetSchemas[srcId]) continue;
      fetch(`/api/datasets/${datasetId}/`)
        .then((r) => r.ok ? r.json() : null)
        .then((ds: _DatasetInfo | null) => {
          if (ds) setDatasetSchemas((prev) => ({ ...prev, [srcId]: ds }));
        })
        .catch(() => {});
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edges, nodes, node.id]);

  // Build variable list: each var is prefixed with the source node ID.
  // For dataset nodes, enrich with schema metadata (columns, entry count).
  // e.g. ablang_1_embedding, ablang_2_embedding — always unique, always traceable.
  const incomingVars = (() => {
    const vars: { varName: string; type: string; sourceNodeName: string; description: string }[] = [];
    const connectedSourceIds = [...new Set(
      edges.filter((e) => e.target === node.id).map((e) => e.source)
    )];
    for (const srcId of connectedSourceIds) {
      const srcNode = nodes.find((n) => n.id === srcId);
      const srcTool = (srcNode?.data as NodeData | undefined)?.tool;
      if (!srcTool) continue;

      // Resolve dataset schema: prefer runtime output, fall back to pre-fetched
      const runtimeInfo = runNodeOutputs[srcId]?.info as _DatasetInfo | undefined;
      const dsInfo: _DatasetInfo | undefined =
        srcTool.id === "dataset" ? (runtimeInfo ?? datasetSchemas[srcId]) : undefined;

      for (const port of srcTool.outputs) {
        let description = "";
        if (srcTool.id === "dataset" && dsInfo) {
          const colStr = dsInfo.columns?.map((c) => `${c.name} (${c.type})`).join(", ");
          if (port.name === "sequences") {
            const n = dsInfo.sequence_count ?? dsInfo.entry_count;
            description = `${n ?? "?"} FASTA sequences — full data in Python, schema only to AI`;
          } else if (port.name === "info") {
            description = [
              dsInfo.name ? `"${dsInfo.name}"` : null,
              dsInfo.entry_count != null ? `${dsInfo.entry_count} entries` : null,
              colStr ? `columns: ${colStr}` : null,
            ].filter(Boolean).join(" · ");
          } else if (port.name === "labels") {
            description = `{seq_name: value} dict — ${dsInfo.entry_count ?? "?"} entries`;
          }
        }
        vars.push({
          varName: `${srcId}_${port.name}`,
          type: port.type,
          sourceNodeName: srcTool.name,
          description,
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

  async function handleAiGenerate() {
    if (!aiPrompt.trim()) return;
    setAiLoading(true);
    setAiError(null);
    try {
      const resp = await fetch("/ws/compute/generate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          prompt: aiPrompt,
          variables: incomingVars.map((v) => ({ name: v.varName, type: v.type, description: v.description })),
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail ?? "Generation failed");
      }
      const { code: generated } = await resp.json() as { code: string };
      setCode(generated);
      setAiOpen(false);
      setAiPrompt("");
    } catch (e) {
      setAiError(e instanceof Error ? e.message : String(e));
    } finally {
      setAiLoading(false);
    }
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
            <div className="flex flex-col gap-1.5">
              {incomingVars.map(({ varName, type, sourceNodeName, description }) => (
                <div
                  key={varName}
                  title={`from ${sourceNodeName}`}
                  className="flex flex-col gap-0.5"
                >
                  <span className="inline-flex items-center gap-1.5 pl-2 pr-1.5 py-0.5 rounded-md
                    bg-indigo-950/60 border border-indigo-700/40 cursor-default w-fit">
                    <span className="text-xs font-mono text-indigo-300">{varName}</span>
                    <TypeBadge type={type} />
                  </span>
                  {description && (
                    <span className="text-[10px] text-slate-500 pl-2 leading-snug">{description}</span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[11px] text-slate-600">
              Connect upstream nodes to inject their outputs as Python variables.
            </p>
          )}
        </div>

        {/* AI generate bar */}
        {aiOpen && (
          <div className="px-3 py-2.5 border-b border-border/60 bg-violet-950/20 shrink-0 space-y-2">
            <textarea
              autoFocus
              rows={2}
              className="w-full bg-canvas border border-violet-700/40 rounded-lg px-3 py-2 text-xs
                text-slate-200 placeholder-slate-600 resize-none focus:outline-none
                focus:border-violet-500/60 font-sans leading-relaxed"
              placeholder="Describe what to compute… e.g. 'average pLDDT score across all residues'"
              value={aiPrompt}
              onChange={(e) => setAiPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleAiGenerate();
                if (e.key === "Escape") { setAiOpen(false); setAiError(null); }
              }}
            />
            {aiError && (
              <p className="text-[11px] text-red-400">{aiError}</p>
            )}
            <div className="flex items-center gap-2">
              <button
                onClick={handleAiGenerate}
                disabled={aiLoading || !aiPrompt.trim()}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                  bg-violet-600 text-white hover:bg-violet-500 disabled:opacity-50
                  disabled:cursor-not-allowed transition-all"
              >
                {aiLoading
                  ? <><Loader2 size={11} className="animate-spin" /><span>Generating…</span></>
                  : <><Sparkles size={11} /><span>Generate</span></>
                }
              </button>
              <span className="text-[10px] text-slate-600">⌘↵ to generate · Esc to cancel</span>
            </div>
          </div>
        )}

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
          <button
            onClick={() => { setAiOpen((v) => !v); setAiError(null); }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
              border transition-all ${
                aiOpen
                  ? "bg-violet-700/40 text-violet-200 border-violet-600/60"
                  : "text-violet-400 border-violet-700/40 hover:bg-violet-900/30 hover:text-violet-300"
              }`}
          >
            <Sparkles size={11} />
            <span>Generate with AI</span>
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

// ── Loop End Panel ────────────────────────────────────────────────────────────

function LoopEndPanelInner({
  node,
  nodes,
  edges,
  selectNode,
  updateNodeParams,
}: {
  node: ReturnType<typeof useCanvasStore.getState>["nodes"][number];
  nodes: ReturnType<typeof useCanvasStore.getState>["nodes"];
  edges: ReturnType<typeof useCanvasStore.getState>["edges"];
  selectNode: (id: string | null) => void;
  updateNodeParams: (id: string, params: Record<string, unknown>) => void;
}) {
  const data = node.data as NodeData;
  const code = String(data.params.code ?? "");

  const [aiOpen, setAiOpen] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [infoOpen, setInfoOpen] = useState(false);

  // Build upstream variable list (same pattern as ComputePanel)
  const incomingVars = (() => {
    const vars: { varName: string; type: string; sourceNodeName: string }[] = [];
    const srcIds = [...new Set(edges.filter((e) => e.target === node.id).map((e) => e.source))];
    for (const srcId of srcIds) {
      const srcNode = nodes.find((n) => n.id === srcId);
      const srcTool = (srcNode?.data as NodeData | undefined)?.tool;
      if (!srcTool) continue;
      for (const port of srcTool.outputs) {
        vars.push({ varName: `${srcId}_${port.name}`, type: port.type, sourceNodeName: srcTool.name });
      }
    }
    return vars;
  })();

  // All variables available in the loop end scope
  const loopVars = [
    { varName: "loop_iteration", type: "int",  desc: "Current iteration index (0-based)" },
    { varName: "loop_history",   type: "json", desc: "List of dicts — one per completed iteration, each with heavy_chain, light_chain, and any scores" },
  ];

  function setCode(v: string) {
    updateNodeParams(node.id, { ...data.params, code: v });
  }

  async function handleAiGenerate() {
    if (!aiPrompt.trim()) return;
    setAiLoading(true);
    setAiError(null);
    try {
      const allVars = [
        ...incomingVars.map((v) => ({ name: v.varName, type: v.type, description: `from ${v.sourceNodeName}` })),
        ...loopVars.map((v) => ({ name: v.varName, type: v.type, description: v.desc })),
      ];
      const resp = await fetch("/ws/compute/generate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          prompt: aiPrompt + "\n\nMust assign: next_heavy_chain (str). Optionally assign next_light_chain (str). These become the inputs for the next loop iteration.",
          variables: allVars,
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail ?? "Generation failed");
      }
      const { code: generated } = await resp.json() as { code: string };
      setCode(generated);
      setAiOpen(false);
      setAiPrompt("");
    } catch (e) {
      setAiError(e instanceof Error ? e.message : String(e));
    } finally {
      setAiLoading(false);
    }
  }

  return (
    <div
      className="w-[480px] shrink-0 border-l border-border bg-surface flex flex-col overflow-hidden"
      style={{ borderTopColor: "#06b6d4", borderTopWidth: 2 }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <RotateCcw size={15} className="text-cyan-400" />
          <div>
            <div className="text-sm font-bold text-white">Loop End · Selection code</div>
            <div className="text-xs text-slate-500">Picks the next sequence for the next iteration</div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setInfoOpen((v) => !v)}
            title={infoOpen ? "Collapse parameters" : "Show parameters"}
            className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] font-semibold transition-colors ${
              infoOpen
                ? "text-cyan-300 bg-cyan-900/30 border border-cyan-700/40"
                : "text-slate-500 hover:text-cyan-400 border border-transparent hover:border-cyan-800/40"
            }`}
          >
            <Info size={11} />
            <span>{infoOpen ? "Hide" : "Params"}</span>
          </button>
          <button
            onClick={() => selectNode(null)}
            className="text-slate-500 hover:text-white transition-colors p-1 rounded hover:bg-white/5"
          >
            <X size={15} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-hidden flex flex-col min-h-0">

        {/* Collapsible info sections */}
        {infoOpen && (
          <>
            {/* How it works */}
            <div className="px-4 py-2 border-b border-border/60 shrink-0">
              <div className="text-[11px] text-slate-400 leading-relaxed space-y-1.5 pb-0.5">
                <p>
                  At the end of each iteration, this code runs in an isolated Python sandbox.
                  All upstream node outputs are injected as variables (<code className="text-cyan-300">nodeId_outputName</code>).
                </p>
                <p>
                  Your code must assign <code className="text-cyan-300">next_heavy_chain</code> — this becomes
                  the VH input to <strong>Loop Start</strong> for the next iteration.
                  The loop stops when <code className="text-cyan-300">max_iterations</code> is reached
                  or you raise <code className="text-cyan-300">StopIteration("reason")</code>.
                </p>
              </div>
            </div>

            {/* Available variables */}
            <div className="px-4 py-2.5 border-b border-border/60 shrink-0">
              <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-2">
                Available variables
              </div>

              {/* Loop-specific (always present) */}
              <div className="flex flex-col gap-1 mb-2">
                {loopVars.map(({ varName, type, desc }) => (
                  <div key={varName} className="flex items-center gap-2">
                    <span className="inline-flex items-center gap-1.5 pl-2 pr-1.5 py-0.5 rounded-md
                      bg-cyan-950/50 border border-cyan-800/40 cursor-default">
                      <span className="text-xs font-mono text-cyan-300">{varName}</span>
                      <span className="text-[9px] font-bold uppercase tracking-wide px-1 py-px rounded
                        border text-sky-400 bg-sky-950/60 border-sky-800/40">{type}</span>
                    </span>
                    <span className="text-[10px] text-slate-500">{desc}</span>
                  </div>
                ))}
              </div>

              {/* Upstream node outputs */}
              {incomingVars.length > 0 ? (
                <div className="flex flex-col gap-1">
                  <div className="text-[9px] font-bold uppercase tracking-widest text-slate-600 mb-0.5">
                    From connected nodes
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {incomingVars.map(({ varName, type, sourceNodeName }) => (
                      <span key={varName} title={`from ${sourceNodeName}`}
                        className="inline-flex items-center gap-1.5 pl-2 pr-1.5 py-0.5 rounded-md
                          bg-indigo-950/60 border border-indigo-700/40 cursor-default">
                        <span className="text-xs font-mono text-indigo-300">{varName}</span>
                        <TypeBadge type={type} />
                      </span>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-[11px] text-slate-600">
                  Connect upstream nodes to inject their outputs as variables.
                </p>
              )}
            </div>

            {/* Required outputs reminder */}
            <div className="px-4 py-2 border-b border-border/60 shrink-0">
              <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-1.5">
                Must assign
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                  <code className="text-xs font-mono text-cyan-300">next_heavy_chain</code>
                  <span className="text-[10px] text-slate-600">str — VH</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400/50" />
                  <code className="text-xs font-mono text-cyan-300/70">next_light_chain</code>
                  <span className="text-[10px] text-slate-600">str — optional VL</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-red-400/50" />
                  <code className="text-xs font-mono text-slate-500">raise StopIteration("reason")</code>
                  <span className="text-[10px] text-slate-600">early stop</span>
                </div>
              </div>
            </div>
          </>
        )}

        {/* AI generate bar */}
        {aiOpen && (
          <div className="px-3 py-2.5 border-b border-border/60 bg-cyan-950/20 shrink-0 space-y-2">
            <textarea
              autoFocus
              rows={2}
              className="w-full bg-canvas border border-cyan-700/40 rounded-lg px-3 py-2 text-xs
                text-slate-200 placeholder-slate-600 resize-none focus:outline-none
                focus:border-cyan-500/60 font-sans leading-relaxed"
              placeholder="e.g. 'pick the sequence with the lowest HADDOCK score from loop_history'"
              value={aiPrompt}
              onChange={(e) => setAiPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleAiGenerate();
                if (e.key === "Escape") { setAiOpen(false); setAiError(null); }
              }}
            />
            {aiError && <p className="text-[11px] text-red-400">{aiError}</p>}
            <div className="flex items-center gap-2">
              <button
                onClick={handleAiGenerate}
                disabled={aiLoading || !aiPrompt.trim()}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                  bg-cyan-600 text-white hover:bg-cyan-500 disabled:opacity-50
                  disabled:cursor-not-allowed transition-all"
              >
                {aiLoading
                  ? <><Loader2 size={11} className="animate-spin" /><span>Generating…</span></>
                  : <><Sparkles size={11} /><span>Generate</span></>
                }
              </button>
              <span className="text-[10px] text-slate-600">⌘↵ to generate · Esc to cancel</span>
            </div>
          </div>
        )}

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
            onClick={() => { setAiOpen((v) => !v); setAiError(null); }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
              border transition-all ${
                aiOpen
                  ? "bg-cyan-700/40 text-cyan-200 border-cyan-600/60"
                  : "text-cyan-400 border-cyan-700/40 hover:bg-cyan-900/30 hover:text-cyan-300"
              }`}
          >
            <Sparkles size={11} />
            <span>Generate with AI</span>
          </button>
          <span className="text-[10px] text-slate-600 ml-auto">
            Code runs server-side at end of each iteration
          </span>
        </div>
      </div>
    </div>
  );
}

export function LoopEndPanel() {
  const { nodes, edges, selectedNodeId, selectNode, updateNodeParams } = useCanvasStore();
  const node = nodes.find((n) => n.id === selectedNodeId);
  if (!node) return null;
  return (
    <LoopEndPanelInner
      node={node}
      nodes={nodes}
      edges={edges}
      selectNode={selectNode}
      updateNodeParams={updateNodeParams}
    />
  );
}
