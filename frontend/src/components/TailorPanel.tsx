import { useEffect, useState } from "react";
import { Copy, Download, Eye, FileCode2, RefreshCw, Sparkles } from "lucide-react";
import type { useTailor } from "../hooks/useTailor";
import { openResumeFile, useCompile } from "../hooks/useResumes";
import { useUpsertApplication } from "../hooks/useCompanies";
import { useToast } from "./ui/Toast";
import { Spinner } from "./ui/Spinner";
import { copyToClipboard } from "../lib/clipboard";
import { ApiError, authedBlob } from "../lib/api";
import type {
  ApplicationFull,
  Resume,
  TailorAdviceResult,
  TailorTexResult,
} from "../types/api";

type TailorMutation = ReturnType<typeof useTailor>;

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/** Filesystem-safe base name for the downloaded .tex. */
function safeFilename(name: string): string {
  const cleaned = name.replace(/[^a-z0-9._-]+/gi, "_").replace(/^_+|_+$/g, "");
  return cleaned.length > 0 ? cleaned : "resume";
}

/** A single scrollable .tex column (original or tailored). */
function TexColumn({ title, body, muted }: { title: string; body: string; muted?: boolean }) {
  return (
    <div className="min-w-0">
      <p className="mb-1.5 text-small font-medium text-muted">{title}</p>
      <pre
        className={`max-h-96 overflow-auto rounded-md border border-line bg-canvas p-3 font-mono text-[11px] leading-relaxed ${
          muted ? "text-muted" : "text-ink/90"
        }`}
      >
        {body}
      </pre>
    </div>
  );
}

