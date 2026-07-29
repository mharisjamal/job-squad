import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, sseUrl } from "../lib/api";
import type { Activity } from "../types/api";

/** Whether the group SSE stream is currently connected (shell provides it). */
export const SseStatusContext = createContext<boolean>(false);

export function useSseConnected(): boolean {
  return useContext(SseStatusContext);
}

export function useActivityFeed(gid: number, opts: { limit?: number; poll?: boolean } = {}) {
  const limit = opts.limit ?? 50;
  return useQuery({
    queryKey: ["activity", gid],
    queryFn: () => apiGet<Activity[]>(`/api/groups/${gid}/activity?limit=${limit}`),
    enabled: Number.isFinite(gid),
    refetchInterval: opts.poll ? 30000 : false,
  });
}

const MAX_BACKOFF_MS = 30000;

/**
 * Group-level SSE subscription. Mount once in the group shell so every page
 * benefits: each `activity` event prepends to the feed cache and invalidates
 * companies / stats / portals / applications queries. Returns connected state;
 * consumers fall back to 30s polling while disconnected.
 */
export function useActivitySse(gid: number): boolean {
  const qc = useQueryClient();
  const [connected, setConnected] = useState(false);
  const attemptRef = useRef(0);

  useEffect(() => {
    if (!Number.isFinite(gid)) return;
    let disposed = false;
    let es: EventSource | null = null;
    let timer: number | undefined;

    const connect = () => {
      if (disposed) return;
      es = new EventSource(sseUrl(`/api/groups/${gid}/activity/sse`));

      es.addEventListener("hello", () => {
        attemptRef.current = 0;
        setConnected(true);
      });

      es.addEventListener("activity", (ev) => {
        let item: Activity;
        try {
          item = JSON.parse((ev as MessageEvent).data) as Activity;
        } catch {
          return;
        }
        qc.setQueryData<Activity[]>(["activity", gid], (prev) => {
          if (!prev) return prev;
          if (prev.some((a) => a.id === item.id)) return prev;
          return [item, ...prev].slice(0, 100);
        });
        void qc.invalidateQueries({ queryKey: ["companies", gid] });
        void qc.invalidateQueries({ queryKey: ["company"] });
        void qc.invalidateQueries({ queryKey: ["applications", gid] });
        void qc.invalidateQueries({ queryKey: ["stats", gid] });
        void qc.invalidateQueries({ queryKey: ["portals", gid] });
        void qc.invalidateQueries({ queryKey: ["group", gid] });
      });

      es.onopen = () => {
        attemptRef.current = 0;
        setConnected(true);
      };

      es.onerror = () => {
        setConnected(false);
        es?.close();
        es = null;
        const backoff = Math.min(1000 * 2 ** attemptRef.current, MAX_BACKOFF_MS);
        attemptRef.current += 1;
        timer = window.setTimeout(connect, backoff);
      };
    };

    connect();

    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
      es?.close();
      setConnected(false);
    };
  }, [gid, qc]);

  return connected;
}
