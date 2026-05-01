import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { Pipeline, Run } from "@/types";

export async function submitRun(pipeline: Pipeline): Promise<Run> {
  const { data } = await api.post<Run>("/runs/", pipeline);
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
