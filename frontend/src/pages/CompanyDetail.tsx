import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Briefcase,
  CalendarClock,
  ExternalLink,
  Globe,
  MessageSquare,
  Pencil,
  Send,
  StickyNote,
  Trash2,
  Users,
} from "lucide-react";
import { useGroupCtx } from "../components/layout/Shell";
import { useAuth } from "../hooks/useAuth";
import {
  useAddComment,
  useCompany,
  useDeleteComment,
  useDeleteCompany,
  useRemoveApplication,
  useUpdateCompany,
  useUpsertApplication,
} from "../hooks/useCompanies";
import { usePortals } from "../hooks/usePortals";
import { useToast } from "../components/ui/Toast";
import { CompanyFormDialog } from "../components/CompanyFormDialog";
import { ConfirmDialog } from "../components/ui/Dialog";
import { StatusBadge } from "../components/ui/StatusBadge";
import { Avatar } from "../components/ui/MemberChip";
import { ErrorState } from "../components/ui/EmptyState";
import { PageSpinner } from "../components/ui/Spinner";
import { STATUSES } from "../config/statuses";
import { formatDate, normalizeUrl, safeHref, timeAgo } from "../lib/format";
import { ApiError } from "../lib/api";
import type { ApplicationFull, ApplicationStatus } from "../types/api";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/** External-link chip; falls back to plain text when the URL is not http(s). */
function LinkChip({ icon: Icon, label, url }: { icon: typeof Globe; label: string; url: string }) {
  const href = safeHref(url);
  if (!href) {
    return (
      <span className="inline-flex max-w-60 items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-xs text-muted">
        <Icon className="h-3 w-3" aria-hidden />
        <span className="truncate">{url}</span>
      </span>
    );
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-xs font-medium text-ink transition-colors duration-150 ease-out hover:bg-hover"
    >
      <Icon className="h-3 w-3 text-muted" aria-hidden />
      {label}
      <ExternalLink className="h-3 w-3 text-muted" aria-hidden />
    </a>
  );
}

/** Quiet "Posting" link on a squad card; plain text when the URL is unsafe. */
function PostingLink({ url }: { url: string }) {
  const href = safeHref(url);
  if (!href) {
    return (
      <span className="inline-flex min-w-0 items-center gap-1.5">
        <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
        <span className="truncate">{url}</span>
      </span>
    );
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1.5 text-muted transition-colors duration-150 ease-out hover:text-ink hover:underline"
    >
      <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
      Posting
    </a>
  );
}

