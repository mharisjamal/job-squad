import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { GroupStats } from "../types/api";

export function useStats(gid: number) {
  return useQuery({
    queryKey: ["stats", gid],
    queryFn: () => apiGet<GroupStats>(`/api/groups/${gid}/stats`),
    enabled: Number.isFinite(gid),
  });
}
