import { api } from "./client";

export interface LoopScoreEntry {
  iteration: number;
  vh_prefix: string;
  vh_cdr3?: string;
  best_score: number | null;
  scores_by_rank: Record<string, number>;
}

export interface LoopRun {
  loop_id: string;
  pipeline_id: string;
  max_iterations: number;
  current_iteration: number;
  status: "running" | "succeeded" | "failed" | "cancelled";
  stop_reason: string | null;
  run_ids: string[];
  created_at: string;
  score_history?: LoopScoreEntry[];
}

export interface LoopRunSummary {
  loop_id: string;
  pipeline_id: string;
  max_iterations: number;
  current_iteration: number;
  status: "running" | "succeeded" | "failed" | "cancelled";
  stop_reason: string | null;
  run_ids_count: number;
  latest_run_id?: string | null;
  created_at: string;
  best_score?: number | null;
  best_iter?: number | null;
  score_count?: number;
}

export async function listLoopRuns(): Promise<LoopRunSummary[]> {
  const { data } = await api.get<LoopRunSummary[]>("/loop-runs/");
  return data;
}

export async function getLoopRun(loopId: string): Promise<LoopRun> {
  const { data } = await api.get<LoopRun>(`/loop-runs/${loopId}/`);
  return data;
}

export async function cancelLoopRun(loopId: string): Promise<void> {
  await api.post(`/loop-runs/${loopId}/cancel/`);
}
