import { useEffect, useState } from "react";
import { Check, RefreshCw, UserMinus, Users, X } from "lucide-react";
import clsx from "clsx";
import { useGroupCtx } from "../components/layout/Shell";
import { useAuth } from "../hooks/useAuth";
import { useUpdateGroup } from "../hooks/useGroups";
import {
  useApproveRequest,
  useGroupRequests,
  useRegenerateInvite,
  useRejectRequest,
  useRemoveMember,
} from "../hooks/useGroupAdmin";
import { useToast } from "../components/ui/Toast";
import { ConfirmDialog } from "../components/ui/Dialog";
import { Avatar } from "../components/ui/MemberChip";
import { CopyChip } from "../components/ui/CopyChip";
import { VisibilityToggle } from "../components/ui/VisibilityChip";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Spinner";
import { ApiError } from "../lib/api";
import { timeAgo } from "../lib/format";
import type { GroupMember, GroupVisibility } from "../types/api";

const DESCRIPTION_MAX = 280;

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function RoleChip({ role }: { role: GroupMember["role"] }) {
  const isOwner = role === "owner";
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[11px]",
        isOwner ? "border-focus/30 bg-focus/10 text-focus" : "border-line text-muted",
      )}
    >
      {isOwner ? "Owner" : "Member"}
    </span>
  );
}

