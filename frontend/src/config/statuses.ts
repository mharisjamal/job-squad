import type { ApplicationStatus, PortalMemberStatus } from "../types/api";

export interface StatusMeta {
  value: ApplicationStatus;
  label: string;
  /** Badge text color (CSS value referencing the themed variable). */
  text: string;
  /** Badge tint background. */
  tint: string;
  /** Leading dot / avatar ring / column marker color. */
  dot: string;
}

const color = (name: string) => `rgb(var(--status-${name}))`;

const meta = (value: ApplicationStatus, label: string): StatusMeta => ({
  value,
  label,
  text: color(`${value}-text`),
  tint: color(`${value}-bg`),
  dot: color(`${value}-dot`),
});

// Frozen order (kanban column order) and labels from the plan, section 5.
// The color values are per-theme CSS variables, never hexes.
export const STATUSES: StatusMeta[] = [
  meta("saved", "Saved"),
  meta("applied", "Applied"),
  meta("assessment", "Assessment"),
  meta("interview", "Interview"),
  meta("offer", "Offer"),
  meta("rejected", "Rejected"),
  meta("ghosted", "Ghosted"),
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
