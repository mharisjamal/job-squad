import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ExternalLink, Globe, Pencil, Plus, Star, Trash2 } from "lucide-react";
import { useGroupCtx } from "../components/layout/Shell";
import { useAuth } from "../hooks/useAuth";
import {
  useAddPortal,
  useDeletePortal,
  usePortals,
  useSetPortalStatus,
  useUpdatePortal,
} from "../hooks/usePortals";
import { useToast } from "../components/ui/Toast";
import { Dialog, ConfirmDialog } from "../components/ui/Dialog";
import { Avatar } from "../components/ui/MemberChip";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Spinner";
import { PORTAL_STATUSES, portalStatusLabel } from "../config/statuses";
import { normalizeUrl, safeHref } from "../lib/format";
import { ApiError } from "../lib/api";
import type { Portal, PortalMemberStatus, PortalPayload } from "../types/api";

// Ratings borrow the interview amber: the one warm signal in the system.
const STAR_ON = "rgb(var(--status-interview-dot))";
const STAR_OFF = "rgb(var(--line-strong))";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function effectivenessLine(p: Portal): string {
  const { applications_via, interviews_via, offers_via } = p.stats;
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  return `${plural(applications_via, "application")}, ${plural(interviews_via, "interview")}, ${plural(offers_via, "offer")} via this portal`;
}

function StarRating({
  value,
  onChange,
}: {
  value: number | null;
  onChange: (v: number | null) => void;
}) {
  return (
    <div className="flex items-center gap-0.5" role="radiogroup" aria-label="Rating out of 5">
      {[1, 2, 3, 4, 5].map((n) => {
        const filled = value != null && n <= value;
        return (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={value === n}
            aria-label={`${n} star${n === 1 ? "" : "s"}`}
            onClick={() => onChange(value === n ? null : n)}
            className="rounded p-0.5 transition-colors duration-150 ease-out hover:bg-hover"
          >
            <Star
              className="h-4 w-4"
              style={{ color: filled ? STAR_ON : STAR_OFF }}
              fill={filled ? "currentColor" : "none"}
              aria-hidden
            />
          </button>
        );
      })}
    </div>
  );
}

