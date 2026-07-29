import type { LucideIcon } from "lucide-react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="card flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-canvas">
        <Icon className="h-5 w-5 text-muted" aria-hidden />
      </div>
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      {description && <p className="max-w-sm text-sm text-muted">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({
  message = "Something went wrong. Retry.",
  onRetry,
}: {
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="card flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-danger/10">
        <AlertTriangle className="h-5 w-5 text-danger" aria-hidden />
      </div>
      <p className="max-w-sm text-sm text-ink">{message}</p>
      {onRetry && (
        <button onClick={onRetry} className="btn-ghost mt-1">
          <RefreshCw className="h-4 w-4" aria-hidden />
          Retry
        </button>
      )}
    </div>
  );
}
