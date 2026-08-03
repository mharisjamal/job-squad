import { useState } from "react";
import { Link } from "react-router-dom";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import type { DragEndEvent, DragStartEvent } from "@dnd-kit/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Globe, Kanban } from "lucide-react";
import clsx from "clsx";
import { useGroupCtx } from "../components/layout/Shell";
import { useMyApplications } from "../hooks/useApplications";
import { useToast } from "../components/ui/Toast";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Spinner";
import { STATUSES } from "../config/statuses";
import { apiSend, ApiError } from "../lib/api";
import { daysUntil, formatDate } from "../lib/format";
import type { ApplicationFull, ApplicationStatus } from "../types/api";

function FollowUpBadge({ followUpAt }: { followUpAt: string | null }) {
  const days = daysUntil(followUpAt);
  if (days === null) return null;
  const urgent = days <= 3;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[10px]",
        urgent
          ? "bg-status-interview-bg text-status-interview-text"
          : "bg-canvas text-muted",
      )}
    >
      <CalendarClock className="h-3 w-3" aria-hidden />
      {days < 0 ? `overdue ${-days}d` : days === 0 ? "follow up today" : `follow up in ${days}d`}
    </span>
  );
}

function CardBody({ app }: { app: ApplicationFull }) {
  return (
    <>
      <p className="text-sm font-medium leading-snug text-ink">{app.company_name}</p>
      {app.job_title && (
        // One quiet line, clipped rather than wrapped so cards stay uniform.
        <p className="mt-0.5 truncate text-[11px] text-muted" title={app.job_title}>
          {app.job_title}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {app.applied_at && (
          <span className="font-mono text-[10px] text-muted">{formatDate(app.applied_at)}</span>
        )}
        {app.applied_via_portal_name && (
          <span className="inline-flex items-center gap-1 rounded-full bg-canvas px-2 py-0.5 font-mono text-[10px] text-muted">
            <Globe className="h-3 w-3" aria-hidden />
            {app.applied_via_portal_name}
          </span>
        )}
        <FollowUpBadge followUpAt={app.follow_up_at} />
      </div>
    </>
  );
}

function BoardCard({ app }: { app: ApplicationFull }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: app.id,
    data: { app },
  });
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      style={
        transform
          ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` }
          : undefined
      }
      className={clsx(
        "cursor-grab rounded-md border border-line bg-paper p-3 transition-colors duration-150 ease-out",
        "hover:bg-hover focus-visible:outline-none",
        isDragging && "z-20 opacity-40",
      )}
      aria-label={`${app.company_name}, drag to change status`}
    >
      <CardBody app={app} />
    </div>
  );
}

function Column({
  status,
  label,
  color,
  apps,
}: {
  status: ApplicationStatus;
  label: string;
  color: string;
  apps: ApplicationFull[];
}) {
  const { setNodeRef, isOver } = useDroppable({ id: status });
  return (
    <div
      ref={setNodeRef}
      aria-label={`${label} column`}
      className={clsx(
        "flex w-64 shrink-0 flex-col rounded-lg bg-canvas",
        isOver ? "border-2 border-dashed border-muted/60" : "border border-line",
      )}
    >
      <div className="flex items-center gap-2 px-3 py-2.5">
        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} aria-hidden />
        <span className="text-small font-medium text-ink">{label}</span>
        <span className="ml-auto font-mono text-xs text-muted">{apps.length}</span>
      </div>
      <div className="flex min-h-24 flex-1 flex-col gap-2 p-2 pt-0">
        {apps.map((a) => (
          <BoardCard key={a.id} app={a} />
        ))}
        {apps.length === 0 && (
          <div className="flex flex-1 items-center justify-center rounded-md border border-dashed border-line p-3">
            <span className="text-[11px] text-muted/70">Drop here</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Board() {
  const { gid } = useGroupCtx();
  const myApps = useMyApplications(gid);
  const qc = useQueryClient();
  const { toast } = useToast();
  const [activeApp, setActiveApp] = useState<ApplicationFull | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  );

  const move = useMutation({
    mutationFn: ({ app, status }: { app: ApplicationFull; status: ApplicationStatus }) =>
      apiSend<ApplicationFull>("PUT", `/api/companies/${app.company_id}/application`, {
        status,
        applied_via_portal_id: app.applied_via_portal_id,
        applied_at: app.applied_at,
        follow_up_at: app.follow_up_at,
        url: app.url,
        notes: app.notes,
      }),
    onMutate: async ({ app, status }) => {
      await qc.cancelQueries({ queryKey: ["applications", gid, "me"] });
      const previous = qc.getQueryData<ApplicationFull[]>(["applications", gid, "me"]);
      qc.setQueryData<ApplicationFull[]>(["applications", gid, "me"], (prev) =>
        prev?.map((a) => (a.id === app.id ? { ...a, status } : a)),
      );
      return { previous };
    },
    onError: (err, _vars, context) => {
      if (context?.previous) {
        qc.setQueryData(["applications", gid, "me"], context.previous);
      }
      toast(
        err instanceof ApiError
          ? err.message
          : "Couldn't move the card; it was put back. Retry.",
        "error",
      );
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["applications", gid] });
      void qc.invalidateQueries({ queryKey: ["companies", gid] });
      void qc.invalidateQueries({ queryKey: ["company"] });
      void qc.invalidateQueries({ queryKey: ["stats", gid] });
      void qc.invalidateQueries({ queryKey: ["portals", gid] });
      void qc.invalidateQueries({ queryKey: ["activity", gid] });
    },
  });

  const onDragStart = (e: DragStartEvent) => {
    const app = (e.active.data.current as { app?: ApplicationFull } | undefined)?.app;
    setActiveApp(app ?? null);
  };

  const onDragEnd = (e: DragEndEvent) => {
    setActiveApp(null);
    const app = (e.active.data.current as { app?: ApplicationFull } | undefined)?.app;
    const over = e.over?.id;
    if (!app || typeof over !== "string") return;
    const status = over as ApplicationStatus;
    if (status === app.status) return;
    move.mutate({ app, status });
  };

  if (myApps.isPending) {
    return (
      <div className="flex gap-3 overflow-x-auto pb-2">
        {STATUSES.map((s) => (
          <Skeleton key={s.value} className="h-72 w-64 shrink-0" />
        ))}
      </div>
    );
  }

  if (myApps.isError) {
    return <ErrorState message="Couldn't load your board. Retry." onRetry={() => myApps.refetch()} />;
  }

  const apps = myApps.data;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink">Board</h1>
          <p className="text-sm text-muted">Your applications only. Drag a card to change its status.</p>
        </div>
        <span className="font-mono text-xs text-muted">
          {apps.length} application{apps.length === 1 ? "" : "s"}
        </span>
      </div>

      {apps.length === 0 ? (
        <EmptyState
          icon={Kanban}
          title="Your board is empty"
          description="Set a status on any company in the shared pool and it becomes a card here."
          action={
            <Link to={`/g/${gid}/companies`} className="btn-primary">
              Browse companies
            </Link>
          }
        />
      ) : (
        <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
          <div className="flex items-stretch gap-3 overflow-x-auto pb-3">
            {STATUSES.map((s) => (
              <Column
                key={s.value}
                status={s.value}
                label={s.label}
                color={s.dot}
                apps={apps.filter((a) => a.status === s.value)}
              />
            ))}
          </div>
          <DragOverlay>
            {activeApp && (
              <div className="w-60 rounded-md border border-line bg-paper p-3 shadow-drag">
                <CardBody app={activeApp} />
              </div>
            )}
          </DragOverlay>
        </DndContext>
      )}
    </div>
  );
}