function TexResult({
  result,
  application,
  gid,
}: {
  result: TailorTexResult;
  application: ApplicationFull;
  gid: number;
}) {
  const { toast } = useToast();
  const compile = useCompile();
  const upsert = useUpsertApplication(gid);

  const [originalTex, setOriginalTex] = useState<string | null>(null);
  const [originalFailed, setOriginalFailed] = useState(false);
  const [compiled, setCompiled] = useState<Resume | null>(null);
  const [compileUnavailable, setCompileUnavailable] = useState(false);

  const resumeId = application.resume_id;
  const label = `${application.resume_label ?? "Resume"} (tailored)`;

  // Fetch the attached .tex to show the before/after. The file endpoint needs
  // the Bearer header, so we read it as a blob rather than an access-token URL.
  useEffect(() => {
    let cancelled = false;
    setOriginalTex(null);
    setOriginalFailed(false);
    if (resumeId == null) {
      setOriginalFailed(true);
      return;
    }
    openResumeText(resumeId)
      .then((text) => {
        if (!cancelled) setOriginalTex(text);
      })
      .catch(() => {
        if (!cancelled) setOriginalFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [resumeId, result]);

  const downloadTex = () => {
    const blob = new Blob([result.tailored_tex], { type: "application/x-tex" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${safeFilename(label)}.tex`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.setTimeout(() => URL.revokeObjectURL(url), 10000);
  };

  const runCompile = () => {
    setCompileUnavailable(false);
    compile.mutate(
      { tex_source: result.tailored_tex, label },
      {
        onSuccess: (r) => {
          setCompiled(r);
          toast(`${r.label} added to your vault`);
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 501) {
            setCompileUnavailable(true);
          } else {
            toast(errMsg(err, "Couldn't compile the PDF. Retry."), "error");
          }
        },
      },
    );
  };

  const attach = () => {
    if (!compiled) return;
    upsert.mutate(
      { cid: application.company_id, payload: { status: application.status, resume_id: compiled.id } },
      {
        onSuccess: () => toast(`Attached ${compiled.label} to this application`),
        onError: (err) => toast(errMsg(err, "Couldn't attach the resume. Retry."), "error"),
      },
    );
  };

  return (
    <div className="space-y-5">
      <div className="grid gap-4 lg:grid-cols-2">
        {originalFailed ? (
          <div className="min-w-0">
            <p className="mb-1.5 text-small font-medium text-muted">Original</p>
            <p className="rounded-md border border-line bg-canvas p-3 text-xs text-muted">
              Couldn't load the original .tex to compare. The tailored version is shown on the right.
            </p>
          </div>
        ) : originalTex == null ? (
          <div className="min-w-0">
            <p className="mb-1.5 text-small font-medium text-muted">Original</p>
            <div className="flex h-24 items-center justify-center rounded-md border border-line bg-canvas">
              <Spinner />
            </div>
          </div>
        ) : (
          <TexColumn title="Original" body={originalTex} muted />
        )}
        <TexColumn title="Tailored" body={result.tailored_tex} />
      </div>

      {result.changes.length > 0 && (
        <div>
          <h3 className="mb-2 text-small font-medium text-ink">What changed</h3>
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink/90">
            {result.changes.map((change, i) => (
              <li key={i}>{change}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="space-y-3 border-t border-line pt-4">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="btn-primary"
            onClick={runCompile}
            disabled={compile.isPending}
          >
            <FileCode2 className="h-4 w-4" aria-hidden />
            {compile.isPending ? "Compiling..." : "Compile to PDF"}
          </button>
          <button type="button" className="btn-ghost" onClick={downloadTex}>
            <Download className="h-4 w-4" aria-hidden />
            Download .tex
          </button>
        </div>

        {compileUnavailable && (
          <p className="rounded-md border border-line bg-canvas p-3 text-xs text-muted">
            PDF compile is not available here. Download the .tex and compile it on Overleaf.
          </p>
        )}

        {compiled && (
          <div className="rounded-md border border-line bg-canvas p-3">
            <p className="text-sm text-ink">Compiled to PDF and added to your vault.</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-primary h-8 px-3 text-xs"
                onClick={attach}
                disabled={upsert.isPending}
              >
                {upsert.isPending ? "Attaching..." : "Attach to this application"}
              </button>
              <button
                type="button"
                className="btn-ghost h-8 px-3 text-xs"
                onClick={() => void openResumeFile(compiled.id)}
              >
                <Eye className="h-3.5 w-3.5" aria-hidden />
                View PDF
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** One suggestion card: section, original -> suggested, reason, per-item copy. */
function SuggestionCard({
  section,
  original,
  suggested,
  reason,
}: {
  section: string;
  original: string;
  suggested: string;
  reason: string;
}) {
  const { toast } = useToast();
  const copy = async () => {
    const ok = await copyToClipboard(suggested);
    toast(ok ? "Suggestion copied" : "Couldn't copy. Select the text manually.", ok ? "success" : "error");
  };
  return (
    <div className="rounded-lg border border-line bg-canvas p-4">
      <div className="flex items-start justify-between gap-3">
        <span className="font-mono text-[11px] uppercase tracking-wide text-muted">{section}</span>
        <button
          type="button"
          onClick={copy}
          className="inline-flex shrink-0 items-center gap-1.5 text-xs text-muted transition-colors duration-150 ease-out hover:text-ink"
        >
          <Copy className="h-3.5 w-3.5" aria-hidden />
          Copy
        </button>
      </div>
      {original.trim().length > 0 && (
        <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-muted line-through decoration-muted/40">
          {original}
        </p>
      )}
      <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-ink">{suggested}</p>
      {reason.trim().length > 0 && (
        <p className="mt-2 text-[11px] leading-relaxed text-muted">{reason}</p>
      )}
    </div>
  );
}

function AdviceResult({ result }: { result: TailorAdviceResult }) {
  const { toast } = useToast();
  const copyKeywords = async () => {
    const ok = await copyToClipboard(result.keywords_to_add.join(", "));
    toast(ok ? "Keywords copied" : "Couldn't copy. Select them manually.", ok ? "success" : "error");
  };

  return (
    <div className="space-y-5">
      <p className="text-xs leading-relaxed text-muted">
        Suggestions only. Apply the ones that are true for you; never add a skill you do not have.
      </p>

      {result.suggestions.length === 0 ? (
        <p className="text-sm text-muted">
          No rewrite suggestions came back. Your resume may already line up well with this posting.
        </p>
      ) : (
        <div className="space-y-3">
          {result.suggestions.map((s, i) => (
            <SuggestionCard
              key={i}
              section={s.section}
              original={s.original}
              suggested={s.suggested}
              reason={s.reason}
            />
          ))}
        </div>
      )}

      {result.keywords_to_add.length > 0 && (
        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-small font-medium text-ink">Keywords to add (only if true)</h3>
            <button
              type="button"
              onClick={copyKeywords}
              className="inline-flex items-center gap-1.5 text-xs text-muted transition-colors duration-150 ease-out hover:text-ink"
            >
              <Copy className="h-3.5 w-3.5" aria-hidden />
              Copy keywords
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {result.keywords_to_add.map((kw) => (
              <span
                key={kw}
                className="inline-flex items-center rounded-full bg-status-interview-bg px-2.5 py-0.5 font-mono text-[11px] font-medium text-status-interview-text"
              >
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Tailor result surface for my application (plan 9b, R3). Renders nothing until
 * a tailor run starts; then an honest 10-30s loading state, a verbatim error, or
 * the result (editable .tex before/after, or non-destructive advice cards).
 */
export function TailorPanel({
  tailor,
  application,
  gid,
}: {
  tailor: TailorMutation;
  application: ApplicationFull;
  gid: number;
}) {
  if (tailor.isIdle) return null;

  const retry = () => {
    if (application.resume_id != null) tailor.mutate(application.resume_id);
  };

  return (
    <section className="card p-5">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold text-ink">
        <Sparkles className="h-4 w-4 text-muted" aria-hidden />
        AI tailoring
      </h2>
      <p className="mb-4 text-[11px] text-muted/90">
        Rephrasing and reordering only. Nothing is invented, and nothing is saved until you act.
      </p>

      {tailor.isPending ? (
        <div className="flex items-center gap-3 py-2" aria-busy="true">
          <Spinner />
          <div>
            <p className="text-sm text-ink">Tailoring your resume...</p>
            <p className="text-xs text-muted">This usually takes 10 to 30 seconds. Keep this tab open.</p>
          </div>
        </div>
      ) : tailor.isError ? (
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm text-danger">{errMsg(tailor.error, "Couldn't tailor the resume.")}</p>
          <button
            type="button"
            onClick={retry}
            className="inline-flex items-center gap-1.5 text-xs text-muted transition-colors duration-150 ease-out hover:text-ink"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            Try again
          </button>
        </div>
      ) : !tailor.data ? null : tailor.data.kind === "tex" ? (
        <TexResult result={tailor.data} application={application} gid={gid} />
      ) : (
        <AdviceResult result={tailor.data} />
      )}
    </section>
  );
}

/** Fetch a resume file as text (used for the .tex before/after). */
async function openResumeText(resumeId: number): Promise<string> {
  const blob = await authedBlob(`/api/resumes/${resumeId}/file`);
  return blob.text();
}
