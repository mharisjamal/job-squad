import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../lib/api";
import type { AiSettings, AiSettingsPut, AiTestResult } from "../types/api";

// AI settings are user-scoped (they span groups), so the key carries no gid.

export function useAiSettings() {
  return useQuery({
    queryKey: ["ai-settings"],
    queryFn: () => apiGet<AiSettings>("/api/settings/ai"),
  });
}

export function useSaveAiSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: AiSettingsPut) => apiSend<AiSettings>("PUT", "/api/settings/ai", payload),
    // Refetch the authoritative masked settings (key_set flips, key stays hidden).
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["ai-settings"] }),
  });
}

/**
 * Fires a minimal chat call against the SAVED settings server-side, so callers
 * must persist changes before testing them. Returns ok/error text either way.
 */
export function useTestAiSettings() {
  return useMutation({
    mutationFn: () => apiSend<AiTestResult>("POST", "/api/settings/ai/test"),
  });
}
