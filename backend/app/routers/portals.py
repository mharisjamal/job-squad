"""Portal endpoints: list with per-member statuses + stats, CRUD, my-status upsert."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..activity import record
from ..deps import (
    get_current_user,
    get_portal_for_member,
    get_session,
    require_member,
)
from ..models import Application, Group, Portal, PortalStatus, User, utcnow
from ..schemas import (
    PortalCreateIn,
    PortalPatchIn,
    PortalStatusPutIn,
    serialize_portal,
    serialize_portal_status,
)

router = APIRouter(tags=["portals"])

_EMPTY_STATS = {"applications_via": 0, "interviews_via": 0, "offers_via": 0}


async def portal_stats(session: AsyncSession, portal_ids: list[int]) -> dict[int, dict]:
    """Effectiveness per portal from applications.applied_via_portal_id."""
    stats = {pid: dict(_EMPTY_STATS) for pid in portal_ids}
    if not portal_ids:
        return stats
    rows = (
        await session.execute(
            select(Application.applied_via_portal_id, Application.status, func.count())
            .where(Application.applied_via_portal_id.in_(portal_ids))
            .group_by(Application.applied_via_portal_id, Application.status)
        )
    ).all()
    for pid, status, count in rows:
        entry = stats[pid]
        entry["applications_via"] += int(count)
        if status in ("assessment", "interview"):
            entry["interviews_via"] += int(count)
        elif status == "offer":
            entry["offers_via"] += int(count)
    return stats


async def _portal_statuses(
    session: AsyncSession, portal_ids: list[int]
) -> dict[int, list[dict]]:
    statuses: dict[int, list[dict]] = {pid: [] for pid in portal_ids}
    if not portal_ids:
        return statuses
    rows = (
        await session.execute(
            select(PortalStatus, User)
            .join(User, User.id == PortalStatus.user_id)
            .where(PortalStatus.portal_id.in_(portal_ids))
            .order_by(PortalStatus.updated_at.desc())
        )
    ).all()
    for status_row, status_user in rows:
        statuses[status_row.portal_id].append(serialize_portal_status(status_row, status_user))
    return statuses


async def _serialize_one(session: AsyncSession, portal: Portal) -> dict:
    creator = await session.get(User, portal.created_by)
    statuses = await _portal_statuses(session, [portal.id])
    stats = await portal_stats(session, [portal.id])
    return serialize_portal(
        portal, creator.username if creator else "", statuses[portal.id], stats[portal.id]
    )


@router.get("/groups/{gid}/portals")
async def list_portals(
    gid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    await require_member(session, gid, user)
    rows = (
        await session.execute(
            select(Portal, User.username)
            .join(User, User.id == Portal.created_by)
            .where(Portal.group_id == gid)
            .order_by(Portal.created_at)
        )
    ).all()
    portal_ids = [portal.id for portal, _ in rows]
    statuses = await _portal_statuses(session, portal_ids)
    stats = await portal_stats(session, portal_ids)
    return [
        serialize_portal(portal, username, statuses[portal.id], stats[portal.id])
        for portal, username in rows
    ]


@router.post("/groups/{gid}/portals")
async def create_portal(
    gid: int,
    body: PortalCreateIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_member(session, gid, user)
    portal = Portal(group_id=gid, name=body.name, url=body.url, notes=body.notes,
                    region=body.region, created_by=user.id)
    session.add(portal)
    await session.flush()
    await record(
        session,
        request.app.state.broker,
        group_id=gid,
        user=user,
        type_="portal_added",
        portal=portal,
    )
    await session.commit()
    return serialize_portal(portal, user.username, [], dict(_EMPTY_STATS))


@router.patch("/portals/{pid}")
async def patch_portal(
    pid: int,
    body: PortalPatchIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    portal = await get_portal_for_member(session, pid, user)
    provided = body.model_dump(exclude_unset=True)
    if "name" in provided:
        name = (provided["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="name must not be blank")
        portal.name = name
    for field in ("url", "notes", "region"):
        if field in provided:
            setattr(portal, field, provided[field])
    await session.commit()
    return await _serialize_one(session, portal)


@router.delete("/portals/{pid}")
async def delete_portal(
    pid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    portal = await get_portal_for_member(session, pid, user)
    group = await session.get(Group, portal.group_id)
    if portal.created_by != user.id and (group is None or group.owner_id != user.id):
        raise HTTPException(
            status_code=403, detail="Only the poster or the group owner can delete a portal"
        )
    await session.delete(portal)
    await session.commit()
    return {"ok": True}


@router.put("/portals/{pid}/status")
async def upsert_portal_status(
    pid: int,
    body: PortalStatusPutIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    portal = await get_portal_for_member(session, pid, user)
    provided = body.model_dump(exclude_unset=True)
    if body.status == "none":
        row = await session.scalar(
            select(PortalStatus).where(
                PortalStatus.portal_id == pid, PortalStatus.user_id == user.id
            )
        )
        if row is not None:
            await session.delete(row)
            await record(
                session,
                request.app.state.broker,
                group_id=portal.group_id,
                user=user,
                type_="portal_status_changed",
                portal=portal,
                detail={"to": "none"},
            )
            await session.commit()
        return {
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "status": "none",
            "rating": None,
            "notes": None,
            "updated_at": None,
        }
    saved_row: PortalStatus | None = None
    for _attempt in range(2):
        row = await session.scalar(
            select(PortalStatus).where(
                PortalStatus.portal_id == pid, PortalStatus.user_id == user.id
            )
        )
        changed = row is None or row.status != body.status
        if row is None:
            row = PortalStatus(portal_id=pid, user_id=user.id, status=body.status)
            session.add(row)
        # Merge semantics (same contract as the application PUT): status is
        # required; omitted rating/notes are preserved; explicit null clears.
        row.status = body.status
        if "rating" in provided:
            row.rating = provided["rating"]
        if "notes" in provided:
            row.notes = provided["notes"]
        row.updated_at = utcnow()
        try:
            await session.flush()
        except IntegrityError:
            # Concurrent request inserted my row first: retry as an update.
            await session.rollback()
            portal = await get_portal_for_member(session, pid, user)
            continue
        if changed:
            await record(
                session,
                request.app.state.broker,
                group_id=portal.group_id,
                user=user,
                type_="portal_status_changed",
                portal=portal,
                detail={"to": body.status},
            )
        await session.commit()
        saved_row = row
        break
    if saved_row is None:
        raise HTTPException(status_code=409, detail="Concurrent update, please retry")
    return serialize_portal_status(saved_row, user)
