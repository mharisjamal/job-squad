import { useState } from "react";
import { Check, Copy } from "lucide-react";
import clsx from "clsx";
import { useToast } from "./Toast";

/** Invite-code chip: mono text, click to copy with confirmation. */
export function CopyChip({ value, className }: { value: string; className?: string }) {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      toast("Invite code copied");
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast("Couldn't copy the code. Select and copy it manually.", "error");
    }
  };

  return (
    <button
      onClick={copy}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-md border border-line bg-paper px-2.5 py-1 font-mono text-xs tracking-widest text-ink transition-colors duration-150 ease-out hover:bg-hover",
        className,
      )}
      title="Copy invite code"
      aria-label={`Copy invite code ${value}`}
    >
      {value}
      {copied ? (
        <Check className="h-3 w-3 text-status-offer" aria-hidden />
      ) : (
        <Copy className="h-3 w-3 text-muted" aria-hidden />
      )}
    </button>
  );
}
