import clsx from "clsx";
import { Globe, Lock } from "lucide-react";
import type { GroupVisibility } from "../../types/api";

/**
 * Small chip stating whether a group is private or public. Private stays in the
 * muted monochrome; public borrows the focus blue subtly (it is the one place a
 * group is exposed to strangers, so it earns a hint of color).
 */
export function VisibilityChip({
  visibility,
  className,
}: {
  visibility: GroupVisibility;
  className?: string;
}) {
  const isPublic = visibility === "public";
  const Icon = isPublic ? Globe : Lock;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[11px]",
        isPublic
          ? "border-focus/30 bg-focus/10 text-focus"
          : "border-line bg-canvas text-muted",
        className,
      )}
    >
      <Icon className="h-3 w-3" aria-hidden />
      {isPublic ? "Public" : "Private"}
    </span>
  );
}

const OPTIONS: { value: GroupVisibility; label: string; hint: string }[] = [
  { value: "private", label: "Private", hint: "Code-only, hidden from discover" },
  { value: "public", label: "Public", hint: "Listed in discover, join by request" },
];

/**
 * Private / public segmented control. Selection reads as a lightness step (the
 * active segment sits on the lighter `paper` over the `canvas` track), so it
 * works in both themes without a saturated fill.
 */
export function VisibilityToggle({
  value,
  onChange,
  disabled = false,
}: {
  value: GroupVisibility;
  onChange: (v: GroupVisibility) => void;
  disabled?: boolean;
}) {
  return (
    <div
      className="inline-flex rounded-md border border-line bg-canvas p-0.5"
      role="radiogroup"
      aria-label="Group visibility"
    >
      {OPTIONS.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            title={opt.hint}
            onClick={() => onChange(opt.value)}
            className={clsx(
              "rounded px-3 py-1 text-sm font-medium transition-colors duration-150 ease-out",
              "disabled:pointer-events-none disabled:opacity-50",
              active ? "bg-paper text-ink" : "text-muted hover:text-ink",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
