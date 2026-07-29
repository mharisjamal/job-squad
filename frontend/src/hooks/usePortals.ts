import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../lib/api";
import type { Portal, PortalPayload, PortalStatusRow, PortalStatusUpsert } from "../types/api";

export function usePortals(gid: number) {
  return useQuery({
    queryKey: ["portals", gid],
    queryFn: () => apiGet<Portal[]>(`/api/groups/${gid}/portals`),
    enabled: Number.isFinite(gid),
  });
}

function invalidatePortalData(qc: ReturnType<typeof useQueryClient>, gid: number) {
  void qc.invalidateQueries({ queryKey: ["portals", gid] });
  void qc.invalidateQueries({ queryKey: ["stats", gid] });
  void qc.invalidateQueries({ queryKey: ["activity", gid] });
}

export function useAddPortal(gid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: PortalPayload) =>
      apiSend<Portal>("POST", `/api/groups/${gid}/portals`, payload),
    onSuccess: () => invalidatePortalData(qc, gid),
  });
}

export function useUpdatePortal(gid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ pid, patch }: { pid: number; patch: Partial<PortalPayload> }) =>
      apiSend<Portal>("PATCH", `/api/portals/${pid}`, patch),
    onSuccess: () => invalidatePortalData(qc, gid),
  });
}

export function useDeletePortal(gid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pid: number) => apiSend<{ ok: boolean }>("DELETE", `/api/portals/${pid}`),
    onSuccess: () => invalidatePortalData(qc, gid),
  });
}

export function useSetPortalStatus(gid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ pid, payload }: { pid: number; payload: PortalStatusUpsert }) =>
      apiSend<PortalStatusRow>("PUT", `/api/portals/${pid}/status`, payload),
    onSuccess: () => invalidatePortalData(qc, gid),
  });
}
