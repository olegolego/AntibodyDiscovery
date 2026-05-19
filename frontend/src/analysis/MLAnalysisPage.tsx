/**
 * ML Analysis Platform — PCA, t-SNE, K-means, clustering, training curves.
 * Analyzes embedding vectors and predictions from completed pipeline runs.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, Legend, BarChart, Bar, Cell,
} from "recharts";
import {
  ArrowLeft, RefreshCw, BarChart2, GitBranch, Zap, Activity, ChevronDown, ChevronRight,
  Layers, Database, TrendingDown,
} from "lucide-react";
import { listRuns } from "@/api/runs";
import type { Run } from "@/types";

// ── API helpers ───────────────────────────────────────────────────────────────

const API = "http://localhost:8000/api/ml-analysis";

async function fetchSummary(runId: string) {
  const r = await fetch(`${API}/runs/${runId}/summary`);
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

async function fetchEmbeddings(runId: string) {
  const r = await fetch(`${API}/runs/${runId}/embeddings`);
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

async function fetchTraining(runId: string) {
  const r = await fetch(`${API}/runs/${runId}/training`);
  if (!r.ok) return null;
  return r.json();
}

async function fetchPredictions(runId: string) {
  const r = await fetch(`${API}/runs/${runId}/predictions`);
  if (!r.ok) return null;
  return r.json();
}

async function postPCA(body: object) {
  const r = await fetch(`${API}/pca`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function postTSNE(body: object) {
  const r = await fetch(`${API}/tsne`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function postKMeans(body: object) {
  const r = await fetch(`${API}/kmeans`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function postStats(body: object) {
  const r = await fetch(`${API}/stats`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// ── Colour palette for clusters ───────────────────────────────────────────────

const CLUSTER_COLORS = [
  "#6366f1", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6",
  "#14b8a6", "#f97316", "#3b82f6", "#ec4899", "#84cc16",
];

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionHeader({ icon: Icon, title, subtitle }: { icon: React.ElementType; title: string; subtitle?: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon size={14} className="text-indigo-400 shrink-0" />
      <span className="text-sm font-semibold text-white">{title}</span>
      {subtitle && <span className="text-xs text-slate-500">{subtitle}</span>}
    </div>
  );
}

function EmptyState({ msg }: { msg: string }) {
  return <div className="text-xs text-slate-600 italic py-6 text-center">{msg}</div>;
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-border bg-surface p-4 ${className}`}>
      {children}
    </div>
  );
}

// ── Scatter plot (PCA / t-SNE) ────────────────────────────────────────────────

interface ScatterPoint { id: string; x: number; y: number; label?: number | null; cluster?: number }

function EmbeddingScatter({ points, title, colorBy = "cluster" }: {
  points: ScatterPoint[]; title: string; colorBy?: "cluster" | "label";
}) {
  if (!points.length) return <EmptyState msg="No points to display" />;

  const labelMin = Math.min(...points.map((p) => p.label ?? 0));
  const labelMax = Math.max(...points.map((p) => p.label ?? 0));
  const labelRange = labelMax - labelMin || 1;

  const colored = points.map((p) => ({
    ...p,
    fill: colorBy === "cluster"
      ? CLUSTER_COLORS[(p.cluster ?? 0) % CLUSTER_COLORS.length]
      : `hsl(${((p.label ?? labelMin) - labelMin) / labelRange * 240}, 70%, 55%)`,
  }));

  return (
    <div>
      <div className="text-xs text-slate-400 mb-2">{title} ({points.length} points)</div>
      <ResponsiveContainer width="100%" height={260}>
        <ScatterChart>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e2533" />
          <XAxis dataKey="x" type="number" tick={{ fontSize: 9, fill: "#64748b" }} />
          <YAxis dataKey="y" type="number" tick={{ fontSize: 9, fill: "#64748b" }} />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0].payload as ScatterPoint;
              return (
                <div className="bg-[#0f1a2e] border border-border rounded-lg px-3 py-2 text-xs">
                  <div className="text-white font-mono">{d.id}</div>
                  <div className="text-slate-400">x={d.x.toFixed(3)} y={d.y.toFixed(3)}</div>
                  {d.label != null && <div className="text-indigo-300">label={d.label.toFixed(3)}</div>}
                  {d.cluster != null && <div className="text-amber-300">cluster {d.cluster}</div>}
                </div>
              );
            }}
          />
          <Scatter data={colored} fill="#6366f1">
            {colored.map((p, i) => (
              <Cell key={i} fill={p.fill} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Training curve ────────────────────────────────────────────────────────────

function TrainingCurve({ history }: { history: Array<{ epoch: number; train_loss: number; val_loss?: number | null }> }) {
  if (!history.length) return <EmptyState msg="No training history" />;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={history}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e2533" />
        <XAxis dataKey="epoch" tick={{ fontSize: 9, fill: "#64748b" }} label={{ value: "Epoch", position: "insideBottom", offset: -2, fontSize: 9, fill: "#64748b" }} />
        <YAxis tick={{ fontSize: 9, fill: "#64748b" }} />
        <Tooltip
          contentStyle={{ background: "#0f1a2e", border: "1px solid #1e2533", borderRadius: 8, fontSize: 11 }}
          labelStyle={{ color: "#94a3b8" }}
        />
        <Legend wrapperStyle={{ fontSize: 10 }} />
        <Line type="monotone" dataKey="train_loss" stroke="#6366f1" strokeWidth={2} dot={false} name="Train loss" />
        <Line type="monotone" dataKey="val_loss" stroke="#f59e0b" strokeWidth={2} dot={false} name="Val loss" strokeDasharray="5 5" />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── Histogram ─────────────────────────────────────────────────────────────────

function PredictionHistogram({ histogram }: { histogram: { counts: number[]; bin_edges: number[] } }) {
  const data = histogram.counts.map((count, i) => ({
    bin: `${histogram.bin_edges[i].toFixed(2)}`,
    count,
  }));
  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={data} margin={{ top: 4, right: 4, bottom: 16, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e2533" />
        <XAxis dataKey="bin" tick={{ fontSize: 8, fill: "#64748b" }} />
        <YAxis tick={{ fontSize: 9, fill: "#64748b" }} />
        <Tooltip
          contentStyle={{ background: "#0f1a2e", border: "1px solid #1e2533", borderRadius: 8, fontSize: 11 }}
        />
        <Bar dataKey="count" fill="#6366f1" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

interface Props { onBack: () => void }

type AnalysisMethod = "pca" | "tsne" | "kmeans";

export function MLAnalysisPage({ onBack }: Props) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunIds, setSelectedRunIds] = useState<Set<string>>(new Set());
  const [method, setMethod] = useState<AnalysisMethod>("pca");
  const [nClusters, setNClusters] = useState(3);
  const [perplexity, setPerplexity] = useState(5);

  // Per-run analysis data
  const [summaries, setSummaries] = useState<Record<string, object>>({});
  const [trainings, setTrainings] = useState<Record<string, object | null>>({});
  const [predData, setPredData] = useState<Record<string, object | null>>({});

  // Computed results
  const [scatterPoints, setScatterPoints] = useState<ScatterPoint[]>([]);
  const [clusterResult, setClusterResult] = useState<object | null>(null);
  const [statsResult, setStatsResult] = useState<object | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisRunning, setAnalysisRunning] = useState(false);

  const [runsExpanded, setRunsExpanded] = useState(true);

  // Load runs on mount
  useEffect(() => {
    listRuns().then((all) => {
      const succeeded = all.filter((r) => r.status === "succeeded");
      setRuns(succeeded);
    });
  }, []);

  const toggleRun = useCallback((id: string) => {
    setSelectedRunIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  // Load summary + training for newly selected runs
  useEffect(() => {
    const toLoad = [...selectedRunIds].filter((id) => !(id in summaries));
    if (!toLoad.length) return;
    toLoad.forEach(async (id) => {
      const [sum, train, preds] = await Promise.all([
        fetchSummary(id).catch(() => null),
        fetchTraining(id).catch(() => null),
        fetchPredictions(id).catch(() => null),
      ]);
      setSummaries((p) => ({ ...p, [id]: sum }));
      setTrainings((p) => ({ ...p, [id]: train }));
      setPredData((p) => ({ ...p, [id]: preds }));
    });
  }, [selectedRunIds]);

  const handleAnalyze = useCallback(async () => {
    if (!selectedRunIds.size) return;
    setAnalysisRunning(true);
    setAnalysisError(null);
    setScatterPoints([]);
    setClusterResult(null);
    setStatsResult(null);

    try {
      // Collect all embedding vectors from selected runs
      const allIds: string[] = [];
      const allVecs: number[][] = [];
      const allLabels: (number | null)[] = [];

      for (const runId of selectedRunIds) {
        const embs = await fetchEmbeddings(runId).catch(() => null);
        if (!embs?.vectors?.length) continue;
        // Fetch predictions as labels if available
        const preds = await fetchPredictions(runId).catch(() => null);
        const predMap: Record<string, number> = {};
        if (preds?.predictions) {
          for (const p of preds.predictions) predMap[p.id] = p.value;
        }
        embs.ids.forEach((id: string, i: number) => {
          allIds.push(`${runId.slice(0, 6)}·${id}`);
          allVecs.push(embs.vectors[i]);
          allLabels.push(predMap[id] ?? null);
        });
      }

      if (!allVecs.length) {
        setAnalysisError("No embedding vectors found in selected runs. Run ESM or AbMAP embedding nodes first.");
        return;
      }

      if (method === "pca") {
        const result = await postPCA({ vectors: allVecs, ids: allIds, labels: allLabels, n_components: 2 });
        setScatterPoints(result.points.map((p: { id: string; x: number; y: number; label?: number | null }) => ({
          id: p.id, x: p.x, y: p.y, label: p.label, cluster: 0,
        })));
      } else if (method === "tsne") {
        const result = await postTSNE({ vectors: allVecs, ids: allIds, labels: allLabels, n_components: 2, perplexity });
        setScatterPoints(result.points.map((p: { id: string; x: number; y: number; label?: number | null }) => ({
          id: p.id, x: p.x, y: p.y, label: p.label, cluster: 0,
        })));
      } else if (method === "kmeans") {
        const result = await postKMeans({ vectors: allVecs, ids: allIds, labels: allLabels, n_clusters: nClusters });
        setClusterResult(result);
        setScatterPoints(result.assignments.map((a: { id: string; cluster: number; label?: number | null }) => ({
          id: a.id, x: 0, y: 0, cluster: a.cluster, label: a.label,
        })));

        // Also run PCA to get 2D coords for visualising cluster assignments
        const pcaResult = await postPCA({ vectors: allVecs, ids: allIds, labels: allLabels, n_components: 2 });
        const clusterMap: Record<string, number> = {};
        result.assignments.forEach((a: { id: string; cluster: number }) => { clusterMap[a.id] = a.cluster; });
        setScatterPoints(pcaResult.points.map((p: { id: string; x: number; y: number; label?: number | null }) => ({
          id: p.id, x: p.x, y: p.y, cluster: clusterMap[p.id] ?? 0, label: p.label,
        })));
      }

      // Stats on all predictions
      const allPredVals: number[] = [];
      const allPredIds: string[] = [];
      for (const runId of selectedRunIds) {
        const preds = predData[runId] as { predictions?: { id: string; value: number }[] } | null;
        if (preds?.predictions) {
          for (const p of preds.predictions) {
            allPredVals.push(p.value);
            allPredIds.push(p.id);
          }
        }
      }
      if (allPredVals.length > 0) {
        const stats = await postStats({ values: allPredVals, labels: allPredIds });
        setStatsResult(stats);
      }
    } catch (e) {
      setAnalysisError(String(e));
    } finally {
      setAnalysisRunning(false);
    }
  }, [selectedRunIds, method, nClusters, perplexity, predData]);

  const selectedSummaryList = useMemo(() =>
    [...selectedRunIds].map((id) => (summaries[id] as { pipeline_name?: string; nodes?: object[] } | undefined)),
    [selectedRunIds, summaries]);

  const selectedTrainingList = useMemo(() =>
    [...selectedRunIds]
      .map((id) => trainings[id] as { history?: object[]; final_train_loss?: number; epochs?: number; node_id?: string } | null)
      .filter(Boolean),
    [selectedRunIds, trainings]);

  const selectedPredList = useMemo(() =>
    [...selectedRunIds]
      .map((id) => ({ runId: id, data: predData[id] as { predictions?: { id: string; value: number }[]; stats?: object } | null }))
      .filter((x) => x.data?.predictions?.length),
    [selectedRunIds, predData]);

  function pipelineName(run: Run): string {
    return (run.pipeline_snapshot as Record<string, unknown>)?.name as string ?? "Untitled";
  }

  return (
    <div className="flex flex-col h-screen bg-[#0a0e1a] text-white overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-4 h-11 border-b border-border shrink-0">
        <button onClick={onBack} className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors">
          <ArrowLeft size={13} /> Canvas
        </button>
        <div className="w-px h-4 bg-border" />
        <BarChart2 size={14} className="text-indigo-400" />
        <span className="text-sm font-bold text-white">ML Analysis Platform</span>
        <div className="w-px h-4 bg-border" />
        <span className="text-xs text-slate-500">PCA · t-SNE · K-means · Clustering · Training curves</span>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => listRuns().then((all) => setRuns(all.filter((r) => r.status === "succeeded")))}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors px-2 py-1 rounded border border-border hover:border-slate-500"
          >
            <RefreshCw size={11} /> Refresh
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* ── Left sidebar: Run selector ── */}
        <div className="w-72 border-r border-border flex flex-col overflow-hidden shrink-0">
          <button
            onClick={() => setRunsExpanded((v) => !v)}
            className="flex items-center gap-2 px-4 py-2.5 border-b border-border text-xs font-semibold text-slate-400 hover:text-white transition-colors"
          >
            {runsExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            Completed Runs ({runs.length})
          </button>

          {runsExpanded && (
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
              {runs.length === 0 && <EmptyState msg="No completed runs yet. Run a pipeline first." />}
              {runs.map((run) => {
                const sel = selectedRunIds.has(run.id);
                const sum = summaries[run.id] as { embeddings?: { count: number }; predictions?: { count: number } } | undefined;
                return (
                  <button
                    key={run.id}
                    onClick={() => toggleRun(run.id)}
                    className={`w-full text-left px-3 py-2 rounded-lg border transition-colors ${
                      sel
                        ? "border-indigo-500/50 bg-indigo-500/10 text-white"
                        : "border-transparent hover:border-border bg-white/3 hover:bg-white/5 text-slate-300"
                    }`}
                  >
                    <div className="text-xs font-medium truncate">{pipelineName(run)}</div>
                    <div className="text-[10px] text-slate-500 font-mono mt-0.5">{run.id.slice(0, 16)}…</div>
                    {sum && (
                      <div className="flex gap-2 mt-1">
                        {(sum.embeddings?.count ?? 0) > 0 && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-400 border border-rose-500/20">
                            {sum.embeddings!.count} emb
                          </span>
                        )}
                        {(sum.predictions?.count ?? 0) > 0 && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-400 border border-indigo-500/20">
                            {sum.predictions!.count} pred
                          </span>
                        )}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          {/* Analysis controls */}
          <div className="border-t border-border p-3 space-y-3 shrink-0">
            <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Method</div>
            <div className="flex gap-1">
              {(["pca", "tsne", "kmeans"] as AnalysisMethod[]).map((m) => (
                <button
                  key={m}
                  onClick={() => setMethod(m)}
                  className={`flex-1 py-1 rounded text-[10px] font-semibold transition-colors border ${
                    method === m
                      ? "bg-indigo-500/20 border-indigo-500/50 text-indigo-300"
                      : "bg-white/3 border-border text-slate-500 hover:text-slate-300"
                  }`}
                >
                  {m.toUpperCase()}
                </button>
              ))}
            </div>

            {method === "tsne" && (
              <div className="space-y-1">
                <label className="text-[10px] text-slate-500">Perplexity: {perplexity}</label>
                <input type="range" min={2} max={30} value={perplexity} onChange={(e) => setPerplexity(+e.target.value)}
                  className="w-full h-1 accent-indigo-500" />
              </div>
            )}
            {method === "kmeans" && (
              <div className="space-y-1">
                <label className="text-[10px] text-slate-500">K clusters: {nClusters}</label>
                <input type="range" min={2} max={10} value={nClusters} onChange={(e) => setNClusters(+e.target.value)}
                  className="w-full h-1 accent-indigo-500" />
              </div>
            )}

            <button
              onClick={handleAnalyze}
              disabled={!selectedRunIds.size || analysisRunning}
              className={`w-full py-2 rounded-lg text-xs font-semibold transition-all border ${
                selectedRunIds.size && !analysisRunning
                  ? "bg-indigo-500/20 border-indigo-500/50 text-indigo-300 hover:bg-indigo-500/30"
                  : "bg-white/3 border-border text-slate-600 cursor-not-allowed"
              }`}
            >
              {analysisRunning ? "Running…" : `Analyze ${selectedRunIds.size > 0 ? `(${selectedRunIds.size} runs)` : ""}`}
            </button>
          </div>
        </div>

        {/* ── Main content ── */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {analysisError && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
              {analysisError}
            </div>
          )}

          {/* Embedding visualization */}
          {scatterPoints.length > 0 && (
            <Card>
              <SectionHeader
                icon={GitBranch}
                title={method === "pca" ? "PCA — Embedding Space" : method === "tsne" ? "t-SNE — Embedding Space" : "K-means Clusters (PCA coords)"}
                subtitle={`${scatterPoints.length} points`}
              />
              <EmbeddingScatter
                points={scatterPoints}
                title={method.toUpperCase()}
                colorBy={method === "kmeans" ? "cluster" : scatterPoints.some((p) => p.label != null) ? "label" : "cluster"}
              />
              {method === "kmeans" && clusterResult && (
                <div className="mt-3 grid grid-cols-3 gap-3">
                  {Object.entries((clusterResult as { cluster_sizes: Record<string, number> }).cluster_sizes).map(([c, size]) => (
                    <div key={c} className="rounded-lg bg-white/3 border border-border px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ background: CLUSTER_COLORS[+c % CLUSTER_COLORS.length] }} />
                        <span className="text-xs text-white">Cluster {c}</span>
                      </div>
                      <div className="text-lg font-bold text-white mt-1">{size}</div>
                      <div className="text-[10px] text-slate-500">sequences</div>
                    </div>
                  ))}
                  <div className="rounded-lg bg-indigo-500/5 border border-indigo-500/20 px-3 py-2">
                    <div className="text-xs text-indigo-400">Silhouette</div>
                    <div className="text-lg font-bold text-white mt-1">
                      {((clusterResult as { silhouette_score: number }).silhouette_score).toFixed(3)}
                    </div>
                    <div className="text-[10px] text-slate-500">−1 worst → 1 best</div>
                  </div>
                </div>
              )}
            </Card>
          )}

          {/* Training curves */}
          {selectedTrainingList.length > 0 && (
            <Card>
              <SectionHeader icon={TrendingDown} title="Training Curves" subtitle={`${selectedTrainingList.length} DNN run(s)`} />
              <div className="space-y-4">
                {selectedTrainingList.map((t, i) => t && (
                  <div key={i}>
                    <div className="flex items-center gap-3 mb-2">
                      <span className="text-[10px] font-mono text-slate-500">{t.node_id ?? `run ${i + 1}`}</span>
                      <span className="text-[10px] px-2 py-0.5 rounded bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
                        {t.epochs} epochs · final loss {t.final_train_loss?.toExponential(2) ?? "—"}
                      </span>
                    </div>
                    <TrainingCurve history={(t.history as Array<{ epoch: number; train_loss: number; val_loss?: number | null }>) ?? []} />
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Predictions */}
          {selectedPredList.length > 0 && (
            <Card>
              <SectionHeader icon={Zap} title="Predictions" subtitle={`${selectedPredList.reduce((s, x) => s + (x.data?.predictions?.length ?? 0), 0)} total`} />
              <div className="space-y-4">
                {selectedPredList.map(({ runId, data }) => data && (
                  <div key={runId}>
                    <div className="text-[10px] font-mono text-slate-500 mb-2">{runId.slice(0, 20)}…</div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-border">
                            <th className="text-left py-1.5 px-2 text-slate-500 font-medium">Sequence</th>
                            <th className="text-right py-1.5 px-2 text-slate-500 font-medium">Predicted Value</th>
                            <th className="text-right py-1.5 px-2 text-slate-500 font-medium">Bar</th>
                          </tr>
                        </thead>
                        <tbody>
                          {[...(data.predictions ?? [])]
                            .sort((a, b) => b.value - a.value)
                            .map((p, i) => {
                              const allVals = (data.predictions ?? []).map((x: { value: number }) => x.value);
                              const min = Math.min(...allVals), max = Math.max(...allVals), range = max - min || 1;
                              const pct = ((p.value - min) / range) * 100;
                              return (
                                <tr key={i} className="border-b border-border/50 hover:bg-white/3">
                                  <td className="py-1.5 px-2 font-mono text-slate-300">{p.id}</td>
                                  <td className="py-1.5 px-2 text-right text-white font-semibold">{p.value.toFixed(4)}</td>
                                  <td className="py-1.5 px-2 w-28">
                                    <div className="h-2 rounded-full bg-white/5 overflow-hidden">
                                      <div className="h-full rounded-full bg-indigo-500" style={{ width: `${pct}%` }} />
                                    </div>
                                  </td>
                                </tr>
                              );
                            })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Stats histogram */}
          {statsResult && (
            <Card>
              <SectionHeader icon={Activity} title="Prediction Statistics" />
              <div className="grid grid-cols-4 gap-3 mb-4">
                {[
                  { label: "Count", value: (statsResult as { count: number }).count, fmt: (v: number) => String(v) },
                  { label: "Mean", value: (statsResult as { mean: number }).mean, fmt: (v: number) => v.toFixed(4) },
                  { label: "Std", value: (statsResult as { std: number }).std, fmt: (v: number) => v.toFixed(4) },
                  { label: "Range", value: (statsResult as { max: number; min: number }).max - (statsResult as { max: number; min: number }).min, fmt: (v: number) => v.toFixed(4) },
                ].map(({ label, value, fmt }) => (
                  <div key={label} className="rounded-lg bg-white/3 border border-border px-3 py-2 text-center">
                    <div className="text-[10px] text-slate-500">{label}</div>
                    <div className="text-base font-bold text-white mt-0.5">{fmt(value)}</div>
                  </div>
                ))}
              </div>
              <PredictionHistogram histogram={(statsResult as { histogram: { counts: number[]; bin_edges: number[] } }).histogram} />
              <div className="mt-3 grid grid-cols-5 gap-2 text-center">
                {["p10", "p25", "p50", "p75", "p90"].map((p) => (
                  <div key={p} className="rounded bg-white/3 border border-border px-2 py-1.5">
                    <div className="text-[9px] text-slate-500">{p.toUpperCase()}</div>
                    <div className="text-xs font-semibold text-white">
                      {((statsResult as { percentiles: Record<string, number> }).percentiles[p] ?? 0).toFixed(3)}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Run summaries */}
          {selectedRunIds.size > 0 && selectedSummaryList.some(Boolean) && (
            <Card>
              <SectionHeader icon={Layers} title="Run Node Overview" />
              <div className="space-y-3">
                {[...selectedRunIds].map((runId) => {
                  const sum = summaries[runId] as {
                    pipeline_name?: string;
                    nodes?: Array<{ node_id: string; tool: string; status: string; has_embedding: boolean; has_predictions: boolean; has_training: boolean }>;
                  } | undefined;
                  if (!sum) return null;
                  return (
                    <div key={runId} className="rounded-lg border border-border p-3">
                      <div className="text-xs font-semibold text-white mb-2">{sum.pipeline_name}</div>
                      <div className="flex flex-wrap gap-1.5">
                        {(sum.nodes ?? []).map((node) => (
                          <div key={node.node_id} className={`flex items-center gap-1 px-2 py-1 rounded border text-[10px] ${
                            node.status === "succeeded" ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-400" : "border-red-500/30 bg-red-500/5 text-red-400"
                          }`}>
                            <span className="font-mono">{node.tool}</span>
                            {node.has_embedding && <Database size={8} className="text-rose-400" />}
                            {node.has_predictions && <Zap size={8} className="text-indigo-400" />}
                            {node.has_training && <TrendingDown size={8} className="text-amber-400" />}
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>
          )}

          {/* Empty state */}
          {selectedRunIds.size === 0 && (
            <div className="flex flex-col items-center justify-center h-64 text-center">
              <BarChart2 size={40} className="text-slate-700 mb-4" />
              <div className="text-slate-500 text-sm">Select one or more completed runs from the sidebar</div>
              <div className="text-slate-600 text-xs mt-1">Then choose a method and click Analyze</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
