import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Bell, Building2, CalendarClock, Globe, Send } from "lucide-react";
import { useGroupCtx } from "../components/layout/Shell";
import { useAuth } from "../hooks/useAuth";
import { useStats } from "../hooks/useStats";
import { useCompanies } from "../hooks/useCompanies";
import { useMyApplications } from "../hooks/useApplications";
import { useActivityFeed } from "../hooks/useActivity";
import { ActivityItem } from "../components/ActivityItem";
import { StatusBadge } from "../components/ui/StatusBadge";
import { Avatar, SquadRow } from "../components/ui/MemberChip";
import { ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Spinner";
import { STATUSES } from "../config/statuses";
import { daysUntil } from "../lib/format";
import type { MemberStats } from "../types/api";

function KpiCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card p-4">
      <p className="text-small font-medium text-muted">{label}</p>
      <p className="mt-1 font-mono text-2xl font-medium text-ink">{value}</p>
      {sub && <p className="mt-0.5 text-small text-muted/90">{sub}</p>}
    </div>
  );
}

function SquadBar({ member, max }: { member: MemberStats; max: number }) {
  const total = member.counts.total;
  return (
    <div className="flex items-center gap-3">
      <div className="flex w-40 min-w-0 items-center gap-2">
        <Avatar username={member.username} displayName={member.display_name} size="sm" />
        <span className="truncate text-sm text-ink">{member.display_name}</span>
      </div>
      <div className="h-4 flex-1 overflow-hidden rounded bg-canvas">
        {total > 0 && (
          <div className="flex h-full" style={{ width: `${(total / max) * 100}%` }}>
            {STATUSES.map((s) => {
              const count = member.counts[s.value];
              if (count === 0) return null;
              return (
                <div
                  key={s.value}
                  className="h-full"
                  style={{ width: `${(count / total) * 100}%`, backgroundColor: s.dot }}
                  title={`${s.label}: ${count}`}
                />
              );
            })}
          </div>
        )}
      </div>
      <span className="w-8 text-right font-mono text-xs text-muted">{total}</span>
    </div>
  );
}

