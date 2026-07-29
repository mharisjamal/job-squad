import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { ApplicationFull } from "../types/api";

/** My applications in a group (board + dashboard follow-ups). */
export function useMyApplications(gid: number) {
  return useQuery({
    queryKey: ["applications", gid, "me"],
    queryFn: () => apiGet<ApplicationFull[]>(`/api/groups/${gid}/applications?user_id=me`),
    enabled: Number.isFinite(gid),
  });
}
