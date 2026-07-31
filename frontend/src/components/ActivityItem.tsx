import type { Activity, ApplicationStatus, PortalMemberStatus } from "../types/api";
import { statusLabel } from "../config/statuses";
import { portalStatusLabel } from "../config/statuses";
import { Avatar } from "./ui/MemberChip";
import { timeAgo } from "../lib/format";

function detailStatus(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) return "";
  return statusLabel(value as ApplicationStatus);
}

/** Human sentence for an activity row, e.g. "moved TechCorp to Interview". */
export function activitySentence(a: Activity): string {
  const company = a.company_name ?? "a company";
  const portal = a.portal_name ?? "a portal";
  switch (a.type) {
    case "member_joined":
      return "joined the group";
    case "join_requested":
      return "asked to join the group";
    case "member_removed": {
      const removed = a.detail["removed_user_name"];
      if (typeof removed === "string" && removed.length > 0) return `removed ${removed}`;
      return "removed a member";
    }
    case "company_added":
      return `added ${company}`;
    case "portal_added":
      return `added portal ${portal}`;
    case "application_status_changed": {
      const from = a.detail["from"];
      const to = detailStatus(a.detail["to"]) || "a new status";
      if (from == null) return `set ${company} to ${to}`;
      return `moved ${company} to ${to}`;
    }
    case "application_removed":
      return `removed their application to ${company}`;
    case "comment_added":
      return `commented on ${company}`;
    case "portal_status_changed": {
      const to = a.detail["to"];
      if (to === "none") return `cleared their status on portal ${portal}`;
      const label =
        typeof to === "string" ? portalStatusLabel(to as PortalMemberStatus) : "updated";
      return `marked portal ${portal} as ${label}`;
    }
    default:
      return "did something";
  }
}

export function ActivityItem({ activity }: { activity: Activity }) {
  return (
    <div className="flex items-start gap-3 py-2.5">
      <Avatar username={activity.username} displayName={activity.display_name} size="sm" />
      <p className="min-w-0 flex-1 text-sm text-muted">
        <span className="font-medium text-ink">{activity.display_name}</span>{" "}
        {activitySentence(activity)}
      </p>
      <span className="shrink-0 font-mono text-[11px] text-muted/80">
        {timeAgo(activity.created_at)}
      </span>
    </div>
  );
}