function SectionCard({
  title,
  icon: Icon,
  children,
  action,
}: {
  title: string;
  icon: typeof Building2;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="card p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
          <Icon className="h-4 w-4 text-muted" aria-hidden />
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export default function Dashboard() {
  const { gid, group } = useGroupCtx();
  const { user } = useAuth();
  const stats = useStats(gid);
  const waiting = useCompanies(gid, { status: "not_applied" });
  const myApps = useMyApplications(gid);
  const activity = useActivityFeed(gid);

  const me = stats.data?.per_member.find((m) => m.user_id === user?.id);
  const maxTotal = Math.max(1, ...(stats.data?.per_member.map((m) => m.counts.total) ?? [1]));

  const followUps = (myApps.data ?? [])
    .filter((a) => {
      const d = daysUntil(a.follow_up_at);
      return d !== null && d >= 0 && d <= 7;
    })
    .sort((a, b) => (a.follow_up_at ?? "").localeCompare(b.follow_up_at ?? ""));

  if (stats.isError) {
    return (
      <ErrorState
        message="Couldn't load the dashboard. Retry."
        onRetry={() => stats.refetch()}
      />
    );
  }

  return (
    <div className="space-y-5">
      {/* KPI row */}
      {stats.isPending ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <KpiCard
            label="Applied"
            value={String(me ? me.counts.total - me.counts.saved : 0)}
            sub={me ? `${me.counts.saved} saved for later` : undefined}
          />
          <KpiCard
            label="In interviews"
            value={String(me ? me.counts.assessment + me.counts.interview : 0)}
            sub={me ? `${me.counts.assessment} in assessment` : undefined}
          />
          <KpiCard label="Offers" value={String(me?.counts.offer ?? 0)} />
          <KpiCard
            label="Response rate"
            value={me?.response_rate == null ? "-" : `${Math.round(me.response_rate * 100)}%`}
            sub="Of applications sent"
          />
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Squad comparison */}
        <SectionCard title="Squad comparison" icon={Send}>
          {stats.isPending ? (
            <Skeleton className="h-32" />
          ) : (stats.data?.per_member.length ?? 0) === 0 ? (
            <p className="text-sm text-muted">No members yet.</p>
          ) : (
            <div className="space-y-3">
              {stats.data?.per_member.map((m) => (
                <SquadBar key={m.user_id} member={m} max={maxTotal} />
              ))}
              <div className="flex flex-wrap gap-x-4 gap-y-1 pt-2">
                {STATUSES.map((s) => (
                  <span key={s.value} className="flex items-center gap-1.5 font-mono text-[11px] text-muted">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: s.dot }} aria-hidden />
                    {s.label}
                  </span>
                ))}
              </div>
            </div>
          )}
        </SectionCard>

        {/* Waiting for you */}
        <SectionCard
          title="Waiting for you"
          icon={Bell}
          action={
            <Link
              to={`/g/${gid}/companies?status=not_applied`}
              className="link flex items-center gap-1 text-xs font-medium"
            >
              View all
              <ArrowRight className="h-3 w-3" aria-hidden />
            </Link>
          }
        >
          {waiting.isPending ? (
            <Skeleton className="h-32" />
          ) : waiting.isError ? (
            <p className="text-sm text-muted">Couldn't load companies. Reload the page to retry.</p>
          ) : waiting.data.length === 0 ? (
            <p className="text-sm text-muted">
              You're all caught up: you have an application on every company your squad posted.
            </p>
          ) : (
            <ul className="divide-y divide-line">
              {waiting.data.slice(0, 5).map((c) => (
                <li key={c.id}>
                  <Link
                    to={`/g/${gid}/companies/${c.id}`}
                    className="flex items-center justify-between gap-3 py-2 transition-colors duration-150 ease-out hover:bg-hover"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-ink">{c.name}</span>
                      <span className="block text-small text-muted">
                        Posted by {c.created_by_username}
                      </span>
                    </span>
                    <SquadRow members={group.members} applications={c.applications} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>

        {/* Upcoming follow-ups */}
        <SectionCard title="Upcoming follow-ups" icon={CalendarClock}>
          {myApps.isPending ? (
            <Skeleton className="h-24" />
          ) : myApps.isError ? (
            <p className="text-sm text-muted">Couldn't load your applications. Reload to retry.</p>
          ) : followUps.length === 0 ? (
            <p className="text-sm text-muted">Nothing due in the next 7 days.</p>
          ) : (
            <ul className="divide-y divide-line">
              {followUps.map((a) => {
                const days = daysUntil(a.follow_up_at) ?? 0;
                return (
                  <li key={a.id} className="flex items-center justify-between gap-3 py-2.5">
                    <Link
                      to={`/g/${gid}/companies/${a.company_id}`}
                      className="min-w-0 truncate text-sm font-medium text-ink hover:underline"
                    >
                      {a.company_name}
                    </Link>
                    <span className="flex shrink-0 items-center gap-2">
                      <StatusBadge status={a.status} />
                      <span
                        className={`font-mono text-xs ${days <= 1 ? "text-status-interview" : "text-muted"}`}
                      >
                        {days === 0 ? "today" : days === 1 ? "tomorrow" : `in ${days}d`}
                      </span>
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </SectionCard>

        {/* Portal effectiveness */}
        <SectionCard title="Portal effectiveness" icon={Globe}>
          {stats.isPending ? (
            <Skeleton className="h-24" />
          ) : (stats.data?.per_portal.length ?? 0) === 0 ? (
            <p className="text-sm text-muted">
              No portals yet.{" "}
              <Link to={`/g/${gid}/portals`} className="link font-medium">
                Add the first one
              </Link>{" "}
              so the squad can compare where applications convert.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-small font-medium text-muted">
                  <th className="pb-2 font-medium">Portal</th>
                  <th className="pb-2 text-right font-medium">Applications</th>
                  <th className="pb-2 text-right font-medium">Interviews</th>
                  <th className="pb-2 text-right font-medium">Offers</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {stats.data?.per_portal.map((p) => (
                  <tr key={p.portal_id}>
                    <td className="py-2 font-medium text-ink">{p.name}</td>
                    <td className="py-2 text-right font-mono text-muted">{p.applications_via}</td>
                    <td className="py-2 text-right font-mono text-muted">{p.interviews_via}</td>
                    <td className="py-2 text-right font-mono text-muted">{p.offers_via}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </SectionCard>
      </div>

      {/* Recent activity */}
      <SectionCard
        title="Recent activity"
        icon={Bell}
        action={
          <Link
            to={`/g/${gid}/activity`}
            className="link flex items-center gap-1 text-xs font-medium"
          >
            Full feed
            <ArrowRight className="h-3 w-3" aria-hidden />
          </Link>
        }
      >
        {activity.isPending ? (
          <Skeleton className="h-32" />
        ) : activity.isError ? (
          <p className="text-sm text-muted">Couldn't load activity. Reload to retry.</p>
        ) : activity.data.length === 0 ? (
          <p className="text-sm text-muted">
            Quiet so far. Add a company or a portal to get the squad moving.
          </p>
        ) : (
          <div className="divide-y divide-line">
            {activity.data.slice(0, 8).map((a) => (
              <ActivityItem key={a.id} activity={a} />
            ))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}
