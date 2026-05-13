import { useEffect, useState } from "react";
import { BarChart2, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { workshopApi, type Benchmark, type BenchmarkResult, type CustomTool } from "../api/workshop";

interface BenchmarkPanelProps {
  tool: CustomTool;
}

export function BenchmarkPanel({ tool }: BenchmarkPanelProps) {
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BenchmarkResult | null>(null);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    workshopApi.listBenchmarks().then((b) => {
      setBenchmarks(b);
      if (b.length > 0) setSelected(b[0].id);
    });
  }, []);

  async function handleRun() {
    if (!selected) return;
    setRunning(true);
    setResult(null);
    setError("");
    try {
      const r = await workshopApi.runBenchmark(tool.id, selected);
      setResult(r);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  const bench = benchmarks.find((b) => b.id === selected);

  return (
    <div className="flex flex-col h-full overflow-y-auto p-3 gap-3">
      <div className="flex flex-col gap-2">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
          Select Benchmark
        </span>
        {benchmarks.length === 0 ? (
          <p className="text-xs text-slate-600">No benchmarks available yet.</p>
        ) : (
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="w-full bg-[#1e2030] border border-border text-white text-xs rounded-lg
              px-2 py-1.5 focus:outline-none focus:border-indigo-500"
          >
            {benchmarks.map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </select>
        )}

        {bench && (
          <div className="text-xs text-slate-500 leading-relaxed">
            {bench.description && <p>{bench.description}</p>}
            <p className="mt-1">
              Metric: <span className="text-slate-300">{bench.metric}</span>
              {bench.pass_threshold != null && (
                <> · Pass: <span className="text-slate-300">{bench.pass_threshold}</span></>
              )}
            </p>
          </div>
        )}

        <button
          onClick={handleRun}
          disabled={running || !selected}
          className="flex items-center justify-center gap-1.5 py-1.5 rounded-lg
            text-xs font-medium bg-violet-600 hover:bg-violet-500 disabled:opacity-50
            text-white transition-colors"
        >
          {running
            ? <><Loader2 size={12} className="animate-spin" /> Running…</>
            : <><BarChart2 size={12} /> Run Benchmark</>
          }
        </button>
      </div>

      {error && (
        <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40
          rounded-lg p-2 whitespace-pre-wrap">
          {error}
        </div>
      )}

      {result && (
        <div className="flex flex-col gap-2">
          {/* Score card */}
          <div className="rounded-lg border border-border p-3 flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-white">Score Card</span>
              {result.passed != null && (
                result.passed
                  ? <span className="flex items-center gap-1 text-xs text-emerald-400">
                      <CheckCircle2 size={12} /> Pass
                    </span>
                  : <span className="flex items-center gap-1 text-xs text-red-400">
                      <XCircle size={12} /> Fail
                    </span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-1 text-xs">
              <span className="text-slate-500">Mean {result.metric}</span>
              <span className="text-white font-mono">
                {result.mean_score != null ? result.mean_score.toFixed(4) : "—"}
              </span>
              <span className="text-slate-500">Entries</span>
              <span className="text-white">{result.n_entries}</span>
              {result.n_errors > 0 && (
                <>
                  <span className="text-slate-500">Errors</span>
                  <span className="text-red-400">{result.n_errors}</span>
                </>
              )}
            </div>
          </div>

          {/* Per-entry table */}
          <div className="text-xs">
            <div className="text-slate-500 mb-1">Per entry</div>
            <div className="space-y-0.5 max-h-60 overflow-y-auto">
              {result.per_entry.map((e) => (
                <div
                  key={e.entry_id}
                  className="flex items-center justify-between gap-2 py-0.5
                    border-b border-border/50 last:border-0"
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
        </div>
      )}
    </div>
  );
}
