import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

export function Dialog({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    // Focus the first focusable control in the panel.
    const t = window.setTimeout(() => {
      const el = panelRef.current?.querySelector<HTMLElement>(
        "input, select, textarea, button:not([data-dialog-close])",
      );
      el?.focus();
    }, 0);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      window.clearTimeout(t);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      className="overlay-in fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-scrim/60 p-4 pt-[8vh] sm:items-center sm:pt-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`w-full rounded-lg border border-line bg-raised ${wide ? "max-w-2xl" : "max-w-md"} p-5 shadow-pop`}
      >
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          <button
            data-dialog-close
            onClick={onClose}
            className="rounded-md p-1.5 text-muted transition-colors hover:bg-hover hover:text-ink"
            aria-label="Close dialog"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

/** Simple confirm dialog built on Dialog. */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel = "Delete",
  busy = false,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  message: string;
  confirmLabel?: string;
  busy?: boolean;
}) {
  return (
    <Dialog open={open} onClose={onClose} title={title}>
      <p className="text-sm text-muted">{message}</p>
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button className="btn-danger" onClick={onConfirm} disabled={busy}>
          {busy ? "Working..." : confirmLabel}
        </button>
      </div>
    </Dialog>
  );
}
