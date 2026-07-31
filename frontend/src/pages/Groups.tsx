import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Check, ChevronDown, Compass, LogOut, Plus, Search, Ticket, UserPlus, Users } from "lucide-react";
import {
  useCreateGroup,
  useDiscoverGroups,
  useGroups,
  useJoinGroup,
  useRequestJoin,
} from "../hooks/useGroups";
import { useAuth } from "../hooks/useAuth";
import { useToast } from "../components/ui/Toast";
import { Dialog } from "../components/ui/Dialog";
import { CopyChip } from "../components/ui/CopyChip";
import { VisibilityChip, VisibilityToggle } from "../components/ui/VisibilityChip";
import { Avatar } from "../components/ui/MemberChip";
import { Menu, MenuItem } from "../components/ui/Menu";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Spinner";
import { ApiError } from "../lib/api";
import { formatDate } from "../lib/format";
import type { DiscoverGroup, GroupVisibility } from "../types/api";

const DESCRIPTION_MAX = 280;

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

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
  const [visibility, setVisibility] = useState<GroupVisibility>("private");
  const [description, setDescription] = useState("");
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

  const openCreate = () => {
    setFormError(null);
    setName("");
    setVisibility("private");
    setDescription("");
    setCreateOpen(true);
  };

  const submitCreate = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim().length === 0) {
      setFormError("Group name is required.");
      return;
    }
    setFormError(null);
    createGroup.mutate(
      { name: name.trim(), visibility, description: description.trim() || null },
      {
        onSuccess: (g) => {
          setCreateOpen(false);
          toast(`Group "${g.name}" created`);
          navigate(`/g/${g.id}`);
        },
        onError: (err) => setFormError(errMsg(err, "Couldn't create the group. Retry.")),
      },
    );
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
            : errMsg(err, "Couldn't join the group. Retry."),
        ),
    });
  };

  const descriptionLeft = DESCRIPTION_MAX - description.length;

  return (
    <div className="mx-auto min-h-screen w-full max-w-3xl p-6">
      <header className="mb-10 flex items-center justify-between">
        <span className="text-xl font-semibold tracking-tight text-ink">JobSquad</span>
        {user && (
          <Menu
            trigger={() => (
              <span className="flex items-center gap-2 rounded-md p-1 pr-2 transition-colors duration-150 ease-out hover:bg-hover">
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

      {/* My groups */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink">Your groups</h1>
          <p className="text-sm text-muted">Pick a squad, or start a new hunt together.</p>
        </div>
        <div className="flex gap-2">
          <button
            className="btn-ghost"
            onClick={() => {
              setFormError(null);
              setCode("");
              setJoinOpen(true);
            }}
          >
            <Ticket className="h-4 w-4" aria-hidden />
            Join with code
          </button>
          <button className="btn-primary" onClick={openCreate}>
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
              <button className="btn-primary" onClick={openCreate}>
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
                <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-canvas px-2.5 py-1 font-mono text-xs text-muted">
                  <Users className="h-3 w-3" aria-hidden />
                  {g.member_count}
                </span>
              </div>
              <div className="mb-3">
                <VisibilityChip visibility={g.visibility} />
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

      {/* Discover */}
      <Discover onJoinWithCode={() => setJoinOpen(true)} onCreate={openCreate} />

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
          <div>
            <span className="label">Visibility</span>
            <VisibilityToggle value={visibility} onChange={setVisibility} />
            <p className="mt-1.5 text-small text-muted">
              {visibility === "public"
                ? "Anyone can find this group in Discover and request to join. You approve each request."
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

function Discover({
  onJoinWithCode,
  onCreate,
}: {
  onJoinWithCode: () => void;
  onCreate: () => void;
}) {
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const requestJoin = useRequestJoin();
  const { toast } = useToast();

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(t);
  }, [search]);

  const discover = useDiscoverGroups(debounced);
  const results = discover.data ?? [];

  const request = (g: DiscoverGroup) => {
    requestJoin.mutate(g.id, {
      onSuccess: () => toast(`Request sent to "${g.name}"`),
      onError: (err) => toast(errMsg(err, "Couldn't send the request. Retry."), "error"),
    });
  };

  return (
    <section className="mt-12">
      <div className="mb-4">
        <h2 className="text-base font-semibold text-ink">Discover</h2>
        <p className="text-sm text-muted">Public groups you can ask to join.</p>
      </div>

      <div className="relative mb-4">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
          aria-hidden
        />
        <input
          className="input pl-9"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search public groups by name or description"
          aria-label="Search public groups"
        />
      </div>

      {discover.isPending ? (
        <div className="space-y-3">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      ) : discover.isError ? (
        <ErrorState message="Couldn't load public groups. Retry." onRetry={() => discover.refetch()} />
      ) : results.length === 0 ? (
        debounced ? (
          <EmptyState
            icon={Search}
            title="No matches"
            description={`No public groups match "${debounced}". Try a different search.`}
          />
        ) : (
          <EmptyState
            icon={Compass}
            title="Nothing to discover yet"
            description="No public groups yet. Create one and make it public, or join with a code."
            action={
              <div className="flex gap-2">
                <button className="btn-ghost" onClick={onJoinWithCode}>
                  Join with code
                </button>
                <button className="btn-primary" onClick={onCreate}>
                  Create group
                </button>
              </div>
            }
          />
        )
      ) : (
        <ul className="space-y-3">
          {results.map((g) => {
            const pending = g.request_status === "pending";
            const inFlight = requestJoin.isPending && requestJoin.variables === g.id;
            return (
              <li
                key={g.id}
                className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="truncate text-sm font-semibold text-ink">{g.name}</h3>
                    <span className="flex shrink-0 items-center gap-1 font-mono text-[11px] text-muted">
                      <Users className="h-3 w-3" aria-hidden />
                      {g.member_count}
                    </span>
                  </div>
                  {g.description && (
                    <p className="mt-1 line-clamp-2 text-sm text-muted">{g.description}</p>
                  )}
                </div>
                <div className="shrink-0">
                  {pending ? (
                    <button className="btn-ghost" disabled aria-label={`Request to ${g.name} is pending`}>
                      <Check className="h-4 w-4" aria-hidden />
                      Requested
                    </button>
                  ) : (
                    <button
                      className="btn-ghost"
                      onClick={() => request(g)}
                      disabled={inFlight}
                    >
                      <UserPlus className="h-4 w-4" aria-hidden />
                      {inFlight ? "Requesting..." : "Request to join"}
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
