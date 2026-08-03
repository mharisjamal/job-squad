import { createContext, useContext, useEffect, useState } from "react";
import { Navigate, NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  Activity as ActivityIcon,
  Building2,
  ChevronDown,
  Download,
  FileText,
  Globe,
  Kanban,
  LayoutDashboard,
  LayoutGrid,
  LogOut,
  Menu as MenuIcon,
  Moon,
  Puzzle,
  Repeat,
  Sparkles,
  Sun,
  Users,
  X,
} from "lucide-react";
import clsx from "clsx";
import type { GroupDetail } from "../../types/api";
import { useGroupDetail } from "../../hooks/useGroups";
import { SseStatusContext, useActivitySse } from "../../hooks/useActivity";
import { useAuth } from "../../hooks/useAuth";
import { useTheme } from "../../hooks/useTheme";
import { downloadUrl } from "../../lib/api";
import { PageSpinner } from "../ui/Spinner";
import { ErrorState } from "../ui/EmptyState";
import { CopyChip } from "../ui/CopyChip";
import { Avatar } from "../ui/MemberChip";
import { Menu, MenuItem, MenuLink } from "../ui/Menu";

interface GroupCtx {
  gid: number;
  group: GroupDetail;
}

const GroupContext = createContext<GroupCtx | null>(null);

export function useGroupCtx(): GroupCtx {
  const ctx = useContext(GroupContext);
  if (!ctx) throw new Error("useGroupCtx must be used inside the group shell");
  return ctx;
}

const NAV = [
  { to: "", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "companies", label: "Companies", icon: Building2, end: false },
  { to: "board", label: "Board", icon: Kanban, end: false },
  { to: "portals", label: "Portals", icon: Globe, end: false },
  { to: "resumes", label: "Resumes", icon: FileText, end: false },
  { to: "activity", label: "Activity", icon: ActivityIcon, end: false },
  { to: "members", label: "Members", icon: Users, end: false },
];

