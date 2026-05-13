import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { Pipeline, Run } from "@/types";

export async function submitRun(pipeline: Pipeline): Promise<Run> {
  const { data } = await api.post<Run>("/runs/", pipeline);
  return data;
}

export async function listRuns(): Promise<Run[]> {
  const { data } = await api.get<Run[]>("/runs/");
  return Array.isArray(data) ? data : [];
}

export async function rerunRun(runId: string): Promise<Run> {
  const { data } = await api.post<Run>(`/runs/${runId}/rerun/`);
  return data;
}

export async function forceFailRun(runId: string): Promise<void> {
  await api.post(`/runs/${runId}/force-fail/`);
}

export async function deleteRun(runId: string): Promise<void> {
  await api.delete(`/runs/${runId}/`);
}

// ── Run Report ────────────────────────────────────────────────────────────────

export interface ReportMetricValue {
  label: string;
  value: number | string | null;
  unit: string | null;
}

export interface NodeReportMetrics {
  primary: ReportMetricValue | null;
  secondary: ReportMetricValue[];
  confidence: "high" | "medium" | "low" | "neutral" | "error";
}

export interface NodeReport {
  node_id: string;
  tool_id: string;
  tool_name: string;
  status: string;
  error_excerpt: string | null;
  has_analysis: boolean;
  metrics: NodeReportMetrics | null;
}

export interface RunReport {
  run_id: string;
  status: string;
  created_at: string | null;
  pipeline_name: string;
  nodes: NodeReport[];
}

export async function fetchRunReport(runId: string): Promise<RunReport> {
  const { data } = await api.get<RunReport>(`/runs/${runId}/report/`);
  return data;
}

export function useRun(runId: string | null) {
  return useQuery<Run>({
    queryKey: ["run", runId],
    queryFn: async () => {
      const { data } = await api.get<Run>(`/runs/${runId}/`);
      return data;
    },
    enabled: runId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "succeeded" || status === "failed" || status === "cancelled") {
        return false;
      }
      return 2000;
    },
  });
}
