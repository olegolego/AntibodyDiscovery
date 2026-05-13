import { useEffect, useRef, useState } from "react";
import { Play, RotateCcw, Loader2, Database, Code2 } from "lucide-react";
import { listDatasets, type Dataset } from "../api/datasets";
import {
  openWorkshopSocket,
  workshopApi,
  type CustomTool,
  type DatasetRunEntryResult,
} from "../api/workshop";

type InputMode = "manual" | "dataset";

type LogLine =
  | { kind: "log"; text: string }
  | { kind: "result"; value: unknown }
  | { kind: "error"; text: string };

interface TestPanelProps {
  tool: CustomTool;
  onError: (err: string) => void;
}

export function TestPanel({ tool, onError }: TestPanelProps) {
  const [mode, setMode] = useState<InputMode>("manual");

  // Manual mode state
  const [inputs, setInputs] = useState('{\n  "input_data": 42\n}');
  const [lines, setLines] = useState<LogLine[]>([]);
  const [running, setRunning] = useState(false);
  const doneReceivedRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  // Dataset mode state
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>("");
  const [datasetRunning, setDatasetRunning] = useState(false);
  const [datasetResults, setDatasetResults] = useState<DatasetRunEntryResult[] | null>(null);
  const [datasetError, setDatasetError] = useState("");

  useEffect(() => {
    if (mode === "dataset") {
      listDatasets().then((ds) => {
        setDatasets(ds);
        if (ds.length > 0 && !selectedDatasetId) setSelectedDatasetId(ds[0].id);
      });
    }
  }, [mode]);

  function appendLine(line: LogLine) {
    setLines((prev) => [...prev, line]);
    setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 30);
  }

  // ── Manual run via WebSocket ──────────────────────────────────────────────

  function handleRun() {
    if (running) return;

    let parsedInputs: Record<string, unknown> = {};
    try {
      parsedInputs = JSON.parse(inputs);
    } catch {
      appendLine({ kind: "error", text: "Invalid JSON in inputs" });
      return;
    }

    setLines([]);
    setRunning(true);
    doneReceivedRef.current = false;

    const sessionId = Math.random().toString(36).slice(2);
    const ws = openWorkshopSocket(sessionId);

    ws.onopen = () => {
      ws.send(JSON.stringify({ run_py: tool.run_py, inputs: parsedInputs }));
    };

    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.type === "log") {
        appendLine({ kind: "log", text: msg.text });
      } else if (msg.type === "done") {
        doneReceivedRef.current = true;
        if (msg.error) {
          appendLine({ kind: "error", text: msg.error });
          onError(msg.error);
        } else {
          appendLine({ kind: "result", value: msg.result });
        }
        setRunning(false);
      } else if (msg.type === "error") {
        doneReceivedRef.current = true;
        appendLine({ kind: "error", text: msg.message });
        setRunning(false);
      }
    };

    ws.onerror = () => {
      // onerror fires when the server closes the socket after sending "done" —
      // only treat it as a real failure if we never received a done message.
      if (!doneReceivedRef.current) {
        appendLine({ kind: "error", text: "WebSocket connection failed" });
        setRunning(false);
      }
    };

    ws.onclose = () => {
      setRunning(false);
    };
  }

  // ── Dataset run via REST ──────────────────────────────────────────────────

  async function handleDatasetRun() {
    if (!selectedDatasetId) return;
    setDatasetRunning(true);
    setDatasetResults(null);
    setDatasetError("");
    try {
      const res = await workshopApi.runOnDataset(tool.id, selectedDatasetId);
      setDatasetResults(res.results);
    } catch (e: unknown) {
      setDatasetError(e instanceof Error ? e.message : String(e));
    } finally {
      setDatasetRunning(false);
    }
  }

  const selectedDs = datasets.find((d) => d.id === selectedDatasetId);

  return (
    <div className="flex flex-col h-full">
      {/* Mode tabs */}
      <div className="flex border-b border-border flex-shrink-0">
        <button
          onClick={() => setMode("manual")}
          className={`flex items-center gap-1.5 px-3 py-2 text-xs transition-colors
            ${mode === "manual"
              ? "text-white border-b-2 border-indigo-500"
              : "text-slate-500 hover:text-slate-300"
            }`}
        >
          <Code2 size={11} /> Manual
        </button>
        <button
          onClick={() => setMode("dataset")}
          className={`flex items-center gap-1.5 px-3 py-2 text-xs transition-colors
            ${mode === "dataset"
              ? "text-white border-b-2 border-indigo-500"
              : "text-slate-500 hover:text-slate-300"
            }`}
        >
          <Database size={11} /> Dataset
        </button>
      </div>

      {/* ── Manual mode ── */}
      {mode === "manual" && (
        <div className="flex flex-1 min-h-0">
          {/* Inputs */}
          <div className="w-56 flex-shrink-0 border-r border-border flex flex-col">
            <div className="px-3 py-2 border-b border-border flex-shrink-0">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
                Inputs (JSON)
              </span>
            </div>
            <div className="flex-1 overflow-auto p-2">
              <textarea
                value={inputs}
                onChange={(e) => setInputs(e.target.value)}
                spellCheck={false}
                className="w-full h-full bg-transparent text-slate-300 font-mono text-xs
                  resize-none focus:outline-none"
              />
            </div>
            <div className="p-2 border-t border-border">
              <button
                onClick={handleRun}
                disabled={running}
                className="w-full flex items-center justify-center gap-1.5 py-1.5 rounded-lg
                  text-xs font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50
                  text-white transition-colors"
              >
                {running
                  ? <><Loader2 size={12} className="animate-spin" /> Running…</>
                  : <><Play size={12} /> Run</>
                }
              </button>
            </div>
          </div>

          {/* Output */}
          <div className="flex-1 flex flex-col min-w-0">
            <div className="px-3 py-2 flex items-center justify-between border-b border-border flex-shrink-0">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
                Output
              </span>
              <button
                onClick={() => setLines([])}
                className="text-slate-600 hover:text-slate-400 transition-colors"
                title="Clear"
              >
                <RotateCcw size={11} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-3 font-mono text-xs space-y-0.5">
              {lines.length === 0 && (
                <span className="text-slate-700">Run your tool to see output here…</span>
              )}
              {lines.map((line, i) => (
                <div key={i}>
                  {line.kind === "log" && <span className="text-slate-400">{line.text}</span>}
                  {line.kind === "result" && (
                    <pre className="text-emerald-400 whitespace-pre-wrap break-all">
                      {JSON.stringify(line.value, null, 2)}
                    </pre>
                  )}
                  {line.kind === "error" && (
                    <pre className="text-red-400 whitespace-pre-wrap break-all">{line.text}</pre>
                  )}
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
          </div>
        </div>
      )}

      {/* ── Dataset mode ── */}
      {mode === "dataset" && (
        <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">
          {/* Dataset selector */}
          <div className="flex gap-2 items-center">
            <select
              value={selectedDatasetId}
              onChange={(e) => { setSelectedDatasetId(e.target.value); setDatasetResults(null); }}
              className="flex-1 bg-[#1e2030] border border-border text-white text-xs rounded-lg
                px-2 py-1.5 focus:outline-none focus:border-indigo-500"
            >
              {datasets.length === 0
                ? <option value="">No datasets</option>
                : datasets.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name} ({d.entry_count} entries)
                    </option>
                  ))
              }
            </select>
            <button
              onClick={handleDatasetRun}
              disabled={datasetRunning || !selectedDatasetId}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white transition-colors
                whitespace-nowrap"
            >
              {datasetRunning
                ? <><Loader2 size={12} className="animate-spin" /> Running…</>
                : <><Play size={12} /> Run on all</>
              }
            </button>
          </div>

          {selectedDs && (
            <p className="text-xs text-slate-600">
              Each entry's fields (name, heavy_chain, light_chain, custom columns) are passed
              as inputs to your tool.
            </p>
          )}

          {datasetError && (
            <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40
              rounded-lg p-2 whitespace-pre-wrap">
              {datasetError}
            </div>
          )}

          {/* Results table */}
          {datasetResults && (
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-400">
                  Results — {datasetResults.length} entries
                </span>
                {datasetResults.some((r) => r.error) && (
                  <span className="text-xs text-red-400">
                    {datasetResults.filter((r) => r.error).length} error(s)
                  </span>
                )}
              </div>
              <div className="space-y-1.5 max-h-72 overflow-y-auto">
                {datasetResults.map((r) => (
                  <div
                    key={r.entry_id}
                    className="rounded-lg border border-border p-2 text-xs font-mono"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-slate-400 font-sans">
                        {r.name ?? r.entry_id.slice(0, 8)}
                      </span>
                      {r.error
                        ? <span className="text-red-400 text-[10px]">error</span>
                        : <span className="text-emerald-400 text-[10px]">ok</span>
                      }
                    </div>
                    {r.error
                      ? <pre className="text-red-400 whitespace-pre-wrap text-[11px]">{r.error}</pre>
                      : <pre className="text-emerald-300 whitespace-pre-wrap text-[11px] overflow-x-auto">
                          {JSON.stringify(r.result, null, 2)}
                        </pre>
                    }
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