function MyPortalStatus({ portal, gid }: { portal: Portal; gid: number }) {
  const { user } = useAuth();
  const setStatus = useSetPortalStatus(gid);
  const { toast } = useToast();
  const mine = portal.statuses.find((s) => s.user_id === user?.id) ?? null;

  const [status, setStatusValue] = useState<PortalMemberStatus>("none");
  const [rating, setRating] = useState<number | null>(null);
  const [notes, setNotes] = useState("");

  useEffect(() => {
    setStatusValue(mine?.status ?? "none");
    setRating(mine?.rating ?? null);
    setNotes(mine?.notes ?? "");
  }, [mine?.status, mine?.rating, mine?.notes]);

  const dirty =
    status !== (mine?.status ?? "none") ||
    rating !== (mine?.rating ?? null) ||
    notes !== (mine?.notes ?? "");

  const save = () => {
    setStatus.mutate(
      {
        pid: portal.id,
        payload:
          status === "none" ? { status: "none" } : { status, rating, notes: notes.trim() || null },
      },
      {
        onSuccess: () =>
          toast(status === "none" ? "Portal status cleared" : "Portal status saved"),
        onError: (err) => toast(errMsg(err, "Couldn't save your portal status. Retry."), "error"),
      },
    );
  };

  return (
    <div className="mt-3 rounded-lg border border-line bg-canvas p-3">
      <p className="mb-2 text-small font-medium text-muted">My status</p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="input h-8 w-36 px-2 py-0 font-mono text-xs"
          value={status}
          onChange={(e) => setStatusValue(e.target.value as PortalMemberStatus)}
          aria-label={`My status on ${portal.name}`}
        >
          {PORTAL_STATUSES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        {status !== "none" && <StarRating value={rating} onChange={setRating} />}
      </div>
      {status !== "none" && (
        <input
          className="input mt-2 h-8 px-2 py-0 text-xs"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Quick note (filters, spam level, tips...)"
          aria-label={`My notes on ${portal.name}`}
        />
      )}
      {dirty && (
        <button
          className="btn-primary mt-2 h-8 px-3 text-xs"
          onClick={save}
          disabled={setStatus.isPending}
        >
          {setStatus.isPending ? "Saving..." : "Save status"}
        </button>
      )}
    </div>
  );
}

function PortalFormDialog({
  open,
  onClose,
  title,
  initial,
  busy,
  error,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  initial?: Portal | null;
  busy: boolean;
  error: string | null;
  onSubmit: (payload: PortalPayload) => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [notes, setNotes] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName(initial?.name ?? "");
    setUrl(initial?.url ?? "");
    setNotes(initial?.notes ?? "");
    setLocalError(null);
  }, [open, initial]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim().length === 0) {
      setLocalError("Portal name is required.");
      return;
    }
    setLocalError(null);
    onSubmit({ name: name.trim(), url: normalizeUrl(url) || null, notes: notes.trim() || null });
  };

  const shownError = localError ?? error;

  return (
    <Dialog open={open} onClose={onClose} title={title}>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor="portal-name" className="label">
            Name
          </label>
          <input
            id="portal-name"
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. LinkedIn"
          />
        </div>
        <div>
          <label htmlFor="portal-url" className="label">
            URL
          </label>
          <input
            id="portal-url"
            className="input"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://linkedin.com/jobs"
            inputMode="url"
          />
        </div>
        <div>
          <label htmlFor="portal-notes" className="label">
            Shared notes
          </label>
          <textarea
            id="portal-notes"
            className="input min-h-20 resize-y"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Tips for the squad about this portal"
            rows={3}
          />
        </div>
        {shownError && (
          <p role="alert" className="text-sm text-danger">
            {shownError}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? "Saving..." : "Save portal"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export default function Portals() {
  const { gid, group } = useGroupCtx();
  const { user } = useAuth();
  const portals = usePortals(gid);
  const addPortal = useAddPortal(gid);
  const updatePortal = useUpdatePortal(gid);
  const deletePortal = useDeletePortal(gid);
  const { toast } = useToast();

  const [addOpen, setAddOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Portal | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Portal | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink">Portals</h1>
          <p className="text-sm text-muted">
            Where the squad actually applies, and which portals convert.
          </p>
        </div>
        <button
          className="btn-primary"
          onClick={() => {
            setFormError(null);
            setAddOpen(true);
          }}
        >
          <Plus className="h-4 w-4" aria-hidden />
          Add portal
        </button>
      </div>

      {portals.isPending ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-56" />
          <Skeleton className="h-56" />
        </div>
      ) : portals.isError ? (
        <ErrorState message="Couldn't load portals. Retry." onRetry={() => portals.refetch()} />
      ) : portals.data.length === 0 ? (
        <EmptyState
          icon={Globe}
          title="No portals yet"
          description="Add the job boards your squad uses (LinkedIn, Indeed, company boards) to compare where applications convert."
          action={
            <button className="btn-primary" onClick={() => setAddOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden />
              Add portal
            </button>
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {portals.data.map((p) => {
            const canDelete =
              user != null && (p.created_by === user.id || group.owner_id === user.id);
            const portalHref = safeHref(p.url);
            return (
              <div key={p.id} className="card flex flex-col p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    {portalHref ? (
                      <a
                        href={portalHref}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1.5 text-base font-semibold text-ink transition-colors duration-150 ease-out hover:underline"
                      >
                        {p.name}
                        <ExternalLink className="h-3.5 w-3.5 text-muted" aria-hidden />
                      </a>
                    ) : (
                      <span className="text-base font-semibold text-ink">{p.name}</span>
                    )}
                    {p.url && !portalHref && (
                      <span className="block truncate font-mono text-[11px] text-muted/80">
                        {p.url}
                      </span>
                    )}
                    <p className="mt-0.5 font-mono text-xs text-muted">{effectivenessLine(p)}</p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <button
                      className="rounded-md p-1.5 text-muted transition-colors duration-150 ease-out hover:bg-hover hover:text-ink"
                      onClick={() => {
                        setFormError(null);
                        setEditTarget(p);
                      }}
                      aria-label={`Edit ${p.name}`}
                    >
                      <Pencil className="h-4 w-4" aria-hidden />
                    </button>
                    {canDelete && (
                      <button
                        className="rounded-md p-1.5 text-muted transition-colors duration-150 ease-out hover:bg-danger/10 hover:text-danger"
                        onClick={() => setDeleteTarget(p)}
                        aria-label={`Delete ${p.name}`}
                      >
                        <Trash2 className="h-4 w-4" aria-hidden />
                      </button>
                    )}
                  </div>
                </div>

                {p.notes && (
                  <p className="mt-3 whitespace-pre-wrap rounded-md bg-canvas p-2.5 text-xs leading-relaxed text-ink/90">
                    {p.notes}
                  </p>
                )}

                {p.statuses.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {p.statuses.map((s) => (
                      <span
                        key={s.user_id}
                        className="inline-flex items-center gap-1.5 rounded-full border border-line bg-paper py-0.5 pl-0.5 pr-2 font-mono text-[11px] text-muted"
                        title={s.notes ?? undefined}
                      >
                        <Avatar username={s.username} displayName={s.display_name} size="sm" />
                        {portalStatusLabel(s.status)}
                        {s.rating != null && (
                          <span className="flex items-center gap-0.5" style={{ color: STAR_ON }}>
                            <Star className="h-3 w-3" fill="currentColor" aria-hidden />
                            {s.rating}
                          </span>
                        )}
                      </span>
                    ))}
                  </div>
                )}

                <div className="mt-auto">
                  <MyPortalStatus portal={p} gid={gid} />
                </div>
              </div>
            );
          })}
        </div>
      )}

      <PortalFormDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add a portal"
        busy={addPortal.isPending}
        error={formError}
        onSubmit={(payload) =>
          addPortal.mutate(payload, {
            onSuccess: (created) => {
              setAddOpen(false);
              toast(`${created.name} added`);
            },
            onError: (err) => setFormError(errMsg(err, "Couldn't add the portal. Retry.")),
          })
        }
      />

      <PortalFormDialog
        open={editTarget != null}
        onClose={() => setEditTarget(null)}
        title={editTarget ? `Edit ${editTarget.name}` : "Edit portal"}
        initial={editTarget}
        busy={updatePortal.isPending}
        error={formError}
        onSubmit={(payload) => {
          if (!editTarget) return;
          updatePortal.mutate(
            { pid: editTarget.id, patch: payload },
            {
              onSuccess: () => {
                setEditTarget(null);
                toast("Portal updated");
              },
              onError: (err) => setFormError(errMsg(err, "Couldn't update the portal. Retry.")),
            },
          );
        }}
      />

      <ConfirmDialog
        open={deleteTarget != null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (!deleteTarget) return;
          deletePortal.mutate(deleteTarget.id, {
            onSuccess: () => {
              toast(`${deleteTarget.name} deleted`);
              setDeleteTarget(null);
            },
            onError: (err) => {
              setDeleteTarget(null);
              toast(errMsg(err, "Couldn't delete the portal. Retry."), "error");
            },
          });
        }}
        title={deleteTarget ? `Delete ${deleteTarget.name}` : "Delete portal"}
        message="This removes the portal for the whole squad. Applications that pointed at it keep their other details."
        confirmLabel="Delete portal"
        busy={deletePortal.isPending}
      />
    </div>
  );
}
