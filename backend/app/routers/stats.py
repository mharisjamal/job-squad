"""Group stats: totals, per-member funnel counts + response rate, portal effectiveness."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_current_user, get_session, require_member
from ..models import (
    APPLICATION_STATUSES,
    RESPONSE_STATUSES,
    Application,
    Company,
    GroupMember,
    Portal,
    User,
)
from .portals import portal_stats

router = APIRouter(tags=["stats"])


@router.get("/groups/{gid}/stats")
async def group_stats(
    gid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_member(session, gid, user)

    companies = await session.scalar(
        select(func.count()).select_from(Company).where(Company.group_id == gid)
    )
    portals = (
        await session.scalars(
            select(Portal).where(Portal.group_id == gid).order_by(Portal.created_at)
        )
    ).all()
    members = (
        await session.execute(
            select(GroupMember, User)
            .join(User, User.id == GroupMember.user_id)
            .where(GroupMember.group_id == gid)
            .order_by(GroupMember.joined_at)
        )
    ).all()

    status_rows = (
        await session.execute(
            select(Application.user_id, Application.status, func.count())
            .join(Company, Company.id == Application.company_id)
            .where(Company.group_id == gid)
            .group_by(Application.user_id, Application.status)
        )
    ).all()
    by_member: dict[int, dict[str, int]] = {}
    total_applications = 0
    for member_id, status, count in status_rows:
        by_member.setdefault(member_id, {})[status] = int(count)
        total_applications += int(count)

    per_member = []
    for _member, member_user in members:
        counts = {status: by_member.get(member_user.id, {}).get(status, 0)
                  for status in APPLICATION_STATUSES}
        counts["total"] = sum(counts.values())
        base = counts["total"] - counts["saved"]
        responses = sum(counts[status] for status in RESPONSE_STATUSES)
        per_member.append(
            {
                "user_id": member_user.id,
                "username": member_user.username,
                "display_name": member_user.display_name,
                "counts": counts,
                "response_rate": (responses / base) if base > 0 else None,
            }
        )

    effectiveness = await portal_stats(session, [p.id for p in portals])
    per_portal = [
        {
            "portal_id": p.id,
            "name": p.name,
            "applications_via": effectiveness[p.id]["applications_via"],
            "interviews_via": effectiveness[p.id]["interviews_via"],
            "offers_via": effectiveness[p.id]["offers_via"],
        }
        for p in portals
    ]
    per_portal.sort(key=lambda entry: (-entry["applications_via"], entry["name"].lower()))

    return {
        "group": {
            "companies": int(companies or 0),
            "portals": len(portals),
            "applications": total_applications,
            "members": len(members),
        },
        "per_member": per_member,
        "per_portal": per_portal,
    }
