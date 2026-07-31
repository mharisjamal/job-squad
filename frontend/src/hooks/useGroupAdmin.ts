import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../lib/api";
import type { Group, JoinRequest } from "../types/api";

/** Owner: pending join requests awaiting approval. Gate with `enabled` (owner only). */
export function useGroupRequests(gid: number, enabled: boolean) {
  return useQuery({
    queryKey: ["group-requests", gid],
    queryFn: () => apiGet<JoinRequest[]>(`/api/groups/${gid}/requests`),
    enabled: enabled && Number.isFinite(gid),
  });
}

function invalidateAfterDecision(qc: ReturnType<typeof useQueryClient>, gid: number) {
  void qc.invalidateQueries({ queryKey: ["group-requests", gid] });
  void qc.invalidateQueries({ queryKey: ["group", gid] });
  void qc.invalidateQueries({ queryKey: ["groups"] });
}

/** Owner: approve a request -> the user becomes a member. */
export function useApproveRequest(gid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reqId: number) =>
      apiSend<{ ok: boolean }>("POST", `/api/groups/${gid}/requests/${reqId}/approve`),
    onSuccess: () => invalidateAfterDecision(qc, gid),
  });
}

/** Owner: reject a request -> no membership. */
export function useRejectRequest(gid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reqId: number) =>
      apiSend<{ ok: boolean }>("POST", `/api/groups/${gid}/requests/${reqId}/reject`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["group-requests", gid] });
      void qc.invalidateQueries({ queryKey: ["group", gid] });
    },
  });
}

/**
 * Owner: remove a member. The backend also deletes that user's applications and
 * portal statuses in this group, so refresh everything scoped to the group.
 */
export function useRemoveMember(gid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: number) =>
      apiSend<{ ok: boolean }>("DELETE", `/api/groups/${gid}/members/${userId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["group", gid] });
      void qc.invalidateQueries({ queryKey: ["groups"] });
      void qc.invalidateQueries({ queryKey: ["companies", gid] });
      void qc.invalidateQueries({ queryKey: ["portals", gid] });
      void qc.invalidateQueries({ queryKey: ["stats", gid] });
      void qc.invalidateQueries({ queryKey: ["activity", gid] });
    },
  });
}

/** Owner: issue a fresh invite code; the old one stops working immediately. */
export function useRegenerateInvite(gid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiSend<Group>("POST", `/api/groups/${gid}/regenerate-invite`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["group", gid] });
      void qc.invalidateQueries({ queryKey: ["groups"] });
    },
  });
}
