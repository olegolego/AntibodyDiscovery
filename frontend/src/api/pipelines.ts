import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { Pipeline } from "@/types";

export function usePipelines() {
  return useQuery<Pipeline[]>({
    queryKey: ["pipelines"],
    queryFn: async () => {
      const { data } = await api.get<Pipeline[]>("/pipelines/");
      return data;
    },
  });
}

export async function savePipeline(pipeline: Pipeline): Promise<Pipeline> {
  // Try update first; fall back to create
  try {
    const { data } = await api.put<Pipeline>(`/pipelines/${pipeline.id}`, pipeline);
    return data;
  } catch {
    const { data } = await api.post<Pipeline>("/pipelines/", pipeline);
    return data;
  }
}
