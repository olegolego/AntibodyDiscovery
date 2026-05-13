import { api } from "./client";

export interface CustomTool {
  id: string;
  name: string;
  tool_yaml: string;
  run_py: string;
  requirements: string | null;
  status: "draft" | "published";
  created_at: string;
  updated_at: string;
}

export interface CustomToolSummary {
  id: string;
  name: string;
  status: "draft" | "published";
  created_at: string;
  updated_at: string;
}

export interface Benchmark {
  id: string;
  name: string;
  description: string | null;
  metric: string;
  pass_threshold: number | null;
}

export interface BenchmarkEntryResult {
  entry_id: string;
  name: string | null;
  predicted: unknown;
  expected: unknown;
  score: number | null;
  error: string | null;
}

export interface BenchmarkResult {
  benchmark_id: string;
  metric: string;
  mean_score: number | null;
  pass_threshold: number | null;
  passed: boolean | null;
  n_entries: number;
  n_errors: number;
  per_entry: BenchmarkEntryResult[];
}

export interface DatasetRunEntryResult {
  entry_id: string;
  name: string | null;
  inputs: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface DatasetRunResult {
  dataset_id: string;
  n_entries: number;
  n_errors: number;
  results: DatasetRunEntryResult[];
}

export const workshopApi = {
  listTools: async (): Promise<CustomToolSummary[]> => {
    const { data } = await api.get("/workshop/tools");
    return data;
  },

  createTool: async (params: {
    name: string;
    tool_yaml?: string;
    run_py?: string;
  }): Promise<CustomTool> => {
    const { data } = await api.post("/workshop/tools", params);
    return data;
  },

  getTool: async (id: string): Promise<CustomTool> => {
    const { data } = await api.get(`/workshop/tools/${id}`);
    return data;
  },

  updateTool: async (
    id: string,
    patch: Partial<Pick<CustomTool, "name" | "tool_yaml" | "run_py" | "requirements">>
  ): Promise<CustomTool> => {
    const { data } = await api.put(`/workshop/tools/${id}`, patch);
    return data;
  },

  deleteTool: async (id: string): Promise<void> => {
    await api.delete(`/workshop/tools/${id}`);
  },

  publishTool: async (id: string): Promise<{ tool_id: string; spec: unknown }> => {
    const { data } = await api.post(`/workshop/tools/${id}/publish`);
    return data;
  },

  claudeHelp: async (
    id: string,
    prompt: string,
    context?: string
  ): Promise<{ code: string }> => {
    const { data } = await api.post(`/workshop/tools/${id}/claude`, {
      prompt,
      context: context ?? "",
    });
    return data;
  },

  listBenchmarks: async (): Promise<Benchmark[]> => {
    const { data } = await api.get("/workshop/benchmarks");
    return data;
  },

  runBenchmark: async (
    toolId: string,
    benchmarkId: string
  ): Promise<BenchmarkResult> => {
    const { data } = await api.post(
      `/workshop/tools/${toolId}/benchmark/${benchmarkId}`
    );
    return data;
  },

  runOnDataset: async (
    toolId: string,
    datasetId: string
  ): Promise<DatasetRunResult> => {
    const { data } = await api.post(
      `/workshop/tools/${toolId}/run-dataset/${datasetId}`
    );
    return data;
  },
};

/** Open a WebSocket for live tool execution. Returns the WebSocket instance. */
export function openWorkshopSocket(sessionId: string): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${proto}://${window.location.host}/ws/workshop/${sessionId}`);
}
