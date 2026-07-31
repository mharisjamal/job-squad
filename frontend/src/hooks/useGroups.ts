import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { apiGet, apiSend } from "../lib/api";
import type {
  DiscoverGroup,
  Group,
  GroupCreatePayload,
  GroupDetail,
  GroupPatch,
  JoinRequestRecord,
} from "../types/api";

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
    mutationFn: (payload: GroupCreatePayload) => apiSend<Group>("POST", "/api/groups", payload),
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

/** Owner: change name / visibility / description (merge semantics). */
export function useUpdateGroup(gid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: GroupPatch) => apiSend<GroupDetail>("PATCH", `/api/groups/${gid}`, patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["group", gid] });
      void qc.invalidateQueries({ queryKey: ["groups"] });
      void qc.invalidateQueries({ queryKey: ["discover"] });
    },
  });
}

/** Public directory of groups the caller is not already in. Debounce `q` upstream. */
export function useDiscoverGroups(q: string) {
  return useQuery({
    queryKey: ["discover", q],
    queryFn: () =>
      apiGet<DiscoverGroup[]>(`/api/groups/discover${q ? `?q=${encodeURIComponent(q)}` : ""}`),
    placeholderData: keepPreviousData,
  });
}

/** Request to join a public group; flips its row to "Requested". */
export function useRequestJoin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (groupId: number) =>
      apiSend<JoinRequestRecord>("POST", `/api/groups/${groupId}/request`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["discover"] }),
  });
}