export default function Members() {
  const { gid, group } = useGroupCtx();
  const { user } = useAuth();
  const { toast } = useToast();
  const isOwner = user != null && group.owner_id === user.id;

  const updateGroup = useUpdateGroup(gid);
  const requests = useGroupRequests(gid, isOwner);
  const approve = useApproveRequest(gid);
  const reject = useRejectRequest(gid);
  const removeMember = useRemoveMember(gid);
  const regenerate = useRegenerateInvite(gid);

  // Settings form (owner only).
  const [visibility, setVisibility] = useState<GroupVisibility>(group.visibility);
  const [description, setDescription] = useState(group.description ?? "");
  useEffect(() => {
    setVisibility(group.visibility);
    setDescription(group.description ?? "");
  }, [group.visibility, group.description]);

  const settingsDirty =
    visibility !== group.visibility || description.trim() !== (group.description ?? "");

  const [removeTarget, setRemoveTarget] = useState<GroupMember | null>(null);
  const [regenOpen, setRegenOpen] = useState(false);

  const saveSettings = () => {
    updateGroup.mutate(
      { visibility, description: description.trim() || null },
      {
        onSuccess: () => toast("Group settings saved"),
        onError: (err) => toast(errMsg(err, "Couldn't save the settings. Retry."), "error"),
      },
    );
  };

  const descriptionLeft = DESCRIPTION_MAX - description.length;
  const pendingRequests = requests.data ?? [];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink">Members</h1>
        <p className="text-sm text-muted">
          {isOwner
            ? "Manage who is in the squad, review join requests, and set how the group is found."
            : "Everyone in this squad. Only the owner can change membership."}
        </p>
      </div>

      {/* Owner: pending requests */}
      {isOwner && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold text-ink">Pending requests</h2>
          {requests.isPending ? (
            <div className="space-y-3">
              <Skeleton className="h-16" />
            </div>
          ) : requests.isError ? (
            <ErrorState
              message="Couldn't load join requests. Retry."
              onRetry={() => requests.refetch()}
            />
          ) : pendingRequests.length === 0 ? (
            <EmptyState
              icon={Users}
              title="No pending requests"
              description="When someone asks to join this public group, their request shows up here for you to approve or reject."
            />
          ) : (
            <ul className="space-y-3">
              {pendingRequests.map((r) => {
                const approving = approve.isPending && approve.variables === r.id;
                const rejecting = reject.isPending && reject.variables === r.id;
                const busy = approving || rejecting;
                return (
                  <li
                    key={r.id}
                    className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <Avatar username={r.username} displayName={r.display_name} size="md" />
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-ink">{r.display_name}</p>
                        <p className="font-mono text-[11px] text-muted/80">
                          @{r.username} · requested {timeAgo(r.created_at)}
                        </p>
                      </div>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <button
                        className="btn-primary"
                        disabled={busy}
                        onClick={() =>
                          approve.mutate(r.id, {
                            onSuccess: () => toast(`${r.display_name} added to the squad`),
                            onError: (err) =>
                              toast(errMsg(err, "Couldn't approve the request. Retry."), "error"),
                          })
                        }
                      >
                        <Check className="h-4 w-4" aria-hidden />
                        {approving ? "Approving..." : "Approve"}
                      </button>
                      <button
                        className="btn-ghost"
                        disabled={busy}
                        onClick={() =>
                          reject.mutate(r.id, {
                            onSuccess: () => toast(`Request from ${r.display_name} rejected`),
                            onError: (err) =>
                              toast(errMsg(err, "Couldn't reject the request. Retry."), "error"),
                          })
                        }
                      >
                        <X className="h-4 w-4" aria-hidden />
                        {rejecting ? "Rejecting..." : "Reject"}
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}

      {/* Roster (everyone) */}
      <section className="space-y-3">
        <h2 className="text-base font-semibold text-ink">
          Roster{" "}
          <span className="font-mono text-xs font-normal text-muted">
            ({group.member_count})
          </span>
        </h2>
        <ul className="card divide-y divide-line">
          {group.members.map((m) => {
            const removable = isOwner && m.user_id !== group.owner_id;
            const removing = removeMember.isPending && removeMember.variables === m.user_id;
            return (
              <li key={m.user_id} className="flex items-center gap-3 p-4">
                <Avatar username={m.username} displayName={m.display_name} size="md" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink">
                    {m.display_name}
                    {user != null && m.user_id === user.id && (
                      <span className="ml-1.5 font-mono text-[11px] text-muted/80">(you)</span>
                    )}
                  </p>
                  <p className="font-mono text-[11px] text-muted/80">@{m.username}</p>
                </div>
                <RoleChip role={m.role} />
                {removable && (
                  <button
                    className="rounded-md p-1.5 text-muted transition-colors duration-150 ease-out hover:bg-danger/10 hover:text-danger disabled:opacity-50"
                    onClick={() => setRemoveTarget(m)}
                    disabled={removing}
                    aria-label={`Remove ${m.display_name}`}
                    title={`Remove ${m.display_name}`}
                  >
                    <UserMinus className="h-4 w-4" aria-hidden />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      {/* Owner: group settings */}
      {isOwner && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold text-ink">Group settings</h2>
          <div className="card space-y-5 p-5">
            <div>
              <span className="label">Visibility</span>
              <VisibilityToggle
                value={visibility}
                onChange={setVisibility}
                disabled={updateGroup.isPending}
              />
              <p className="mt-1.5 text-small text-muted">
                {visibility === "public"
                  ? "Listed in Discover. People can request to join and you approve each one."
                  : "Hidden from Discover. Only people with the invite code can join."}
              </p>
            </div>

            <div>
              <label htmlFor="group-description" className="label">
                Description <span className="text-muted/70">(optional)</span>
              </label>
              <textarea
                id="group-description"
                className="input min-h-20 resize-y"
                value={description}
                onChange={(e) => setDescription(e.target.value.slice(0, DESCRIPTION_MAX))}
                placeholder="What is this squad hunting for? Shown in Discover."
                maxLength={DESCRIPTION_MAX}
                rows={3}
              />
              {descriptionLeft <= 40 && (
                <p className="mt-1 text-right font-mono text-[11px] text-muted">
                  {descriptionLeft} left
                </p>
              )}
            </div>

            <div className="flex justify-end">
              <button
                className="btn-primary"
                disabled={!settingsDirty || updateGroup.isPending}
                onClick={saveSettings}
              >
                {updateGroup.isPending ? "Saving..." : "Save settings"}
              </button>
            </div>

            <div className="border-t border-line pt-5">
              <span className="label">Invite code</span>
              <div className="flex flex-wrap items-center gap-3">
                <CopyChip value={group.invite_code} />
                <button
                  className="btn-ghost"
                  onClick={() => setRegenOpen(true)}
                  disabled={regenerate.isPending}
                >
                  <RefreshCw className="h-4 w-4" aria-hidden />
                  Regenerate invite code
                </button>
              </div>
              <p className="mt-1.5 text-small text-muted">
                Anyone with this code joins instantly. Regenerate it to cut off an old share.
              </p>
            </div>
          </div>
        </section>
      )}

      <ConfirmDialog
        open={removeTarget != null}
        onClose={() => setRemoveTarget(null)}
        onConfirm={() => {
          if (!removeTarget) return;
          const target = removeTarget;
          removeMember.mutate(target.user_id, {
            onSuccess: () => {
              toast(`${target.display_name} removed from the squad`);
              setRemoveTarget(null);
            },
            onError: (err) => {
              setRemoveTarget(null);
              toast(errMsg(err, "Couldn't remove the member. Retry."), "error");
            },
          });
        }}
        title={removeTarget ? `Remove ${removeTarget.display_name}?` : "Remove member"}
        message="This removes their applications and portal statuses in this group."
        confirmLabel="Remove member"
        busy={removeMember.isPending}
      />

      <ConfirmDialog
        open={regenOpen}
        onClose={() => setRegenOpen(false)}
        onConfirm={() =>
          regenerate.mutate(undefined, {
            onSuccess: () => {
              toast("New invite code generated");
              setRegenOpen(false);
            },
            onError: (err) => {
              setRegenOpen(false);
              toast(errMsg(err, "Couldn't regenerate the code. Retry."), "error");
            },
          })
        }
        title="Regenerate invite code?"
        message="The current code stops working immediately. You will get a new code to share."
        confirmLabel="Regenerate code"
        busy={regenerate.isPending}
      />
    </div>
  );
}
