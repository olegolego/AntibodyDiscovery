import { useState, useMemo } from "react";
import { ArrowLeft, BookOpen, Copy, Play, Terminal as TerminalIcon } from "lucide-react";
import { useTools } from "@/api/tools";
import type { ToolSpec } from "@/types";
import { RunPanel } from "@/runs/RunPanel";
import { AnalysisPanel } from "@/analysis/AnalysisPanel";

const CATEGORY_COLOR: Record<string, string> = {
  input:                "#fbbf24",
  structure_prediction: "#38bdf8",
  structure_design:     "#a78bfa",
  sequence_design:      "#34d399",
  sequence_embedding:   "#fb7185",
  docking:              "#f97316",
  toolbox:              "#e879f9",
  compute:              "#818cf8",
  debug:                "#94a3b8",
};

const TYPE_INPUT: Record<string, string> = {
  int: "number",
  float: "number",
  bool: "checkbox",
};

// ── Static API endpoint registry ─────────────────────────────────────────────

interface ApiEndpoint {
  method: "GET" | "POST" | "PUT" | "DELETE";
  path: string;
  description: string;
  body?: string;
}

const STATIC_ENDPOINTS: { section: string; color: string; endpoints: ApiEndpoint[] }[] = [
  {
    section: "Tools",
    color: "#818cf8",
    endpoints: [
      { method: "GET",  path: "/api/tools/",            description: "List all registered tools" },
      { method: "GET",  path: "/api/tools/{tool_id}",   description: "Get tool spec (inputs, outputs, runtime)" },
      { method: "POST", path: "/api/tools/{tool_id}/run", description: "Invoke a single tool directly",
        body: '{"params": {"heavy_chain": "EVQL...", "light_chain": ""}}' },
    ],
  },
  {
    section: "Pipeline Runs",
    color: "#38bdf8",
    endpoints: [
      { method: "GET",  path: "/api/runs/",              description: "List all past runs" },
      { method: "POST", path: "/api/runs/",              description: "Submit a full pipeline run",
        body: '{"id": "uuid", "name": "my run", "schema_version": "1", "nodes": [...], "edges": [...]}' },
      { method: "GET",  path: "/api/runs/{run_id}/",     description: "Get run status + per-node logs" },
      { method: "POST", path: "/api/runs/{run_id}/cancel/", description: "Request cancellation of a running run" },
    ],
  },
  {
    section: "Saved Pipelines",
    color: "#a78bfa",
    endpoints: [
      { method: "GET",  path: "/api/pipelines/",              description: "List saved pipelines" },
      { method: "POST", path: "/api/pipelines/",              description: "Save or overwrite a pipeline" },
      { method: "GET",  path: "/api/pipelines/{pipeline_id}", description: "Get a saved pipeline" },
      { method: "DELETE", path: "/api/pipelines/{pipeline_id}", description: "Delete a saved pipeline" },
    ],
  },
  {
    section: "Results Database",
    color: "#34d399",
    endpoints: [
      { method: "GET", path: "/api/results/molecules/",         description: "List all molecules with run counts" },
      { method: "GET", path: "/api/results/molecules/{id}/",    description: "Full molecule detail (structures, docking, etc.)" },
      { method: "GET", path: "/api/results/structures/{id}/pdb", description: "Download predicted structure PDB" },
      { method: "GET", path: "/api/results/docking/{id}/pdb",   description: "Download docking complex PDB" },
    ],
  },
  {
    section: "Sequence Library",
    color: "#fbbf24",
    endpoints: [
      { method: "GET",    path: "/api/sequences/collections/",                     description: "List all sequence collections" },
      { method: "POST",   path: "/api/sequences/collections/",                     description: "Create a collection",
        body: '{"name": "My Antibodies", "description": "optional"}' },
      { method: "GET",    path: "/api/sequences/collections/{coll_id}/",           description: "Get collection detail with all entries" },
      { method: "PUT",    path: "/api/sequences/collections/{coll_id}/",           description: "Rename / update description",
        body: '{"name": "New Name"}' },
      { method: "DELETE", path: "/api/sequences/collections/{coll_id}/",           description: "Delete collection and all its entries" },
      { method: "GET",    path: "/api/sequences/collections/{coll_id}/entries/?q=", description: "Search entries by name or sequence" },
      { method: "POST",   path: "/api/sequences/collections/{coll_id}/entries/",   description: "Add an entry to a collection",
        body: '{"name": "Ab-001", "heavy_chain": "EVQL...", "light_chain": "DIQM..."}' },
      { method: "DELETE", path: "/api/sequences/entries/{entry_id}/",              description: "Delete a single entry" },
      { method: "POST",   path: "/api/sequences/collections/{coll_id}/import/",    description: "Bulk-import from Results DB molecules",
        body: '{"molecule_ids": ["uuid1", "uuid2"]}' },
    ],
  },
  {
    section: "Artifacts",
    color: "#fb7185",
    endpoints: [
      { method: "GET", path: "/api/artifacts/{artifact_id}/", description: "Fetch raw artifact content" },
    ],
  },
  {
    section: "Analysis",
    color: "#f97316",
    endpoints: [
      { method: "GET", path: "/api/analysis/{run_id}/{node_id}/", description: "Get analysis data for a completed node" },
    ],
  },
  {
    section: "Health",
    color: "#94a3b8",
    endpoints: [
      { method: "GET", path: "/health", description: "Backend health check" },
      { method: "GET", path: "/ws/{run_id}", description: "WebSocket: subscribe to live run updates" },
    ],
  },
];

