import { Loader2 } from "lucide-react";
import clsx from "clsx";

export function Spinner({ className }: { className?: string }) {
  return (
    <Loader2
      className={clsx("h-5 w-5 animate-spin text-muted", className)}
      aria-label="Loading"
      role="status"
    />
  );
}

/** Full-area centered spinner for page-level loading. */
export function PageSpinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 text-muted">
      <Spinner className="h-6 w-6" />
      <p className="text-sm">{label}</p>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-lg bg-pill", className)} aria-hidden />;
}
