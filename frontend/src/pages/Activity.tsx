import { Activity as ActivityIcon } from "lucide-react";
import clsx from "clsx";
import { useGroupCtx } from "../components/layout/Shell";
import { useActivityFeed, useSseConnected } from "../hooks/useActivity";
import { ActivityItem } from "../components/ActivityItem";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Spinner";
import { dayLabel } from "../lib/format";
import type { Activity } from "../types/api";

function groupByDay(items: Activity[]): { label: string; items: Activity[] }[] {
  const groups: { label: string; items: Activity[] }[] = [];
  for (const item of items) {
    const label = dayLabel(item.created_at);
    const last = groups[groups.length - 1];
    if (last && last.label === label) {
      last.items.push(item);
    } else {
      groups.push({ label, items: [item] });
    }
  }
  return groups;
}

export default function ActivityPage() {
  const { gid } = useGroupCtx();
  const sseConnected = useSseConnected();
  // SSE prepends live rows; while disconnected we poll every 30s instead.
  const feed = useActivityFeed(gid, { poll: !sseConnected });

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink">Activity</h1>
          <p className="text-sm text-muted">Everything your squad has been up to.</p>
        </div>
        <span
          className={clsx(
            "flex items-center gap-1.5 rounded-full border border-line bg-paper px-2.5 py-1 font-mono text-[11px] text-muted",
          )}
        >
          <span
            className={clsx(
              "h-1.5 w-1.5 rounded-full",
              sseConnected ? "bg-[#059669]" : "bg-muted/50",
            )}
            aria-hidden
          />
          {sseConnected ? "Live" : "Polling"}
        </span>
      </div>

      {feed.isPending ? (
        <div className="space-y-2">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      ) : feed.isError ? (
        <ErrorState message="Couldn't load the activity feed. Retry." onRetry={() => feed.refetch()} />
      ) : feed.data.length === 0 ? (
        <EmptyState
          icon={ActivityIcon}
          title="Nothing yet"
          description="Squad actions show up here: added companies, status moves, comments, new members."
        />
      ) : (
        <div className="space-y-6">
          {groupByDay(feed.data).map((g) => (
            <section key={g.label}>
              <h2 className="mb-1.5 font-mono text-xs font-medium text-muted">{g.label}</h2>
              <div className="card divide-y divide-line px-4 py-1">
                {g.items.map((a) => (
                  <ActivityItem key={a.id} activity={a} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
