import { useEffect, useState } from "react";
import { BarChart2, CheckCircle2, XCircle, Loader2, Play } from "lucide-react";
import { workshopApi, type Benchmark, type BenchmarkResult, type CustomTool, type DatasetRunResult } from "../api/workshop";
import { listDatasets, type Dataset } from "../api/datasets";

interface BenchmarkPanelProps {
  tool: CustomTool;
}

export function BenchmarkPanel({ tool }: BenchmarkPanelProps) {
  // ── Dataset run ───────────────────────────────────────────────────────────
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [dsSelected, setDsSelected] = useState("");
  const [dsRunning, setDsRunning] = useState(false);
  const [dsResult, setDsResult] = useState<DatasetRunResult | null>(null);
  const [dsError, setDsError] = useState("");

  // ── Saved benchmarks ──────────────────────────────────────────────────────
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);
  const [benchSelected, setBenchSelected] = useState("");
  const [benchRunning, setBenchRunning] = useState(false);
  const [benchResult, setBenchResult] = useState<BenchmarkResult | null>(null);
  const [benchError, setBenchError] = useState("");

  useEffect(() => {
    listDatasets().then((ds) => {
      setDatasets(ds);
      if (ds.length > 0) setDsSelected(ds[0].id);
    });
    workshopApi.listBenchmarks().then((b) => {
      setBenchmarks(b);
      if (b.length > 0) setBenchSelected(b[0].id);
    });
  }, [tool.id]);

  async function handleRunOnDataset() {
    if (!dsSelected) return;
    setDsRunning(true);
    setDsResult(null);
    setDsError("");
    try {
      const r = await workshopApi.runOnDataset(tool.id, dsSelected);
      setDsResult(r);
    } catch (e: unknown) {
      setDsError(e instanceof Error ? e.message : String(e));
    } finally {
      setDsRunning(false);
    }
  }

  async function handleRunBenchmark() {
    if (!benchSelected) return;
    setBenchRunning(true);
    setBenchResult(null);
    setBenchError("");
    try {
      const r = await workshopApi.runBenchmark(tool.id, benchSelected);
      setBenchResult(r);
    } catch (e: unknown) {
      setBenchError(e instanceof Error ? e.message : String(e));
    } finally {
      setBenchRunning(false);
    }
  }

  const selectedBench = benchmarks.find((b) => b.id === benchSelected);
  const selectedDs = datasets.find((d) => d.id === dsSelected);

  return (
    <div className="flex flex-col h-full overflow-y-auto p-3 gap-4">

      {/* ── Run on Dataset ── */}
      <section className="flex flex-col gap-2">
        <span className="text-xs font-semibold text-slate-300 uppercase tracking-wide">
          Run on Dataset
        </span>

        {datasets.length === 0 ? (
          <p className="text-xs text-slate-600">No datasets found. Create one in the Datasets page.</p>
        ) : (
          <select
            value={dsSelected}
            onChange={(e) => { setDsSelected(e.target.value); setDsResult(null); }}
            className="w-full bg-[#1e2030] border border-border text-white text-xs rounded-lg
              px-2 py-1.5 focus:outline-none focus:border-indigo-500"
          >
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} ({d.entry_count} rows)
              </option>
            ))}
          </select>
        )}

        {selectedDs && (
          <p className="text-[11px] text-slate-500">
            {selectedDs.entry_count} entr{selectedDs.entry_count === 1 ? "y" : "ies"}
            {selectedDs.columns.length > 0 && ` · ${selectedDs.columns.length} custom col${selectedDs.columns.length !== 1 ? "s" : ""}`}
          </p>
        )}

        <button
          onClick={handleRunOnDataset}
          disabled={dsRunning || !dsSelected}
          className="flex items-center justify-center gap-1.5 py-1.5 rounded-lg
            text-xs font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50
            text-white transition-colors"
        >
          {dsRunning
            ? <><Loader2 size={12} className="animate-spin" /> Running…</>
            : <><Play size={12} /> Run on Dataset</>
          }
        </button>

        {dsError && (
          <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40
            rounded-lg p-2 whitespace-pre-wrap">
            {dsError}
          </div>
        )}

        {dsResult && (
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>{dsResult.n_entries} entries ran</span>
              {dsResult.n_errors > 0 && (
                <span className="text-red-400">{dsResult.n_errors} error{dsResult.n_errors !== 1 ? "s" : ""}</span>
              )}
            </div>
            <div className="space-y-0.5 max-h-64 overflow-y-auto rounded border border-border/50">
              {dsResult.results.map((r) => (
                <div
                  key={r.entry_id}
                  className="flex items-start gap-2 px-2 py-1.5 border-b border-border/40
                    last:border-0 text-xs"
                >
                  <span className="text-slate-500 truncate w-24 shrink-0">
                    {r.name ?? r.entry_id.slice(0, 8)}
                  </span>
                  {r.error ? (
                    <span className="text-red-400 truncate flex-1">{r.error}</span>
                  ) : (
                    <span className="text-slate-300 font-mono break-all flex-1 text-[10px]">
                      {JSON.stringify(r.result)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <div className="border-t border-border/50" />

      {/* ── Saved Benchmarks ── */}
      <section className="flex flex-col gap-2">
        <span className="text-xs font-semibold text-slate-300 uppercase tracking-wide">
          Saved Benchmarks
        </span>

        {benchmarks.length === 0 ? (
          <p className="text-xs text-slate-600">No saved benchmarks yet.</p>
        ) : (
          <>
            <select
              value={benchSelected}
              onChange={(e) => { setBenchSelected(e.target.value); setBenchResult(null); }}
              className="w-full bg-[#1e2030] border border-border text-white text-xs rounded-lg
                px-2 py-1.5 focus:outline-none focus:border-indigo-500"
            >
              {benchmarks.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>

            {selectedBench && (
              <div className="text-[11px] text-slate-500 leading-relaxed">
                {selectedBench.description && <p>{selectedBench.description}</p>}
                <p>
                  Metric: <span className="text-slate-300">{selectedBench.metric}</span>
                  {selectedBench.pass_threshold != null && (
                    <> · Pass: <span className="text-slate-300">{selectedBench.pass_threshold}</span></>
                  )}
                </p>
              </div>
            )}

            <button
              onClick={handleRunBenchmark}
              disabled={benchRunning || !benchSelected}
              className="flex items-center justify-center gap-1.5 py-1.5 rounded-lg
                text-xs font-medium bg-violet-600 hover:bg-violet-500 disabled:opacity-50
                text-white transition-colors"
            >
              {benchRunning
                ? <><Loader2 size={12} className="animate-spin" /> Running…</>
                : <><BarChart2 size={12} /> Run Benchmark</>
              }
            </button>
          </>
        )}

        {benchError && (
          <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40
            rounded-lg p-2 whitespace-pre-wrap">
            {benchError}
          </div>
        )}

        {benchResult && (
          <div className="flex flex-col gap-2">
            <div className="rounded-lg border border-border p-3 flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-white">Score Card</span>
                {benchResult.passed != null && (
                  benchResult.passed
                    ? <span className="flex items-center gap-1 text-xs text-emerald-400">
                        <CheckCircle2 size={12} /> Pass
                      </span>
                    : <span className="flex items-center gap-1 text-xs text-red-400">
                        <XCircle size={12} /> Fail
                      </span>
                )}
              </div>
              <div className="grid grid-cols-2 gap-1 text-xs">
                <span className="text-slate-500">Mean {benchResult.metric}</span>
                <span className="text-white font-mono">
                  {benchResult.mean_score != null ? benchResult.mean_score.toFixed(4) : "—"}
                </span>
                <span className="text-slate-500">Entries</span>
                <span className="text-white">{benchResult.n_entries}</span>
                {benchResult.n_errors > 0 && (
                  <>
                    <span className="text-slate-500">Errors</span>
                    <span className="text-red-400">{benchResult.n_errors}</span>
                  </>
                )}
              </div>
            </div>
            <div className="space-y-0.5 max-h-48 overflow-y-auto">
              {benchResult.per_entry.map((e) => (
                <div
                  key={e.entry_id}
                  className="flex items-center justify-between gap-2 py-0.5
                    border-b border-border/50 last:border-0 text-xs"
                >
                  <span className="text-slate-400 truncate max-w-[80px]">
                    {e.name ?? e.entry_id.slice(0, 8)}
                  </span>
                  {e.error
                    ? <span className="text-red-400 truncate max-w-[120px]">{e.error}</span>
                    : <span className="text-white font-mono">
                        {e.score != null ? e.score.toFixed(4) : "—"}
                      </span>
                  }
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
