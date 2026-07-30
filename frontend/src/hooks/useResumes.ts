import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend, apiUpload, authedBlob } from "../lib/api";
import type { Resume, ResumeStatsRow, ShareLink } from "../types/api";

// The vault is user-scoped (it spans groups), so keys carry no gid.
// ["resumes"] prefixes ["resumes", "stats"], so one invalidation hits both.

export function useResumes() {
  return useQuery({
    queryKey: ["resumes"],
    queryFn: () => apiGet<Resume[]>("/api/resumes"),
  });
}

export function useResumeStats() {
  return useQuery({
    queryKey: ["resumes", "stats"],
    queryFn: () => apiGet<ResumeStatsRow[]>("/api/resumes/stats"),
  });
}

/** Rename/delete change resume_label on every application that carries it. */
function invalidateResumeData(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ["resumes"] });
  void qc.invalidateQueries({ queryKey: ["company"] });
  void qc.invalidateQueries({ queryKey: ["companies"] });
  void qc.invalidateQueries({ queryKey: ["applications"] });
}

export function useUploadResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ label, file }: { label: string; file: File }) => {
      const form = new FormData();
      form.append("label", label);
      form.append("file", file);
      return apiUpload<Resume>("/api/resumes", form);
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["resumes"] }),
  });
}

export function useRenameResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, label }: { id: number; label: string }) =>
      apiSend<Resume>("PATCH", `/api/resumes/${id}`, { label }),
    onSuccess: () => invalidateResumeData(qc),
  });
}

export function useDeleteResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiSend<{ ok: boolean }>("DELETE", `/api/resumes/${id}`),
    onSuccess: () => invalidateResumeData(qc),
  });
}

/**
 * Compile tailored .tex into a NEW pdf resume in the vault (plan 9b, R3). The
 * server returns 501 when no LaTeX engine is present; callers offer the .tex
 * download as the fallback in that case.
 */
export function useCompile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { tex_source: string; label: string }) =>
      apiSend<Resume>("POST", "/api/resumes/compile", vars),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["resumes"] }),
  });
}

/**
 * Create or revoke a public share link for a pdf resume (plan 9b, R3). Create
 * returns the URL (server generates the token); revoke tears it down. Both
 * refresh the vault so any share state the list shows stays current.
 */
export function useShareLink(resumeId: number) {
  const qc = useQueryClient();
  const create = useMutation({
    mutationFn: () => apiSend<ShareLink>("POST", `/api/resumes/${resumeId}/share`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["resumes"] }),
  });
  const revoke = useMutation({
    mutationFn: () => apiSend<{ ok: boolean }>("DELETE", `/api/resumes/${resumeId}/share`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["resumes"] }),
  });
  return { create, revoke };
}

/**
 * Open a resume file in a new tab: fetch with the Bearer header, hand the
 * bytes over as a short-lived blob URL, revoke once the tab has had time to
 * load. Never appends access_token to a URL. Throws ApiError on failure;
 * callers choose the toast message.
 */
export async function openResumeFile(resumeId: number): Promise<void> {
  const blob = await authedBlob(`/api/resumes/${resumeId}/file`);
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener");
  window.setTimeout(() => URL.revokeObjectURL(url), 10000);
}
