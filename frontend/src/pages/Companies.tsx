import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Building2, Plus, Search } from "lucide-react";
import { useGroupCtx } from "../components/layout/Shell";
import { useAuth } from "../hooks/useAuth";
import { useAddCompany, useCompanies, useUpsertApplication } from "../hooks/useCompanies";
import { useDebouncedValue } from "../hooks/useDebounced";
import { useToast } from "../components/ui/Toast";
import { CompanyFormDialog } from "../components/CompanyFormDialog";
import { SquadRow } from "../components/ui/MemberChip";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Spinner";
import { STATUSES, statusMeta } from "../config/statuses";
import { timeAgo } from "../lib/format";
import { ApiError } from "../lib/api";
import type { ApplicationStatus, Company } from "../types/api";

const NOT_APPLIED = "not_applied";

/** Inline "My status" select: upserts my application with the values I have. */
function MyStatusSelect({
  company,
  myUserId,
  gid,
}: {
  company: Company;
  myUserId: number;
  gid: number;
}) {
  const upsert = useUpsertApplication(gid);
  const { toast } = useToast();
  const mine = company.applications.find((a) => a.user_id === myUserId);

  return (
    <select
      className="input h-8 w-36 px-2 py-0 font-mono text-xs"
      value={mine?.status ?? ""}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => {
        e.stopPropagation();
        const status = e.target.value as ApplicationStatus | "";
        if (!status) return;
        upsert.mutate(
          {
            cid: company.id,
            payload: mine ? { status, applied_at: mine.applied_at } : { status },
          },
          {
            onError: (err) =>
              toast(
                err instanceof ApiError ? err.message : "Couldn't update your status. Retry.",
                "error",
              ),
          },
        );
      }}
      disabled={upsert.isPending}
      aria-label={`My status for ${company.name}`}
      style={mine ? { color: statusMeta(mine.status).text } : undefined}
    >
      <option value="" disabled>
        Set status...
      </option>
      {STATUSES.map((s) => (
        <option key={s.value} value={s.value}>
          {s.label}
        </option>
      ))}
    </select>
  );
}

function TagPills({ tags }: { tags: string[] }) {
  if (tags.length === 0) return <span className="text-xs text-muted/50">-</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {tags.map((t) => (
        <span
          key={t}
          className="rounded-full bg-canvas px-2 py-0.5 font-mono text-[11px] text-muted"
        >
          {t}
        </span>
      ))}
    </span>
  );
}

