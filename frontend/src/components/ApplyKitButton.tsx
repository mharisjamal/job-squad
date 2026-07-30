import { useState } from "react";
import { Rocket } from "lucide-react";
import { useUpsertApplication } from "../hooks/useCompanies";
import { useShareLink } from "../hooks/useResumes";
import { useToast } from "./ui/Toast";
import { copyToClipboard } from "../lib/clipboard";
import { safeHref } from "../lib/format";
import type { ApplicationFull } from "../types/api";

/**
 * Apply kit (plan 9b, R3): the deliberate alternative to auto-submitting to ATS
 * portals. One click opens the job posting, ensures a shareable link for the
 * attached resume and copies it, and bumps a still-"saved" application to
 * "applied". Everything after opening the posting is best-effort: if share or
 * copy is unavailable, the posting still opens and we say so plainly.
 */
export function ApplyKitButton({
  application,
  gid,
}: {
  application: ApplicationFull;
  gid: number;
}) {
  const { toast } = useToast();
  const upsert = useUpsertApplication(gid);
  const share = useShareLink(application.resume_id ?? 0);
  const [busy, setBusy] = useState(false);

  const href = safeHref(application.url);
  const ready = href != null && application.resume_id != null;

  const run = async () => {
    if (!ready || !href) return;
    // Open the posting first, inside the click, so the popup is allowed.
    window.open(href, "_blank", "noopener");
    setBusy(true);

    let copied = false;
    try {
      const link = await share.create.mutateAsync();
      copied = await copyToClipboard(link.url);
    } catch {
      copied = false;
    }

    if (application.status === "saved") {
      try {
        await upsert.mutateAsync({
          cid: application.company_id,
          payload: { status: "applied" },
        });
      } catch {
        // Non-fatal: the posting is already open; the user can set status by hand.
      }
    }

    setBusy(false);
    if (copied) {
      toast("Posting opened, resume link copied");
    } else {
      toast("Posting opened. Couldn't create a shareable resume link.", "error");
    }
    toast("Fill every field in the application form, especially Skills - recruiters search those.");
  };

  return (
    <button type="button" className="btn-ghost" onClick={run} disabled={!ready || busy}>
      <Rocket className="h-4 w-4" aria-hidden />
      {busy ? "Opening..." : "Apply kit"}
    </button>
  );
}
