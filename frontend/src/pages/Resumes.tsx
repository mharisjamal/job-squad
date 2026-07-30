import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { Check, Copy, Eye, FileText, Link2, Pencil, Trash2, Upload } from "lucide-react";
import {
  openResumeFile,
  useDeleteResume,
  useRenameResume,
  useResumes,
  useResumeStats,
  useShareLink,
  useUploadResume,
} from "../hooks/useResumes";
import { useToast } from "../components/ui/Toast";
import { ConfirmDialog } from "../components/ui/Dialog";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Spinner";
import { copyToClipboard } from "../lib/clipboard";
import { formatBytes, timeAgo } from "../lib/format";
import { ApiError } from "../lib/api";
import type { Resume, ResumeStatsRow } from "../types/api";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/** Kind badge: mono, 1px line border, no color (the design's quiet data chip). */
function KindBadge({ kind }: { kind: Resume["kind"] }) {
  return (
    <span className="shrink-0 rounded border border-line px-1.5 py-0.5 font-mono text-[11px] font-medium uppercase text-muted">
      {kind}
    </span>
  );
}

/** "8 applications · 3 interviews · 1 offer" - zero segments omitted. */
function outcomeLine(row: ResumeStatsRow | undefined): string {
  if (!row || row.applications === 0) return "";
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const parts = [plural(row.applications, "application")];
  if (row.interviews > 0) parts.push(plural(row.interviews, "interview"));
  if (row.offers > 0) parts.push(plural(row.offers, "offer"));
  if (row.rejected > 0) parts.push(`${row.rejected} rejected`);
  if (row.ghosted > 0) parts.push(`${row.ghosted} ghosted`);
  return parts.join(" · ");
}

function UploadCard() {
  const upload = useUploadResume();
  const { toast } = useToast();
  const [label, setLabel] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = label.trim();
    if (!file || !trimmed) return;
    upload.mutate(
      { label: trimmed, file },
      {
        onSuccess: (r) => {
          toast(`${r.label} uploaded`);
          setLabel("");
          setFile(null);
          if (fileRef.current) fileRef.current.value = "";
        },
        // 413/409/422 messages from the server surface verbatim.
        onError: (err) => toast(errMsg(err, "Couldn't upload the resume. Retry."), "error"),
      },
    );
  };

  return (
    <section className="card p-5">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold text-ink">
        <Upload className="h-4 w-4 text-muted" aria-hidden />
        Add a resume
      </h2>
      <p className="mb-4 text-small text-muted">PDF, TEX, or DOCX, up to 2 MB. You can keep up to 10.</p>
      <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <label htmlFor="resume-label" className="label">
            Label
          </label>
          <input
            id="resume-label"
            className="input"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="v2 backend-focused"
            maxLength={80}
            required
          />
        </div>
        <div className="min-w-0 sm:w-64">
          <label htmlFor="resume-file" className="label">
            File
          </label>
          <input
            ref={fileRef}
            id="resume-file"
            type="file"
            accept=".pdf,.tex,.docx"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            className="btn-ghost w-full justify-start font-normal"
            onClick={() => fileRef.current?.click()}
          >
            <FileText className="h-4 w-4 shrink-0 text-muted" aria-hidden />
            <span className={file ? "truncate text-ink" : "truncate text-muted"}>
              {file ? file.name : "Choose a file"}
            </span>
          </button>
        </div>
        <button
          type="submit"
          className="btn-primary shrink-0"
          disabled={upload.isPending || !file || label.trim().length === 0}
        >
          {upload.isPending ? "Uploading..." : "Upload resume"}
        </button>
      </form>
    </section>
  );
}

