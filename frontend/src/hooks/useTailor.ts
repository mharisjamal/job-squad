import { useMutation } from "@tanstack/react-query";
import { apiSend } from "../lib/api";
import type { TailorResult } from "../types/api";

/**
 * BYOK AI tailoring for one of my applications (plan 9b, R3). The call reads the
 * saved jd_text + the passed resume server-side and takes 10-30s, so callers
 * surface an honest loading state. The result is either an editable .tex or a
 * list of non-destructive suggestions; nothing is persisted until the user acts.
 */
export function useTailor(applicationId: number | null) {
  return useMutation({
    mutationFn: (resumeId: number) =>
      apiSend<TailorResult>("POST", `/api/applications/${applicationId}/tailor`, {
        resume_id: resumeId,
      }),
  });
}
