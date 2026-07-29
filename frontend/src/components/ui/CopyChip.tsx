import { useState } from "react";
import { Check, Copy } from "lucide-react";
import clsx from "clsx";
import { useToast } from "./Toast";

/** Legacy copy path for insecure origins (LAN http) where navigator.clipboard is undefined. */
function legacyCopy(text: string): boolean {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  document.body.removeChild(ta);
  return ok;
}

/** Invite-code chip: selectable mono text + a copy button with confirmation. */
export function CopyChip({ value, className }: { value: string; className?: string }) {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    let ok = false;
    try {
      await navigator.clipboard.writeText(value);
      ok = true;
    } catch {
      ok = legacyCopy(value);
    }
    if (ok) {
      setCopied(true);
      toast("Invite code copied");
      window.setTimeout(() => setCopied(false), 2000);
    } else {
      toast("Couldn't copy the code. Select it and copy manually.", "error");
    }
  };

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-md border border-line bg-paper px-2.5 py-1 font-mono text-xs tracking-widest text-ink",
        className,
      )}
    >
      <span className="cursor-text select-all">{value}</span>
      <button
        onClick={copy}
        className="rounded p-0.5 text-muted transition-colors duration-150 ease-out hover:text-ink"
        title="Copy invite code"
        aria-label={`Copy invite code ${value}`}
      >
        {copied ? (
          <Check className="h-3 w-3 text-status-offer" aria-hidden />
        ) : (
          <Copy className="h-3 w-3" aria-hidden />
        )}
      </button>
    </span>
  );
}