export function GroupShell() {
  const params = useParams();
  const gid = Number(params.gid);
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();
  const { theme, toggle: toggleTheme } = useTheme();
  const detail = useGroupDetail(gid);
  const sseConnected = useActivitySse(gid);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Remember this group for auto-redirect from the picker.
  useEffect(() => {
    if (detail.data) localStorage.setItem("last_group", String(detail.data.id));
  }, [detail.data]);

  // Drawer closes on route change and on Esc.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);
  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawerOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  if (!Number.isFinite(gid)) {
    return <Navigate to="/" replace />;
  }

  if (detail.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <PageSpinner label="Opening group" />
      </div>
    );
  }

  if (detail.isError || !detail.data) {
    localStorage.removeItem("last_group");
    return (
      <div className="mx-auto flex min-h-screen max-w-lg flex-col justify-center gap-4 p-6">
        <ErrorState
          message="Couldn't open this group. It may not exist, or you are not a member. Retry, or go back to your groups."
          onRetry={() => detail.refetch()}
        />
        <button className="btn-ghost self-center" onClick={() => navigate("/")}>
          Back to my groups
        </button>
      </div>
    );
  }

  const group = detail.data;

  // Owner-only pending-request count; drives the Members nav badge.
  const pendingCount =
    user != null && group.owner_id === user.id ? (group.pending_request_count ?? 0) : 0;

  const sidebar = (
    <nav className="flex h-full flex-col gap-0.5 p-4" aria-label="Group navigation">
      <div className="mb-5 px-3">
        <span className="text-base font-semibold tracking-tight text-ink">JobSquad</span>
      </div>
      <NavLink
        to="/"
        onClick={() => localStorage.removeItem("last_group")}
        className="nav-item"
      >
        <LayoutGrid className="h-4 w-4" aria-hidden />
        Groups
      </NavLink>
      <div className="my-2 h-px bg-line" aria-hidden />
      {NAV.map((item) => (
        <NavLink
          key={item.label}
          to={item.to === "" ? `/g/${gid}` : `/g/${gid}/${item.to}`}
          end={item.end}
          className={({ isActive }) => clsx("nav-item", isActive && "nav-item-active")}
        >
          <item.icon className="h-4 w-4" aria-hidden />
          {item.label}
          {item.to === "members" && pendingCount > 0 && (
            <span
              className="ml-auto inline-flex min-w-[18px] items-center justify-center rounded-full bg-focus/15 px-1.5 py-0.5 font-mono text-[10px] font-medium text-focus"
              aria-label={`${pendingCount} pending join request${pendingCount === 1 ? "" : "s"}`}
            >
              {pendingCount}
            </span>
          )}
        </NavLink>
      ))}
      <div className="mt-auto space-y-1.5 px-3 pt-4">
        <div className="flex items-center gap-2 text-small text-muted">
          <span
            className={clsx(
              "h-1.5 w-1.5 rounded-full",
              sseConnected ? "bg-status-offer-dot" : "bg-muted/40",
            )}
            aria-hidden
          />
          {sseConnected ? "Live updates on" : "Reconnecting live updates"}
        </div>
        <p className="font-mono text-[11px] text-muted/80">
          {group.member_count} member{group.member_count === 1 ? "" : "s"}
        </p>
      </div>
    </nav>
  );

  return (
    <GroupContext.Provider value={{ gid, group }}>
      <SseStatusContext.Provider value={sseConnected}>
        <div className="flex min-h-screen">
          {/* Desktop sidebar */}
          <aside className="hidden w-60 shrink-0 border-r border-line bg-canvas lg:block">
            <div className="sticky top-0 h-screen">{sidebar}</div>
          </aside>

          {/* Mobile drawer */}
          {drawerOpen && (
            <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true">
              <div
                className="overlay-in absolute inset-0 bg-scrim/60"
                onClick={() => setDrawerOpen(false)}
              />
              <aside className="overlay-in absolute inset-y-0 left-0 w-64 border-r border-line bg-canvas shadow-pop">
                <button
                  className="absolute right-3 top-4 rounded-md p-1.5 text-muted hover:text-ink"
                  onClick={() => setDrawerOpen(false)}
                  aria-label="Close navigation"
                >
                  <X className="h-4 w-4" aria-hidden />
                </button>
                {sidebar}
              </aside>
            </div>
          )}

          <div className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-paper px-4 sm:px-6">
              <button
                className="rounded-md p-1.5 text-muted hover:bg-hover hover:text-ink lg:hidden"
                onClick={() => setDrawerOpen(true)}
                aria-label="Open navigation"
              >
                <MenuIcon className="h-5 w-5" aria-hidden />
              </button>
              <h1 className="min-w-0 truncate text-sm font-semibold text-ink">{group.name}</h1>
              <div className="hidden sm:block">
                <CopyChip value={group.invite_code} />
              </div>
              <div className="ml-auto flex items-center gap-2">
                <Menu
                  trigger={(open) => (
                    <span className={clsx("btn-ghost", open && "bg-hover")}>
                      <Download className="h-4 w-4" aria-hidden />
                      <span className="hidden sm:inline">Export</span>
                      <ChevronDown className="h-3.5 w-3.5 text-muted" aria-hidden />
                    </span>
                  )}
                >
                  {(close) => (
                    <>
                      <MenuLink
                        href={downloadUrl(`/api/groups/${gid}/export/applications.csv`)}
                        onClick={close}
                      >
                        <Download className="h-4 w-4 text-muted" aria-hidden />
                        Applications CSV
                      </MenuLink>
                      <MenuLink
                        href={downloadUrl(`/api/groups/${gid}/export/companies.csv`)}
                        onClick={close}
                      >
                        <Download className="h-4 w-4 text-muted" aria-hidden />
                        Companies CSV
                      </MenuLink>
                      <MenuLink
                        href={downloadUrl(`/api/groups/${gid}/export/portals.csv`)}
                        onClick={close}
                      >
                        <Download className="h-4 w-4 text-muted" aria-hidden />
                        Portals CSV
                      </MenuLink>
                    </>
                  )}
                </Menu>
                {user && (
                  <Menu
                    trigger={() => (
                      <span className="flex items-center gap-2 rounded-md p-1 pr-2 transition-colors duration-150 ease-out hover:bg-hover">
                        <Avatar username={user.username} displayName={user.display_name} size="md" />
                        <ChevronDown className="h-3.5 w-3.5 text-muted" aria-hidden />
                      </span>
                    )}
                  >
                    {(close) => (
                      <>
                        <div className="border-b border-line px-3.5 pb-2 pt-1">
                          <p className="text-sm font-medium text-ink">{user.display_name}</p>
                          <p className="font-mono text-xs text-muted">@{user.username}</p>
                        </div>
                        <MenuItem
                          onClick={() => {
                            close();
                            localStorage.removeItem("last_group");
                            navigate("/");
                          }}
                        >
                          <Repeat className="h-4 w-4 text-muted" aria-hidden />
                          Switch group
                        </MenuItem>
                        <MenuItem
                          onClick={() => {
                            close();
                            navigate(`/g/${gid}/settings/ai`);
                          }}
                        >
                          <Sparkles className="h-4 w-4 text-muted" aria-hidden />
                          AI settings
                        </MenuItem>
                        <MenuItem
                          onClick={() => {
                            close();
                            navigate("/connect");
                          }}
                        >
                          <Puzzle className="h-4 w-4 text-muted" aria-hidden />
                          Browser extension
                        </MenuItem>
                        <MenuItem
                          onClick={() => {
                            close();
                            toggleTheme();
                          }}
                        >
                          {theme === "dark" ? (
                            <Sun className="h-4 w-4 text-muted" aria-hidden />
                          ) : (
                            <Moon className="h-4 w-4 text-muted" aria-hidden />
                          )}
                          {theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
                        </MenuItem>
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
                      </>
                    )}
                  </Menu>
                )}
              </div>
            </header>
            <main className="mx-auto w-full max-w-6xl flex-1 p-4 sm:p-6">
              <Outlet />
            </main>
          </div>
        </div>
      </SseStatusContext.Provider>
    </GroupContext.Provider>
  );
}
