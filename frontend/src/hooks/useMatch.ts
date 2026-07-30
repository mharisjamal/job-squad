import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { MatchReport } from "../types/api";

/**
 * Deterministic JD <-> resume match for one of my applications (plan 9b, R2).
 * Only fetch when the caller knows the application carries both a JD and an
 * attached resume; the server returns 409 otherwise, which the panel renders
 * as a quiet prompt rather than an error. The query key is invalidated by the
 * application upsert (see useCompanies) so a fresh save re-runs the match.
 */
export function useMatch(applicationId: number | null, ready: boolean) {
  return useQuery({
    queryKey: ["match", applicationId],
    queryFn: () => apiGet<MatchReport>(`/api/applications/${applicationId}/match`),
    enabled: ready && applicationId != null,
  });
}
