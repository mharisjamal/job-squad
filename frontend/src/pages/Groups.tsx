import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, LogOut, Plus, Ticket, Users } from "lucide-react";
import { useCreateGroup, useGroups, useJoinGroup } from "../hooks/useGroups";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../components/ui/Toast";
import { Dialog } from "../components/ui/Dialog";
import { CopyChip } from "../components/ui/CopyChip";
import { Avatar } from "../components/ui/MemberChip";
import { Menu, MenuItem } from "../components/ui/Menu";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Spinner";
import { ApiError } from "../lib/api";
import { formatDate } from "../lib/format";

export default function Groups() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const groups = useGroups();
  const createGroup = useCreateGroup();
  const joinGroup = useJoinGroup();
  const { toast } = useToast();

  const [createOpen, setCreateOpen] = useState(false);
  const [joinOpen, setJoinOpen] = useState(false);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  // Auto-redirect to the last group while it still exists.
  useEffect(() => {
    const last = localStorage.getItem("last_group");
    if (!last || !groups.data) return;
    if (groups.data.some((g) => String(g.id) === last)) {
      navigate(`/g/${last}`, { replace: true });
    } else {
      localStorage.removeItem("last_group");
    }
  }, [groups.data, navigate]);

  const submitCreate = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim().length === 0) {
      setFormError("Group name is required.");
      return;
    }
    setFormError(null);
    createGroup.mutate(name.trim(), {
      onSuccess: (g) => {
        setCreateOpen(false);
        setName("");
        toast(`Group "${g.name}" created`);
        navigate(`/g/${g.id}`);
      },
      onError: (err) =>
        setFormError(err instanceof ApiError ? err.message : "Couldn't create the group. Retry."),
    });
  };

  const submitJoin = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = code.trim();
    if (trimmed.length === 0) {
      setFormError("Enter the invite code your friend shared.");
      return;
    }
    setFormError(null);
    joinGroup.mutate(trimmed, {
      onSuccess: (g) => {
        setJoinOpen(false);
        setCode("");
        toast(`Joined "${g.name}"`);
        navigate(`/g/${g.id}`);
      },
      onError: (err) =>
        setFormError(
          err instanceof ApiError && err.status === 404
            ? "No group matches that code. Check it with your friend and retry."
            : err instanceof ApiError
              ? err.message
              : "Couldn't join the group. Retry.",
        ),
    });
  };

  return (
    <div className="mx-auto min-h-screen w-full max-w-3xl p-6">
      <header className="mb-10 flex items-center justify-between">
        <span className="text-xl font-semibold tracking-tight text-ink">JobSquad</span>
        {user && (
          <Menu
            trigger={() => (
              <span className="flex items-center gap-2 rounded-md p-1 pr-2 transition-colors duration-150 ease-out hover:bg-pill/70">
                <Avatar username={user.username} displayName={user.display_name} size="md" />
                <span className="hidden text-sm font-medium text-ink sm:inline">
                  {user.display_name}
                </span>
                <ChevronDown className="h-3.5 w-3.5 text-muted" aria-hidden />
              </span>
            )}
          >
            {(close) => (
              <MenuItem
                danger
                onClick={() => {
                  close();
                  logout();
                }}
              >
                <LogOut className="h-4 w-4" aria-hidden />
                Sign out
              </MenuItem>
            )}
          </Menu>
        )}
      </header>

      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink">Your groups</h1>
          <p className="text-sm text-muted">Pick a squad, or start a new hunt together.</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={() => { setFormError(null); setJoinOpen(true); }}>
            <Ticket className="h-4 w-4" aria-hidden />
            Join with code
          </button>
          <button className="btn-primary" onClick={() => { setFormError(null); setCreateOpen(true); }}>
            <Plus className="h-4 w-4" aria-hidden />
            Create group
          </button>
        </div>
      </div>

      {groups.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
      ) : groups.isError ? (
        <ErrorState
          message="Couldn't load your groups. Check the server is running and retry."
          onRetry={() => groups.refetch()}
        />
      ) : groups.data.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No groups yet"
          description="Create a group and share its invite code, or join a friend's group with theirs."
          action={
            <div className="flex gap-2">
              <button className="btn-ghost" onClick={() => setJoinOpen(true)}>
                Join with code
              </button>
              <button className="btn-primary" onClick={() => setCreateOpen(true)}>
                Create group
              </button>
            </div>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {groups.data.map((g) => (
            <div
              key={g.id}
              role="button"
              tabIndex={0}
              onClick={() => navigate(`/g/${g.id}`)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  navigate(`/g/${g.id}`);
                }
              }}
              className="card cursor-pointer p-5 text-left transition-colors duration-150 ease-out hover:bg-hover"
            >
              <div className="mb-3 flex items-start justify-between gap-3">
                <h2 className="text-base font-semibold text-ink">{g.name}</h2>
                <span className="flex items-center gap-1.5 rounded-full bg-canvas px-2.5 py-1 font-mono text-xs text-muted">
                  <Users className="h-3 w-3" aria-hidden />
                  {g.member_count}
                </span>
              </div>
              <div
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => e.stopPropagation()}
                role="presentation"
              >
                <CopyChip value={g.invite_code} />
              </div>
              <p className="mt-3 font-mono text-[11px] text-muted/80">
                Created {formatDate(g.created_at)}
              </p>
            </div>
          ))}
        </div>
      )}

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="Create a group">
        <form onSubmit={submitCreate} className="space-y-4">
          <div>
            <label htmlFor="group-name" className="label">
              Group name
            </label>
            <input
              id="group-name"
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Job Hunt 2026"
            />
          </div>
          {formError && (
            <p role="alert" className="text-sm text-danger">
              {formError}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={createGroup.isPending}>
              {createGroup.isPending ? "Creating..." : "Create group"}
            </button>
          </div>
        </form>
      </Dialog>

      <Dialog open={joinOpen} onClose={() => setJoinOpen(false)} title="Join with an invite code">
        <form onSubmit={submitJoin} className="space-y-4">
          <div>
            <label htmlFor="invite-code" className="label">
              Invite code
            </label>
            <input
              id="invite-code"
              className="input font-mono uppercase tracking-widest"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="8 characters"
              maxLength={8}
            />
          </div>
          {formError && (
            <p role="alert" className="text-sm text-danger">
              {formError}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={() => setJoinOpen(false)}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={joinGroup.isPending}>
              {joinGroup.isPending ? "Joining..." : "Join group"}
            </button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
