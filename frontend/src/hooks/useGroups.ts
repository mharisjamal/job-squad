import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../lib/api";
import type { Group, GroupDetail } from "../types/api";

export function useGroups() {
  return useQuery({
    queryKey: ["groups"],
    queryFn: () => apiGet<Group[]>("/api/groups"),
  });
}

export function useGroupDetail(gid: number) {
  return useQuery({
    queryKey: ["group", gid],
    queryFn: () => apiGet<GroupDetail>(`/api/groups/${gid}`),
    enabled: Number.isFinite(gid),
  });
}

export function useCreateGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => apiSend<Group>("POST", "/api/groups", { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["groups"] }),
  });
}

export function useJoinGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (invite_code: string) =>
      apiSend<Group>("POST", "/api/groups/join", { invite_code }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["groups"] }),
  });
}
