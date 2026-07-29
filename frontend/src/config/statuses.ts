import type { ApplicationStatus, PortalMemberStatus } from "../types/api";

export interface StatusMeta {
  value: ApplicationStatus;
  label: string;
  /** Badge text color. */
  text: string;
  /** Badge tint background. */
  tint: string;
  /** Leading dot / ring / column marker color. */
  dot: string;
}

// Frozen order (kanban column order) and colors from the plan, section 5.
export const STATUSES: StatusMeta[] = [
  { value: "saved", label: "Saved", text: "#475569", tint: "#F1F5F9", dot: "#64748B" },
  { value: "applied", label: "Applied", text: "#1D4ED8", tint: "#EFF6FF", dot: "#2563EB" },
  { value: "assessment", label: "Assessment", text: "#6D28D9", tint: "#F5F3FF", dot: "#7C3AED" },
  { value: "interview", label: "Interview", text: "#B45309", tint: "#FFFBEB", dot: "#D97706" },
  { value: "offer", label: "Offer", text: "#047857", tint: "#ECFDF5", dot: "#059669" },
  { value: "rejected", label: "Rejected", text: "#B91C1C", tint: "#FEF2F2", dot: "#DC2626" },
  { value: "ghosted", label: "Ghosted", text: "#52525B", tint: "#F4F4F5", dot: "#71717A" },
];

export const STATUS_META: Record<ApplicationStatus, StatusMeta> = Object.fromEntries(
  STATUSES.map((s) => [s.value, s]),
) as Record<ApplicationStatus, StatusMeta>;

export function statusLabel(status: ApplicationStatus): string {
  return STATUS_META[status]?.label ?? status;
}

export function statusMeta(status: ApplicationStatus): StatusMeta {
  return STATUS_META[status] ?? STATUSES[0];
}

export const PORTAL_STATUSES: { value: PortalMemberStatus; label: string }[] = [
  { value: "none", label: "None" },
  { value: "signed_up", label: "Signed up" },
  { value: "active", label: "Active" },
  { value: "abandoned", label: "Abandoned" },
];

export function portalStatusLabel(status: PortalMemberStatus): string {
  return PORTAL_STATUSES.find((p) => p.value === status)?.label ?? status;
}