const METHOD_COLOR: Record<string, string> = {
  GET:    "text-emerald-400 bg-emerald-400/10",
  POST:   "text-sky-400 bg-sky-400/10",
  PUT:    "text-amber-400 bg-amber-400/10",
  DELETE: "text-red-400 bg-red-400/10",
};

// ── Components ────────────────────────────────────────────────────────────────

interface TerminalPageProps {
  onBack: () => void;
}

export function TerminalPage({ onBack }: TerminalPageProps) {
  const { data: tools } = useTools();
  const [tab, setTab] = useState<"run" | "docs">("run");

  // Run tab state
  const [search, setSearch] = useState("");
  const [selectedTool, setSelectedTool] = useState<ToolSpec | null>(null);
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [runId, setRunId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [analysis, setAnalysis] = useState<{ runId: string; nodeId: string } | null>(null);

  // Docs tab state
  const [copied, setCopied] = useState<string | null>(null);

  const grouped = useMemo(() => {
    if (!tools) return {} as Record<string, ToolSpec[]>;
    const q = search.toLowerCase();
    const filtered = q
      ? tools.filter((t) => t.name.toLowerCase().includes(q) || t.id.toLowerCase().includes(q))
      : tools;
    const result: Record<string, ToolSpec[]> = {};
    for (const t of filtered) {
      (result[t.category] ??= []).push(t);
    }
    return result;
  }, [tools, search]);

  function selectTool(tool: ToolSpec) {
    setSelectedTool(tool);
    setRunId(null);
    const defaults: Record<string, unknown> = {};
    for (const p of tool.inputs) {
      if (p.default !== undefined && p.default !== null &&
          !(typeof p.default === "string" && p.default.startsWith("__default_file__:"))) {
        defaults[p.name] = p.default;
      }
    }
    setParams(defaults);
  }

  async function handleRun() {
    if (!selectedTool) return;
    setSubmitting(true);
    setRunId(null);
    try {
      const r = await fetch(`/api/tools/${selectedTool.id}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ params }),
      });
      if (!r.ok) throw new Error(await r.text());
      const run = await r.json();
      setRunId(run.id);
    } catch (e) {
      console.error("Terminal run failed:", e);
    } finally {
      setSubmitting(false);
    }
  }

  function copyToClipboard(text: string, key: string) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    });
  }

  const accentColor = selectedTool ? (CATEGORY_COLOR[selectedTool.category] ?? "#94a3b8") : "#818cf8";

  // Build dynamic tool endpoints for the docs
  const toolEndpoints: ApiEndpoint[] = (tools ?? []).map((t) => ({
    method: "POST" as const,
    path: `/api/tools/${t.id}/run`,
    description: `Run ${t.name} · ${t.category.replace(/_/g, " ")}`,
    body: JSON.stringify({
      params: Object.fromEntries(t.inputs.map((p) => [p.name, p.default ?? ""])),
    }, null, 2),
  }));

  const allDocs = [
    ...STATIC_ENDPOINTS,
    ...(toolEndpoints.length ? [{ section: "Tool Run Endpoints", color: "#818cf8", endpoints: toolEndpoints }] : []),
  ];

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-canvas">
      {/* Header */}
      <div
        className="h-12 shrink-0 border-b border-border flex items-center px-4 gap-4"
        style={{ background: "linear-gradient(90deg, #0e1425 0%, #111830 100%)" }}
      >
        <button onClick={onBack}
          className="flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors">
          <ArrowLeft size={15} /> Back to Canvas
        </button>
        <div className="w-px h-4 bg-border" />
        <TerminalIcon size={14} className="text-violet-400" />
        <span className="text-sm font-bold text-white">API Terminal</span>
        {tools && (
          <span className="text-xs text-slate-600">{tools.length} tools</span>
        )}

        {/* Tabs */}
        <div className="ml-auto flex items-center gap-1 bg-canvas rounded-lg p-0.5 border border-border">
          <button
            onClick={() => setTab("run")}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-all
              ${tab === "run" ? "bg-violet-600 text-white" : "text-slate-400 hover:text-white"}`}
          >
            <Play size={11} />
            Run
          </button>
          <button
            onClick={() => setTab("docs")}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-all
              ${tab === "docs" ? "bg-violet-600 text-white" : "text-slate-400 hover:text-white"}`}
          >
            <BookOpen size={11} />
            API Docs
          </button>
        </div>
      </div>

      {/* ── Run Tab ─────────────────────────────────────────────────────────── */}
      {tab === "run" && (
        <div className="flex flex-1 overflow-hidden">
          {/* Left: tool list */}
          <div className="w-64 shrink-0 border-r border-border flex flex-col overflow-hidden bg-surface">
            <div className="px-3 py-2 border-b border-border shrink-0">
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search tools…"
                className="w-full bg-canvas border border-border rounded-lg px-2.5 py-1.5 text-xs
                  text-slate-300 placeholder-slate-600 focus:outline-none focus:border-violet-500/60"
              />
            </div>
            <div className="flex-1 overflow-y-auto">
              {!tools && (
                <div className="p-4 text-xs text-slate-600 animate-pulse text-center">Loading…</div>
              )}
              {tools && Object.keys(grouped).length === 0 && (
                <div className="p-4 text-xs text-slate-600 text-center">No tools match</div>
              )}
              {Object.entries(grouped).map(([category, categoryTools]) => (
                <div key={category}>
                  <div
                    className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest
                      sticky top-0 bg-surface border-b border-border/50 z-10"
                    style={{ color: CATEGORY_COLOR[category] ?? "#94a3b8" }}
                  >
                    {category.replace(/_/g, " ")}
                  </div>
                  {categoryTools.map((tool) => (
                    <button
                      key={tool.id}
                      onClick={() => selectTool(tool)}
                      className={`w-full text-left px-4 py-2.5 border-b border-border/30 last:border-0
                        transition-colors text-xs
                        ${selectedTool?.id === tool.id
                          ? "bg-violet-500/10 text-violet-200 border-l-2 border-l-violet-500"
                          : "text-slate-300 hover:bg-surface2"}`}
                    >
                      <div className="font-medium truncate">{tool.name}</div>
                      <div className="text-slate-600 text-[10px] mt-0.5 font-mono">{tool.id}</div>
                    </button>
                  ))}
                </div>
              ))}
            </div>
          </div>

          {/* Right: param form + output */}
          {!selectedTool ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <TerminalIcon size={40} className="text-slate-700 mx-auto mb-3" />
                <p className="text-slate-500 text-sm font-medium">Select a tool to invoke it</p>
                <p className="text-slate-700 text-xs mt-1 font-mono">POST /api/tools/&#123;id&#125;/run</p>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex overflow-hidden">
              {/* Param form */}
              <div className="flex-1 flex flex-col overflow-hidden">
                <div className="flex-1 overflow-y-auto p-6">
                  {/* Tool header */}
                  <div className="mb-5">
                    <div className="flex items-center gap-2 mb-1">
                      <h2 className="text-lg font-bold text-white">{selectedTool.name}</h2>
                      <span
                        className="text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider"
                        style={{ color: accentColor, background: `${accentColor}22` }}
                      >
                        {selectedTool.category.replace(/_/g, " ")}
                      </span>
                      {selectedTool.wip && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-fuchsia-950/60 border border-fuchsia-800/50 text-fuchsia-400 font-bold uppercase">
                          WIP
                        </span>
                      )}
                    </div>
                    {selectedTool.description && (
                      <p className="text-sm text-slate-500 leading-relaxed max-w-2xl">{selectedTool.description}</p>
                    )}
                    <div className="mt-1.5 font-mono text-xs text-slate-600">
                      POST /api/tools/{selectedTool.id}/run
                    </div>
                  </div>

                  {/* cURL example */}
                  <div className="mb-6 rounded-xl border border-border overflow-hidden">
                    <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-surface">
                      <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">cURL</span>
                      <button
                        onClick={() => copyToClipboard(
                          `curl -X POST http://localhost:8000/api/tools/${selectedTool.id}/run \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify({ params }, null, 2)}'`,
                          "curl"
                        )}
                        className="flex items-center gap-1 text-[10px] text-slate-600 hover:text-slate-300 transition-colors"
                      >
                        <Copy size={10} />
                        {copied === "curl" ? "Copied!" : "Copy"}
                      </button>
                    </div>
                    <pre className="px-4 py-3 text-[11px] font-mono text-slate-400 overflow-x-auto bg-canvas leading-relaxed">
{`curl -X POST http://localhost:8000/api/tools/${selectedTool.id}/run \\
  -H "Content-Type: application/json" \\
  -d '${JSON.stringify({ params }, null, 2)}'`}
                    </pre>
                  </div>

                  {/* Inputs */}
                  {selectedTool.inputs.length > 0 && (
                    <div className="space-y-4">
                      <h3 className="text-[11px] font-bold uppercase tracking-widest text-slate-500">Inputs</h3>
                      {selectedTool.inputs.map((port) => {
                        const inputType = TYPE_INPUT[port.type] ?? "text";
                        const value = params[port.name] ?? "";
                        const isTextarea = ["fasta", "pdb", "str", "text"].includes(port.type);

                        return (
                          <div key={port.name}>
                            <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-300 mb-1.5">
                              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: accentColor }} />
                              {port.name}
                              {port.required && <span className="text-red-400">*</span>}
                              <span className="ml-auto text-slate-600 font-normal font-mono">{port.type}</span>
                            </label>
                            {port.description && (
                              <p className="text-[11px] text-slate-600 mb-1.5 pl-3">{port.description}</p>
                            )}
                            {inputType === "checkbox" ? (
                              <input
                                type="checkbox"
                                checked={Boolean(value)}
                                onChange={(e) => setParams((p) => ({ ...p, [port.name]: e.target.checked }))}
                                className="ml-3 w-4 h-4 accent-violet-500"
                              />
                            ) : isTextarea ? (
                              <textarea
                                value={String(value)}
                                onChange={(e) => setParams((p) => ({ ...p, [port.name]: e.target.value }))}
                                rows={5}
                                placeholder={`${port.type}…`}
                                className="w-full bg-canvas border border-border rounded-lg px-3 py-2 text-xs
                                  font-mono text-slate-200 placeholder-slate-600 resize-y
                                  focus:outline-none focus:border-violet-500/60 transition-colors"
                              />
                            ) : (
                              <input
                                type={inputType}
                                value={String(value)}
                                step={inputType === "number" ? "any" : undefined}
                                onChange={(e) =>
                                  setParams((p) => ({
                                    ...p,
                                    [port.name]: inputType === "number" ? Number(e.target.value) : e.target.value,
                                  }))
                                }
                                placeholder={port.required ? `required` : `optional`}
                                className="w-full bg-canvas border border-border rounded-lg px-3 py-2 text-sm
                                  text-slate-200 placeholder-slate-600
                                  focus:outline-none focus:border-violet-500/60 transition-colors"
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Outputs reference */}
                  {selectedTool.outputs.length > 0 && (
                    <div className="mt-6 space-y-1">
                      <h3 className="text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-2">Outputs</h3>
                      {selectedTool.outputs.map((port) => (
                        <div key={port.name}
                          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface border border-border text-xs">
                          <span className="w-1.5 h-1.5 rounded-full bg-slate-600 shrink-0" />
                          <span className="text-slate-300 font-medium">{port.name}</span>
                          <span className="text-slate-600 font-mono ml-auto">{port.type}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Run button */}
                <div className="shrink-0 px-6 py-4 border-t border-border bg-surface flex items-center gap-4">
                  <button
                    onClick={handleRun}
                    disabled={submitting}
                    className="flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold
                      text-white disabled:opacity-40 transition-all shadow-lg
                      bg-gradient-to-r from-violet-600 to-indigo-600
                      hover:from-violet-500 hover:to-indigo-500"
                  >
                    <Play size={13} fill="white" />
                    {submitting ? "Submitting…" : "Run Tool"}
                  </button>
                  {runId && (
                    <span className="text-xs text-slate-500 font-mono">run: {runId.slice(0, 12)}…</span>
                  )}
                </div>
              </div>

              {/* Run output panel */}
              {runId && (
                <div className="w-80 shrink-0 border-l border-border bg-surface flex flex-col overflow-hidden">
                  <RunPanel
                    runId={runId}
                    onClose={() => setRunId(null)}
                    onOpenAnalysis={(rId, nId) => setAnalysis({ runId: rId, nodeId: nId })}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── API Docs Tab ─────────────────────────────────────────────────────── */}
      {tab === "docs" && (
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-4xl mx-auto px-6 py-6 space-y-8">
            <div>
              <h1 className="text-lg font-bold text-white mb-1">API Reference</h1>
              <p className="text-sm text-slate-500">
                Base URL: <span className="font-mono text-slate-300">http://localhost:8000</span>
                {" · "}All endpoints return JSON unless noted.
                {" · "}Interactive docs: <span className="font-mono text-indigo-400">/docs</span>
              </p>
            </div>

            {allDocs.map(({ section, color, endpoints }) => (
              <div key={section}>
                <div className="flex items-center gap-2 mb-3">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: color }} />
                  <h2 className="text-sm font-bold" style={{ color }}>{section}</h2>
                  <span className="text-xs text-slate-600">{endpoints.length} endpoint{endpoints.length !== 1 ? "s" : ""}</span>
                </div>
                <div className="space-y-2">
                  {endpoints.map((ep, i) => {
                    const curlKey = `${section}-${i}`;
                    const curlCmd = ep.body
                      ? `curl -X ${ep.method} http://localhost:8000${ep.path} \\\n  -H "Content-Type: application/json" \\\n  -d '${ep.body}'`
                      : `curl http://localhost:8000${ep.path}`;

                    return (
                      <div key={i} className="rounded-xl border border-border overflow-hidden">
                        <div className="flex items-center gap-3 px-4 py-2.5 bg-surface">
                          <span className={`text-[11px] font-bold font-mono px-2 py-0.5 rounded-md shrink-0 ${METHOD_COLOR[ep.method]}`}>
                            {ep.method}
                          </span>
                          <span className="font-mono text-sm text-slate-200 flex-1">{ep.path}</span>
                          <button
                            onClick={() => copyToClipboard(curlCmd, curlKey)}
                            className="flex items-center gap-1 text-[10px] text-slate-600 hover:text-slate-300 transition-colors shrink-0"
                          >
                            <Copy size={10} />
                            {copied === curlKey ? "Copied!" : "Copy cURL"}
                          </button>
                        </div>
                        <div className="px-4 py-2 bg-canvas/50 border-t border-border/50">
                          <p className="text-xs text-slate-500">{ep.description}</p>
                          {ep.body && (
                            <pre className="mt-1.5 text-[11px] font-mono text-slate-600 overflow-x-auto leading-relaxed">
                              {ep.body}
                            </pre>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

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
