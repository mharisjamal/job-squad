import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../lib/api";
import type { ExtensionToken, ExtensionTokenCreated } from "../types/api";

// Extension tokens are user-scoped (one pairing works across every group),
// so the query key carries no gid.

const KEY = ["extension-tokens"];

/** Paired browsers for the signed-in user. Never includes the token value. */
export function useExtensionTokens() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => apiGet<ExtensionToken[]>("/api/auth/extension-tokens"),
  });
}

/**
 * Mints a pairing token. The value is returned once and is handed straight to
 * the extension via postMessage by the caller: do not store, render or log it.
 * Always pass a label: without one the list is a row of identical dates and
 * the user cannot tell which connection to revoke.
 */
export function useCreateExtensionToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (label?: string) =>
      apiSend<ExtensionTokenCreated>("POST", "/api/auth/extension-token", label ? { label } : {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: KEY }),
  });
}

/** Revokes one pairing; that browser stops being able to add jobs immediately. */
export function useRevokeExtensionToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiSend<{ ok: boolean }>("DELETE", `/api/auth/extension-tokens/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: KEY }),
  });
}

/**
 * Fire-and-forget revoke of a connection the extension told us it replaced.
 * The pairing already succeeded, so a failure here (already revoked, gone)
 * must stay silent and must never affect what the page shows.
 */
export async function revokeSupersededToken(id: number): Promise<void> {
  try {
    await apiSend<{ ok: boolean }>("DELETE", `/api/auth/extension-tokens/${id}`);
  } catch {
    // Nothing to tell the user: the connection they asked for is live.
  }
}
