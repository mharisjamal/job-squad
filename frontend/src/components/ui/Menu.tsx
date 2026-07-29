import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import clsx from "clsx";

/** Minimal dropdown: trigger + right-aligned panel, closes on outside click / Esc. */
export function Menu({
  trigger,
  children,
  align = "right",
}: {
  trigger: (open: boolean) => ReactNode;
  children: (close: () => void) => ReactNode;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="block"
      >
        {trigger(open)}
      </button>
      {open && (
        <div
          role="menu"
          className={clsx(
            "overlay-in absolute z-40 mt-1.5 w-56 overflow-hidden rounded-lg border border-line bg-paper py-1 shadow-pop",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

export function MenuItem({
  onClick,
  children,
  danger = false,
}: {
  onClick: () => void;
  children: ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      role="menuitem"
      onClick={onClick}
      className={clsx(
        "flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-sm transition-colors duration-150 ease-out hover:bg-hover",
        danger ? "text-danger" : "text-ink",
      )}
    >
      {children}
    </button>
  );
}

export function MenuLink({
  href,
  children,
  onClick,
}: {
  href: string;
  children: ReactNode;
  onClick?: () => void;
}) {
  return (
    <a
      role="menuitem"
      href={href}
      onClick={onClick}
      className="flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-sm text-ink transition-colors duration-150 ease-out hover:bg-hover"
    >
      {children}
    </a>
  );
}
