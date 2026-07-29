import type { ApplicationStatus } from "../../types/api";
import { statusMeta } from "../../config/statuses";
import clsx from "clsx";

/** Badge = tint bg + status text color + small leading dot, mono font. */
export function StatusBadge({
  status,
  className,
}: {
  status: ApplicationStatus;
  className?: string;
}) {
  const meta = statusMeta(status);
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-xs font-medium",
        className,
      )}
      style={{ color: meta.text, backgroundColor: meta.tint }}
    >
      <span
        className="h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: meta.dot }}
        aria-hidden
      />
      {meta.label}
    </span>
  );
}

export function StatusDot({
  status,
  className,
}: {
  status: ApplicationStatus;
  className?: string;
}) {
  return (
    <span
      className={clsx("inline-block h-2 w-2 rounded-full", className)}
      style={{ backgroundColor: statusMeta(status).dot }}
      aria-hidden
    />
  );
}
