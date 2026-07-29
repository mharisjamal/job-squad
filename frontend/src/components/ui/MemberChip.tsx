import clsx from "clsx";
import type { ApplicationBrief, ApplicationStatus, GroupMember } from "../../types/api";
import { statusLabel, statusMeta } from "../../config/statuses";
import { avatarColor, initials } from "../../lib/format";

export function Avatar({
  username,
  displayName,
  size = "md",
  className,
}: {
  username: string;
  displayName: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const sizes = {
    sm: "h-6 w-6 text-[10px]",
    md: "h-8 w-8 text-xs",
    lg: "h-10 w-10 text-sm",
  } as const;
  return (
    <span
      className={clsx(
        "inline-flex shrink-0 items-center justify-center rounded-full font-medium text-white",
        sizes[size],
        className,
      )}
      style={{ backgroundColor: avatarColor(username) }}
      title={displayName}
      aria-label={displayName}
    >
      {initials(displayName)}
    </span>
  );
}

/**
 * Signature element: a 24px member avatar wearing a 2px ring in that member's
 * status color for the company in question. Dim gray outline ring = not applied.
 * Tooltip "name: status".
 */
export function MemberChip({
  username,
  displayName,
  status,
}: {
  username: string;
  displayName: string;
  status: ApplicationStatus | null;
}) {
  const title = status ? `${displayName}: ${statusLabel(status)}` : `${displayName}: not applied`;
  return (
    <span
      className="inline-flex h-[30px] w-[30px] items-center justify-center rounded-full bg-paper"
      title={title}
      aria-label={title}
    >
      <span
        className="inline-flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-medium"
        style={
          status
            ? {
                backgroundColor: avatarColor(username),
                color: "#FFFFFF",
                boxShadow: `0 0 0 2px ${statusMeta(status).dot}`,
              }
            : {
                backgroundColor: "#FFFFFF",
                color: "#5C6470",
                boxShadow: "0 0 0 2px #D6D6D2",
              }
        }
      >
        {initials(displayName)}
      </span>
    </span>
  );
}

/**
 * The Squad row: overlapping MemberChips for every group member, ringed by
 * their application status on this company. Used on company rows + dashboard.
 */
export function SquadRow({
  members,
  applications,
}: {
  members: GroupMember[];
  applications: Pick<ApplicationBrief, "user_id" | "status">[];
}) {
  return (
    <span className="flex items-center -space-x-[7px]">
      {members.map((m) => {
        const app = applications.find((a) => a.user_id === m.user_id);
        return (
          <MemberChip
            key={m.user_id}
            username={m.username}
            displayName={m.display_name}
            status={app?.status ?? null}
          />
        );
      })}
    </span>
  );
}