function MyApplicationEditor({
  gid,
  cid,
  mine,
}: {
  gid: number;
  cid: number;
  mine: ApplicationFull | null;
}) {
  const upsert = useUpsertApplication(gid);
  const removeApp = useRemoveApplication(gid);
  const portals = usePortals(gid);
  const { toast } = useToast();

  const [status, setStatus] = useState<ApplicationStatus>("saved");
  const [appliedAt, setAppliedAt] = useState("");
  const [followUpAt, setFollowUpAt] = useState("");
  const [portalId, setPortalId] = useState("");
  const [url, setUrl] = useState("");
  const [notes, setNotes] = useState("");
  const [confirmRemove, setConfirmRemove] = useState(false);

  // Sync the form whenever my server-side row changes identity or version.
  useEffect(() => {
    setStatus(mine?.status ?? "saved");
    setAppliedAt(mine?.applied_at ?? "");
    setFollowUpAt(mine?.follow_up_at ?? "");
    setPortalId(mine?.applied_via_portal_id != null ? String(mine.applied_via_portal_id) : "");
    setUrl(mine?.url ?? "");
    setNotes(mine?.notes ?? "");
  }, [mine?.id, mine?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = (e: FormEvent) => {
    e.preventDefault();
    upsert.mutate(
      {
        cid,
        payload: {
          status,
          applied_via_portal_id: portalId ? Number(portalId) : null,
          applied_at: appliedAt || null,
          follow_up_at: followUpAt || null,
          url: normalizeUrl(url) || null,
          notes: notes.trim() || null,
        },
      },
      {
        onSuccess: () => toast("Application saved"),
        onError: (err) => toast(errMsg(err, "Couldn't save your application. Retry."), "error"),
      },
    );
  };

  return (
    <section className="card p-5">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-ink">
        <Briefcase className="h-4 w-4 text-muted" aria-hidden />
        My application
      </h2>
      <form onSubmit={save} className="space-y-4">
        <div>
          <label htmlFor="app-status" className="label">
            Status
          </label>
          <select
            id="app-status"
            className="input font-mono"
            value={status}
            onChange={(e) => setStatus(e.target.value as ApplicationStatus)}
          >
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="app-applied-at" className="label">
              Applied on
            </label>
            <input
              id="app-applied-at"
              type="date"
              className="input font-mono"
              value={appliedAt}
              onChange={(e) => setAppliedAt(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="app-follow-up" className="label">
              Follow up on
            </label>
            <input
              id="app-follow-up"
              type="date"
              className="input font-mono"
              value={followUpAt}
              onChange={(e) => setFollowUpAt(e.target.value)}
            />
          </div>
        </div>
        <div>
          <label htmlFor="app-portal" className="label">
            Applied via
          </label>
          <select
            id="app-portal"
            className="input"
            value={portalId}
            onChange={(e) => setPortalId(e.target.value)}
          >
            <option value="">Not via a portal</option>
            {(portals.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="app-url" className="label">
            Posting URL
          </label>
          <input
            id="app-url"
            className="input"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Link to the exact job posting"
            inputMode="url"
          />
        </div>
        <div>
          <label htmlFor="app-notes" className="label">
            My notes
          </label>
          <textarea
            id="app-notes"
            className="input min-h-24 resize-y"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Interview prep, contacts, salary asks..."
            rows={4}
          />
          <p className="mt-1 text-[11px] text-muted/90">Notes are visible to your group.</p>
        </div>
        <div className="flex items-center justify-between gap-2">
          {mine ? (
            <button
              type="button"
              className="btn-ghost text-danger"
              onClick={() => setConfirmRemove(true)}
              disabled={removeApp.isPending}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
              Remove application
            </button>
          ) : (
            <span className="text-xs text-muted">You have not applied yet.</span>
          )}
          <button type="submit" className="btn-primary" disabled={upsert.isPending}>
            {upsert.isPending ? "Saving..." : "Save application"}
          </button>
        </div>
      </form>

      <ConfirmDialog
        open={confirmRemove}
        onClose={() => setConfirmRemove(false)}
        onConfirm={() =>
          removeApp.mutate(cid, {
            onSuccess: () => {
              setConfirmRemove(false);
              toast("Application removed");
            },
            onError: (err) => {
              setConfirmRemove(false);
              toast(errMsg(err, "Couldn't remove your application. Retry."), "error");
            },
          })
        }
        title="Remove my application"
        message="This deletes your status, dates, and notes for this company. The company stays in the squad pool."
        confirmLabel="Remove application"
        busy={removeApp.isPending}
      />
    </section>
  );
}

export default function CompanyDetail() {
  const { gid, group } = useGroupCtx();
  const { user } = useAuth();
  const params = useParams();
  const cid = Number(params.cid);
  const navigate = useNavigate();
  const { toast } = useToast();

  const company = useCompany(cid);
  const updateCompany = useUpdateCompany(gid);
  const deleteCompany = useDeleteCompany(gid);
  const addComment = useAddComment(gid, cid);
  const deleteComment = useDeleteComment(gid, cid);

  const [editOpen, setEditOpen] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [sharedNotes, setSharedNotes] = useState("");
  const [notesDirty, setNotesDirty] = useState(false);
  const [commentBody, setCommentBody] = useState("");

  useEffect(() => {
    if (company.data && !notesDirty) setSharedNotes(company.data.notes ?? "");
  }, [company.data, notesDirty]);

  if (company.isPending) return <PageSpinner label="Loading company" />;
  if (company.isError || !company.data) {
    return (
      <ErrorState
        message="Couldn't load this company. It may have been deleted. Retry."
        onRetry={() => company.refetch()}
      />
    );
  }

  const c = company.data;
  const mine = c.applications.find((a) => a.user_id === user?.id) ?? null;
  const canDelete = user != null && (c.created_by === user.id || group.owner_id === user.id);

  const saveNotes = () => {
    updateCompany.mutate(
      { cid, patch: { notes: sharedNotes.trim() || null } },
      {
        onSuccess: () => {
          setNotesDirty(false);
          toast("Shared notes saved");
        },
        onError: (err) => toast(errMsg(err, "Couldn't save shared notes. Retry."), "error"),
      },
    );
  };

  const submitComment = (e: FormEvent) => {
    e.preventDefault();
    const body = commentBody.trim();
    if (!body) return;
    addComment.mutate(body, {
      onSuccess: () => setCommentBody(""),
      onError: (err) => toast(errMsg(err, "Couldn't post the comment. Retry."), "error"),
    });
  };

  return (
    <div className="space-y-5">
      <Link
        to={`/g/${gid}/companies`}
        className="inline-flex items-center gap-1.5 text-sm text-muted transition-colors duration-150 ease-out hover:text-ink"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        Back to companies
      </Link>

      {/* Header */}
      <div className="card p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold tracking-tight text-ink">{c.name}</h1>
            <p className="mt-1 text-sm text-muted">
              {c.location ? `${c.location} - ` : ""}
              posted by {c.created_by_username} {timeAgo(c.created_at)}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {c.website && <LinkChip icon={Globe} label="Website" url={c.website} />}
              {c.careers_url && <LinkChip icon={Briefcase} label="Careers" url={c.careers_url} />}
              {c.tags.map((t) => (
                <span
                  key={t}
                  className="rounded-full bg-canvas px-2 py-0.5 font-mono text-[11px] text-muted"
                >
                  {t}
                </span>
              ))}
            </div>
          </div>
          <div className="flex gap-2">
            <button
              className="btn-ghost"
              onClick={() => {
                setEditError(null);
                setEditOpen(true);
              }}
            >
              <Pencil className="h-4 w-4" aria-hidden />
              Edit company
            </button>
            {canDelete && (
              <button className="btn-ghost text-danger" onClick={() => setConfirmDelete(true)}>
                <Trash2 className="h-4 w-4" aria-hidden />
                Delete
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Squad status */}
        <section className="card p-5">
          <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold text-ink">
            <Users className="h-4 w-4 text-muted" aria-hidden />
            Squad status
          </h2>
          <p className="mb-4 text-[11px] text-muted/90">Notes are visible to your group.</p>
          {c.applications.length === 0 ? (
            <p className="text-sm text-muted">
              No applications here yet. Save yours on the right to start the squad off.
            </p>
          ) : (
            <div className="space-y-3">
              {c.applications.map((a) => (
                <div key={a.id} className="rounded-lg border border-line bg-canvas p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex min-w-0 items-center gap-2.5">
                      <Avatar username={a.username} displayName={a.display_name} size="md" />
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium text-ink">
                          {a.display_name}
                          {a.user_id === user?.id && (
                            <span className="ml-1.5 text-xs font-normal text-muted">(you)</span>
                          )}
                        </span>
                        <span className="block font-mono text-[11px] text-muted">
                          updated {timeAgo(a.updated_at)}
                        </span>
                      </span>
                    </span>
                    <StatusBadge status={a.status} />
                  </div>
                  <dl className="mt-3 space-y-1 text-xs text-muted">
                    {a.applied_at && (
                      <div className="flex items-center gap-1.5">
                        <Send className="h-3 w-3" aria-hidden />
                        Applied {formatDate(a.applied_at)}
                        {a.applied_via_portal_name && ` via ${a.applied_via_portal_name}`}
                      </div>
                    )}
                    {!a.applied_at && a.applied_via_portal_name && (
                      <div className="flex items-center gap-1.5">
                        <Send className="h-3 w-3" aria-hidden />
                        Via {a.applied_via_portal_name}
                      </div>
                    )}
                    {a.follow_up_at && (
                      <div className="flex items-center gap-1.5">
                        <CalendarClock className="h-3 w-3" aria-hidden />
                        Follow up {formatDate(a.follow_up_at)}
                      </div>
                    )}
                    {a.url && <PostingLink url={a.url} />}
                  </dl>
                  {a.notes && (
                    <p className="mt-2 whitespace-pre-wrap rounded-md bg-paper p-2.5 text-xs leading-relaxed text-ink/90">
                      {a.notes}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* My application */}
        <MyApplicationEditor gid={gid} cid={cid} mine={mine} />
      </div>

      {/* Shared notes */}
      <section className="card p-5">
        <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-ink">
          <StickyNote className="h-4 w-4 text-muted" aria-hidden />
          Shared company notes
        </h2>
        <textarea
          className="input min-h-24 resize-y"
          value={sharedNotes}
          onChange={(e) => {
            setSharedNotes(e.target.value);
            setNotesDirty(true);
          }}
          placeholder="Facts for the whole squad: stack, referral contacts, salary intel..."
          rows={3}
          aria-label="Shared company notes"
        />
        {notesDirty && (
          <div className="mt-3 flex justify-end gap-2">
            <button
              className="btn-ghost"
              onClick={() => {
                setSharedNotes(c.notes ?? "");
                setNotesDirty(false);
              }}
            >
              Discard changes
            </button>
            <button className="btn-primary" onClick={saveNotes} disabled={updateCompany.isPending}>
              {updateCompany.isPending ? "Saving..." : "Save notes"}
            </button>
          </div>
        )}
      </section>

      {/* Comments */}
      <section className="card p-5">
        <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-ink">
          <MessageSquare className="h-4 w-4 text-muted" aria-hidden />
          Comments
          <span className="font-mono text-xs font-normal text-muted">{c.comments.length}</span>
        </h2>
        {c.comments.length === 0 ? (
          <p className="mb-4 text-sm text-muted">No comments yet. Start the thread below.</p>
        ) : (
          <div className="mb-4 space-y-3">
            {c.comments.map((cm) => (
              <div key={cm.id} className="flex items-start gap-3">
                <Avatar username={cm.username} displayName={cm.display_name} size="sm" />
                <div className="min-w-0 flex-1 rounded-lg bg-canvas px-3.5 py-2.5">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-xs font-medium text-ink">{cm.display_name}</span>
                    <span className="flex items-center gap-2">
                      <span className="font-mono text-[11px] text-muted/80">
                        {timeAgo(cm.created_at)}
                      </span>
                      {cm.user_id === user?.id && (
                        <button
                          onClick={() =>
                            deleteComment.mutate(cm.id, {
                              onError: (err) =>
                                toast(errMsg(err, "Couldn't delete the comment. Retry."), "error"),
                            })
                          }
                          className="text-muted/70 transition-colors duration-150 ease-out hover:text-danger"
                          aria-label="Delete my comment"
                        >
                          <Trash2 className="h-3.5 w-3.5" aria-hidden />
                        </button>
                      )}
                    </span>
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-ink/90">{cm.body}</p>
                </div>
              </div>
            ))}
          </div>
        )}
        <form onSubmit={submitComment} className="flex gap-2">
          <input
            className="input flex-1"
            value={commentBody}
            onChange={(e) => setCommentBody(e.target.value)}
            placeholder="Write a comment for the squad"
            aria-label="New comment"
          />
          <button
            type="submit"
            className="btn-primary"
            disabled={addComment.isPending || commentBody.trim().length === 0}
          >
            {addComment.isPending ? "Posting..." : "Post comment"}
          </button>
        </form>
      </section>

      <CompanyFormDialog
        open={editOpen}
        onClose={() => setEditOpen(false)}
        title={`Edit ${c.name}`}
        initial={c}
        busy={updateCompany.isPending}
        error={editError}
        onSubmit={(payload) =>
          updateCompany.mutate(
            { cid, patch: payload },
            {
              onSuccess: () => {
                setEditOpen(false);
                toast("Company updated");
              },
              onError: (err) => setEditError(errMsg(err, "Couldn't update the company. Retry.")),
            },
          )
        }
      />

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() =>
          deleteCompany.mutate(cid, {
            onSuccess: () => {
              toast(`${c.name} deleted`);
              navigate(`/g/${gid}/companies`);
            },
            onError: (err) => {
              setConfirmDelete(false);
              toast(errMsg(err, "Couldn't delete the company. Retry."), "error");
            },
          })
        }
        title={`Delete ${c.name}`}
        message="This removes the company for the whole squad, along with everyone's applications and comments on it. This cannot be undone."
        confirmLabel="Delete company"
        busy={deleteCompany.isPending}
      />
    </div>
  );
}
