import { api } from "./client";

export interface LoopRun {
  loop_id: string;
  pipeline_id: string;
  max_iterations: number;
  current_iteration: number;
  status: "running" | "succeeded" | "failed" | "cancelled";
  stop_reason: string | null;
  run_ids: string[];
  created_at: string;
}

export async function getLoopRun(loopId: string): Promise<LoopRun> {
  const { data } = await api.get<LoopRun>(`/loop-runs/${loopId}/`);
  return data;
}

export async function cancelLoopRun(loopId: string): Promise<void> {
  await api.post(`/loop-runs/${loopId}/cancel/`);
}
