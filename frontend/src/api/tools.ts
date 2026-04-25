import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { ToolSpec } from "@/types";

export function useTools() {
  return useQuery<ToolSpec[]>({
    queryKey: ["tools"],
    queryFn: async () => {
      const { data } = await api.get<ToolSpec[]>("/tools/");
      return data;
    },
  });
}
