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
    staleTime: 0,
  });
}

export async function savePipeline(pipeline: Pipeline): Promise<Pipeline> {
  try {
    const { data } = await api.put<Pipeline>(`/pipelines/${pipeline.id}`, pipeline);
    return data;
  } catch (err: unknown) {
    // Only fall back to create on 404; re-throw other errors
    const status = (err as { response?: { status?: number } })?.response?.status;
    if (status !== 404) throw err;
    const { data } = await api.post<Pipeline>("/pipelines/", pipeline);
    return data;
  }
}

export async function deletePipeline(id: string): Promise<void> {
  await api.delete(`/pipelines/${id}`);
}
