import { Copy, RefreshCw, Target } from "lucide-react";
import { useMatch } from "../hooks/useMatch";
import { useToast } from "./ui/Toast";
import { Skeleton } from "./ui/Spinner";
import { copyToClipboard } from "../lib/clipboard";
import { ApiError } from "../lib/api";
import type { ApplicationFull, MatchReport } from "../types/api";

/** Guidance framing, not a target: 100% coverage reads as keyword stuffing. */
function coverageLabel(pct: number): string {
  if (pct >= 80) return "Strong";
  if (pct >= 70) return "Good";
  return "Keep tailoring";
}

/** Small tint pill for a single skill, colored by whether the resume covers it. */
function SkillChip({ skill, present }: { skill: string; present: boolean }) {
  return (
    <span
      className={
        present
          ? "inline-flex items-center rounded-full bg-status-offer-bg px-2.5 py-0.5 font-mono text-[11px] font-medium text-status-offer-text"
          : "inline-flex items-center rounded-full bg-status-interview-bg px-2.5 py-0.5 font-mono text-[11px] font-medium text-status-interview-text"
      }
    >
      {skill}
    </span>
  );
}

/** The quiet, non-error state: not enough saved yet to compute a match. */
function MatchPrompt({ message }: { message: string }) {
  return <p className="text-sm text-muted">{message}</p>;
}

/**
 * Calm notice (muted/line tokens, not an error) for an image-only/scanned
 * resume: no text could be extracted, so a coverage number would be a false 0%.
 * We deliberately hide the skills list here so nothing reads as a real match.
 */
function ResumeUnreadableNotice() {
  return (
    <div className="rounded-md border border-line bg-canvas p-4">
      <h3 className="text-sm font-medium text-ink">Couldn't read this resume</h3>
      <p className="mt-1 text-xs leading-relaxed text-muted">
        This resume looks image-only, so we couldn't extract its text to compare. Upload a
        text-based PDF (exported from a document, not a scan) or a .tex file to see the match.
      </p>
    </div>
  );
}

function MatchResult({ report }: { report: MatchReport }) {
  const { toast } = useToast();
  const total = report.jd_skills.length;
  const present = report.jd_skills.filter((s) => s.present);
  const missing = report.missing;
  const pct = Math.max(0, Math.min(100, Math.round(report.coverage)));

  // Image-only resume: no extractable text, so any coverage would be a false
  // 0%. Show the notice and nothing else (skills list stays hidden).
  if (report.resume_text_available === false) {
    return <ResumeUnreadableNotice />;
  }

  if (total === 0) {
    return (
      <MatchPrompt message="No known skills were detected in this job description. Paste the full posting to get a match." />
    );
  }

  const copyMissing = async () => {
    const ok = await copyToClipboard(missing.join(", "));
    toast(
      ok ? "Missing skills copied" : "Couldn't copy. Select the chips and copy manually.",
      ok ? "success" : "error",
    );
  };

  return (
    <div className="space-y-5">
      {/* Coverage: a thin, monochrome bar. The qualitative label frames it as
          guidance so nobody chases 100% (which reads as stuffing). */}
      <div>
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-small font-medium text-muted">Coverage</span>
          <span className="font-mono text-xs text-muted">
            {present.length} of {total} skills
          </span>
        </div>
        <div
          className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-line"
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Skill coverage"
        >
          <div
            className="h-full rounded-full bg-ink transition-[width] duration-150 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="mt-1.5 flex items-baseline gap-2">
          <span className="font-mono text-sm text-ink">{pct}%</span>
          <span className="text-xs text-muted">{coverageLabel(pct)}</span>
        </div>
      </div>

      {/* Already covered */}
      <div>
        <h3 className="mb-2 text-small font-medium text-ink">Already covered</h3>
        {present.length === 0 ? (
          <p className="text-xs text-muted">
            None of the listed skills matched your resume yet.
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {present.map((s) => (
              <SkillChip key={s.skill} skill={s.skill} present />
            ))}
          </div>
        )}
      </div>

      {/* Gaps to consider - honest framing, never "cram these in" */}
      <div>
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-small font-medium text-ink">Gaps to consider</h3>
          {missing.length > 0 && (
            <button
              type="button"
              onClick={copyMissing}
              className="inline-flex items-center gap-1.5 text-xs text-muted transition-colors duration-150 ease-out hover:text-ink"
            >
              <Copy className="h-3.5 w-3.5" aria-hidden />
              Copy missing skills
            </button>
          )}
        </div>
        <p className="mb-2.5 text-xs text-muted">
          Only add a skill if you genuinely have it. Stuffing keywords gets flagged by modern ATS.
        </p>
        {missing.length === 0 ? (
          <p className="text-xs text-muted">
            No gaps: your resume covers every skill this posting names.
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {missing.map((skill) => (
              <SkillChip key={skill} skill={skill} present={false} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Match panel for my application (plan 9b, R2). Reads the SAVED application:
 * the report needs jd_text and an attached resume persisted server-side, so
 * this fetches only when both are present and shows a quiet prompt otherwise.
 */
export function MatchPanel({ application }: { application: ApplicationFull }) {
  const hasResume = application.resume_id != null;
  const hasJd = (application.jd_text?.trim().length ?? 0) > 0;
  const ready = hasResume && hasJd;
  const match = useMatch(application.id, ready);

  return (
    <section className="card p-5">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold text-ink">
        <Target className="h-4 w-4 text-muted" aria-hidden />
        Match
      </h2>
      <p className="mb-4 text-[11px] text-muted/90">
        How your attached resume lines up with this job description.
      </p>

      {!ready ? (
        <MatchPrompt message="Paste a job description and attach a resume to see your match." />
      ) : match.isPending ? (
        <div className="space-y-4" aria-busy="true">
          <Skeleton className="h-1.5 w-full" />
          <div className="flex flex-wrap gap-1.5">
            <Skeleton className="h-5 w-16" />
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-5 w-14" />
            <Skeleton className="h-5 w-24" />
          </div>
        </div>
      ) : match.isError ? (
        match.error instanceof ApiError && match.error.status === 409 ? (
          // The server confirms a JD or resume is still missing: quiet prompt,
          // never an error toast.
          <MatchPrompt message="Paste a job description and attach a resume to see your match." />
        ) : (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-muted">Couldn't build the match report.</p>
            <button
              type="button"
              onClick={() => match.refetch()}
              className="inline-flex items-center gap-1.5 text-xs text-muted transition-colors duration-150 ease-out hover:text-ink"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              Retry
            </button>
          </div>
        )
      ) : (
        <MatchResult report={match.data} />
      )}
    </section>
  );
}