function ResumeRow({ resume, stats }: { resume: Resume; stats: ResumeStatsRow | undefined }) {
  const rename = useRenameResume();
  const del = useDeleteResume();
  const { toast } = useToast();

  const share = useShareLink(resume.id);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(resume.label);
  const cancelRef = useRef(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [viewing, setViewing] = useState(false);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const getLink = () =>
    share.create.mutate(undefined, {
      onSuccess: (link) => {
        setShareUrl(link.url);
        toast("Share link ready");
      },
      onError: (err) => toast(errMsg(err, "Couldn't create a share link. Retry."), "error"),
    });

  const copyLink = async () => {
    if (!shareUrl) return;
    const ok = await copyToClipboard(shareUrl);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }
    toast(ok ? "Share link copied" : "Couldn't copy. Select it manually.", ok ? "success" : "error");
  };

  const revokeLink = () =>
    share.revoke.mutate(undefined, {
      onSuccess: () => {
        setShareUrl(null);
        toast("Share link revoked");
      },
      onError: (err) => toast(errMsg(err, "Couldn't revoke the link. Retry."), "error"),
    });

  const commit = () => {
    setEditing(false);
    const next = draft.trim();
    if (!next || next === resume.label) return;
    rename.mutate(
      { id: resume.id, label: next },
      { onError: (err) => toast(errMsg(err, "Couldn't rename the resume. Retry."), "error") },
    );
  };

  const view = async () => {
    setViewing(true);
    try {
      await openResumeFile(resume.id);
    } catch (err) {
      setViewing(false);
      toast(errMsg(err, "Couldn't open the file. Retry."), "error");
      return;
    }
    setViewing(false);
  };

  const outcome = outcomeLine(stats);
  const attachedLine =
    resume.attached_count === 0
      ? "not attached yet"
      : `attached to ${resume.attached_count} application${resume.attached_count === 1 ? "" : "s"}`;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {editing ? (
            <input
              className="input h-7 w-full max-w-64 px-2 py-0 text-sm"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.currentTarget.blur();
                if (e.key === "Escape") {
                  cancelRef.current = true;
                  e.currentTarget.blur();
                }
              }}
              onBlur={() => {
                if (cancelRef.current) {
                  cancelRef.current = false;
                  setEditing(false);
                  setDraft(resume.label);
                  return;
                }
                commit();
              }}
              maxLength={80}
              aria-label={`New label for ${resume.label}`}
              autoFocus
            />
          ) : (
            <>
              <span className="truncate text-sm font-medium text-ink">{resume.label}</span>
              <button
                onClick={() => {
                  setDraft(resume.label);
                  setEditing(true);
                }}
                className="shrink-0 rounded p-0.5 text-muted/70 transition-colors duration-150 ease-out hover:text-ink"
                aria-label={`Rename ${resume.label}`}
              >
                <Pencil className="h-3.5 w-3.5" aria-hidden />
              </button>
            </>
          )}
          <KindBadge kind={resume.kind} />
        </div>
        <p className="mt-1 font-mono text-[11px] text-muted">
          {formatBytes(resume.size_bytes)} · uploaded {timeAgo(resume.created_at)} · {attachedLine}
        </p>
        {outcome && <p className="mt-0.5 font-mono text-[11px] text-muted/80">{outcome}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <button className="btn-ghost h-8 px-2.5 text-xs" onClick={view} disabled={viewing}>
          <Eye className="h-3.5 w-3.5" aria-hidden />
          {viewing ? "Opening..." : "View"}
        </button>
        {resume.kind === "pdf" && shareUrl == null && (
          <button
            className="btn-ghost h-8 px-2.5 text-xs"
            onClick={getLink}
            disabled={share.create.isPending}
          >
            <Link2 className="h-3.5 w-3.5" aria-hidden />
            {share.create.isPending ? "Creating..." : "Get share link"}
          </button>
        )}
        <button
          className="btn-ghost h-8 px-2.5 text-xs text-danger"
          onClick={() => setConfirmDelete(true)}
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden />
          Delete
        </button>
      </div>

      {shareUrl != null && (
        <div className="flex w-full flex-wrap items-center gap-2 rounded-md border border-line bg-canvas p-2.5">
          <Link2 className="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden />
          <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-ink" title={shareUrl}>
            {shareUrl}
          </span>
          <button className="btn-ghost h-7 px-2 text-xs" onClick={copyLink}>
            {copied ? (
              <Check className="h-3.5 w-3.5 text-status-offer-text" aria-hidden />
            ) : (
              <Copy className="h-3.5 w-3.5" aria-hidden />
            )}
            {copied ? "Copied" : "Copy"}
          </button>
          <button
            className="btn-ghost h-7 px-2 text-xs text-danger"
            onClick={revokeLink}
            disabled={share.revoke.isPending}
          >
            {share.revoke.isPending ? "Revoking..." : "Revoke"}
          </button>
        </div>
      )}

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() =>
          del.mutate(resume.id, {
            onSuccess: () => {
              setConfirmDelete(false);
              toast(`${resume.label} deleted`);
            },
            onError: (err) => {
              setConfirmDelete(false);
              toast(errMsg(err, "Couldn't delete the resume. Retry."), "error");
            },
          })
        }
        title={`Delete ${resume.label}`}
        message={
          resume.attached_count > 0
            ? `${resume.attached_count} application${resume.attached_count === 1 ? "" : "s"} will lose ${resume.attached_count === 1 ? "its" : "their"} attached resume. The file is removed from your vault and cannot be recovered.`
            : "This removes the file from your vault. This cannot be undone."
        }
        confirmLabel="Delete resume"
        busy={del.isPending}
      />
    </div>
  );
}

export default function Resumes() {
  const resumes = useResumes();
  const stats = useResumeStats();

  // Stats are quiet decoration; a stats error never blocks the vault.
  const statsById = new Map((stats.data ?? []).map((r) => [r.resume_id, r]));

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink">Resumes</h1>
        <p className="text-sm text-muted">
          Your vault spans all your groups. Attach one to an application from a company page.
        </p>
      </div>

      <UploadCard />

      {resumes.isPending ? (
        <div className="space-y-2">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      ) : resumes.isError ? (
        <ErrorState message="Couldn't load your resumes. Retry." onRetry={() => resumes.refetch()} />
      ) : resumes.data.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No resumes yet"
          description="Upload the one you send most, then attach it to your applications."
        />
      ) : (
        <div className="card divide-y divide-line">
          {resumes.data.map((r) => (
            <ResumeRow key={r.id} resume={r} stats={statsById.get(r.id)} />
          ))}
        </div>
      )}
    </div>
  );
}