export default function Companies() {
  const { gid, group } = useGroupCtx();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();

  const statusFilter = searchParams.get("status") ?? "";
  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);

  const companies = useCompanies(gid, {
    q: debouncedSearch || undefined,
    status: statusFilter || undefined,
    tag: tagFilter || undefined,
  });
  // Unfiltered list just to harvest the tag vocabulary for the filter select.
  const allCompanies = useCompanies(gid, {});
  const addCompany = useAddCompany(gid);
  const [addOpen, setAddOpen] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const allTags = useMemo(() => {
    const set = new Set<string>();
    for (const c of allCompanies.data ?? []) for (const t of c.tags) set.add(t);
    return [...set].sort((a, b) => a.localeCompare(b));
  }, [allCompanies.data]);

  const setStatusFilter = (value: string) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set("status", value);
        else next.delete("status");
        return next;
      },
      { replace: true },
    );
  };

  const hasFilters = Boolean(debouncedSearch || statusFilter || tagFilter);
  const myUserId = user?.id ?? -1;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink">Companies</h1>
          <p className="text-sm text-muted">The squad's shared pool. Anyone can add one.</p>
        </div>
        <button
          className="btn-primary"
          onClick={() => {
            setAddError(null);
            setAddOpen(true);
          }}
        >
          <Plus className="h-4 w-4" aria-hidden />
          Add company
        </button>
      </div>

      {/* Toolbar */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
            aria-hidden
          />
          <input
            className="input pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or location"
            aria-label="Search companies"
          />
        </div>
        <select
          className="input sm:w-48"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filter by my status"
        >
          <option value="">All companies</option>
          <option value={NOT_APPLIED}>Not applied by me</option>
          {STATUSES.map((s) => (
            <option key={s.value} value={s.value}>
              My status: {s.label}
            </option>
          ))}
        </select>
        <select
          className="input sm:w-40"
          value={tagFilter}
          onChange={(e) => setTagFilter(e.target.value)}
          aria-label="Filter by tag"
        >
          <option value="">All tags</option>
          {allTags.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      {companies.isPending ? (
        <div className="space-y-2">
          <Skeleton className="h-11" />
          <Skeleton className="h-11" />
          <Skeleton className="h-11" />
        </div>
      ) : companies.isError ? (
        <ErrorState message="Couldn't load companies. Retry." onRetry={() => companies.refetch()} />
      ) : companies.data.length === 0 ? (
        hasFilters ? (
          <EmptyState
            icon={Search}
            title="No matches"
            description="No companies match these filters. Clear them to see the whole pool."
            action={
              <button
                className="btn-ghost"
                onClick={() => {
                  setSearch("");
                  setTagFilter("");
                  setStatusFilter("");
                }}
              >
                Clear filters
              </button>
            }
          />
        ) : (
          <EmptyState
            icon={Building2}
            title="No companies yet"
            description="Add the first one your squad should apply to."
            action={
              <button className="btn-primary" onClick={() => setAddOpen(true)}>
                <Plus className="h-4 w-4" aria-hidden />
                Add company
              </button>
            }
          />
        )
      ) : (
        <>
          {/* Desktop table */}
          <div className="card hidden overflow-x-auto md:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-small font-medium text-muted">
                  <th className="px-4 py-2.5 font-medium">Company</th>
                  <th className="px-4 py-2.5 font-medium">Tags</th>
                  <th className="px-4 py-2.5 font-medium">Squad</th>
                  <th className="px-4 py-2.5 font-medium">My status</th>
                  <th className="px-4 py-2.5 text-right font-medium">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {companies.data.map((c) => (
                  <tr
                    key={c.id}
                    className="h-11 cursor-pointer transition-colors duration-150 ease-out hover:bg-hover"
                    onClick={() => navigate(`/g/${gid}/companies/${c.id}`)}
                  >
                    <td className="px-4 py-2">
                      <span className="block font-medium text-ink">{c.name}</span>
                      {c.location && (
                        <span className="block text-small text-muted">{c.location}</span>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      <TagPills tags={c.tags} />
                    </td>
                    <td className="px-4 py-2">
                      <SquadRow members={group.members} applications={c.applications} />
                    </td>
                    <td className="px-4 py-2">
                      <MyStatusSelect company={c} myUserId={myUserId} gid={gid} />
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-muted">
                      {timeAgo(c.updated_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="space-y-3 md:hidden">
            {companies.data.map((c) => (
              <div key={c.id} className="card p-4">
                <Link to={`/g/${gid}/companies/${c.id}`} className="mb-2 block">
                  <span className="block font-medium text-ink">{c.name}</span>
                  {c.location && <span className="block text-small text-muted">{c.location}</span>}
                </Link>
                <div className="mb-3">
                  <TagPills tags={c.tags} />
                </div>
                <div className="flex items-center justify-between gap-3">
                  <SquadRow members={group.members} applications={c.applications} />
                  <MyStatusSelect company={c} myUserId={myUserId} gid={gid} />
                </div>
                <p className="mt-2 font-mono text-[11px] text-muted/80">
                  Updated {timeAgo(c.updated_at)}
                </p>
              </div>
            ))}
          </div>
        </>
      )}

      <CompanyFormDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add a company"
        busy={addCompany.isPending}
        error={addError}
        onSubmit={(payload) =>
          addCompany.mutate(payload, {
            onSuccess: (created) => {
              setAddOpen(false);
              toast(`${created.name} added to the pool`);
            },
            onError: (err) =>
              setAddError(
                err instanceof ApiError ? err.message : "Couldn't add the company. Retry.",
              ),
          })
        }
      />
    </div>
  );
}
