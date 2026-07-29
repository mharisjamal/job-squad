import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../lib/api";
import type {
  ApplicationFull,
  ApplicationUpsert,
  Comment,
  Company,
  CompanyDetail,
  CompanyPatch,
  CompanyPayload,
} from "../types/api";

export interface CompanyFilters {
  q?: string;
  status?: string;
  tag?: string;
}

export function useCompanies(gid: number, filters: CompanyFilters = {}) {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.status) params.set("status", filters.status);
  if (filters.tag) params.set("tag", filters.tag);
  const qs = params.toString();
  return useQuery({
    queryKey: ["companies", gid, filters],
    queryFn: () => apiGet<Company[]>(`/api/groups/${gid}/companies${qs ? `?${qs}` : ""}`),
    enabled: Number.isFinite(gid),
  });
}

export function useCompany(cid: number) {
  return useQuery({
    queryKey: ["company", cid],
    queryFn: () => apiGet<CompanyDetail>(`/api/companies/${cid}`),
    enabled: Number.isFinite(cid),
  });
}

/** Invalidate everything that shows company/application state for a group. */
function invalidateCompanyData(qc: ReturnType<typeof useQueryClient>, gid: number) {
  void qc.invalidateQueries({ queryKey: ["companies", gid] });
  void qc.invalidateQueries({ queryKey: ["company"] });
  void qc.invalidateQueries({ queryKey: ["applications", gid] });
  void qc.invalidateQueries({ queryKey: ["stats", gid] });
  void qc.invalidateQueries({ queryKey: ["portals", gid] });
  void qc.invalidateQueries({ queryKey: ["activity", gid] });
}

export function useAddCompany(gid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CompanyPayload) =>
      apiSend<Company>("POST", `/api/groups/${gid}/companies`, payload),
    onSuccess: () => invalidateCompanyData(qc, gid),
  });
}

export function useUpdateCompany(gid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ cid, patch }: { cid: number; patch: CompanyPatch }) =>
      apiSend<Company>("PATCH", `/api/companies/${cid}`, patch),
    onSuccess: () => invalidateCompanyData(qc, gid),
  });
}

export function useDeleteCompany(gid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (cid: number) => apiSend<{ ok: boolean }>("DELETE", `/api/companies/${cid}`),
    onSuccess: () => invalidateCompanyData(qc, gid),
  });
}

export function useUpsertApplication(gid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ cid, payload }: { cid: number; payload: ApplicationUpsert }) =>
      apiSend<ApplicationFull>("PUT", `/api/companies/${cid}/application`, payload),
    onSuccess: () => invalidateCompanyData(qc, gid),
  });
}

export function useRemoveApplication(gid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (cid: number) =>
      apiSend<{ ok: boolean }>("DELETE", `/api/companies/${cid}/application`),
    onSuccess: () => invalidateCompanyData(qc, gid),
  });
}

export function useAddComment(gid: number, cid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: string) =>
      apiSend<Comment>("POST", `/api/companies/${cid}/comments`, { body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["company", cid] });
      void qc.invalidateQueries({ queryKey: ["companies", gid] });
      void qc.invalidateQueries({ queryKey: ["activity", gid] });
    },
  });
}

export function useDeleteComment(gid: number, cid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (commentId: number) =>
      apiSend<{ ok: boolean }>("DELETE", `/api/comments/${commentId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["company", cid] });
      void qc.invalidateQueries({ queryKey: ["companies", gid] });
    },
  });
}
