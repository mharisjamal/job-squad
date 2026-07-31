"""Group endpoints: create, list, discover, detail, join, requests, members."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..activity import record
from ..deps import get_current_user, get_group_for_member, get_session
from ..models import (
    Application,
    Company,
    Group,
    GroupJoinRequest,
    GroupMember,
    Portal,
    PortalStatus,
    User,
    utcnow,
)
from ..schemas import (
    NAME_MAX,
    GroupCreateIn,
    GroupJoinIn,
    GroupPatchIn,
    iso_z,
    serialize_group,
    serialize_group_member,
    serialize_join_request,
)

router = APIRouter(tags=["groups"])

# Unambiguous subset of A-Z0-9 (no O/0, I/1/L) for invite codes.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards (and the escape char itself) in user input."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _generate_invite_code(session: AsyncSession) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        taken = await session.scalar(select(Group.id).where(Group.invite_code == code))
        if taken is None:
            return code
    raise HTTPException(status_code=500, detail="Could not generate an invite code")


async def _member_count(session: AsyncSession, group_id: int) -> int:
    count = await session.scalar(
        select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group_id)
    )
    return int(count or 0)


async def _pending_request_count(session: AsyncSession, group_id: int) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(GroupJoinRequest)
        .where(GroupJoinRequest.group_id == group_id, GroupJoinRequest.status == "pending")
    )
    return int(count or 0)


def _require_owner(group: Group, user: User, action: str) -> None:
    if group.owner_id != user.id:
        raise HTTPException(status_code=403, detail=f"Only the group owner can {action}")


@router.post("/groups")
async def create_group(
    body: GroupCreateIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    group = Group(
        name=body.name,
        invite_code=await _generate_invite_code(session),
        owner_id=user.id,
        visibility=body.visibility,
        description=body.description,
    )
    session.add(group)
    await session.flush()
    session.add(GroupMember(group_id=group.id, user_id=user.id, role="owner"))
    await session.commit()
    return serialize_group(group, member_count=1, pending_request_count=0)


@router.get("/groups")
async def list_groups(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    groups = (
        await session.scalars(
            select(Group)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.user_id == user.id)
            .order_by(Group.created_at)
        )
    ).all()
    if not groups:
        return []
    ids = [g.id for g in groups]
    counts = dict(
        (
            await session.execute(
                select(GroupMember.group_id, func.count())
                .where(GroupMember.group_id.in_(ids))
                .group_by(GroupMember.group_id)
            )
        ).all()
    )
    owned_ids = [g.id for g in groups if g.owner_id == user.id]
    pending: dict[int, int] = {}
    if owned_ids:
        pending = dict(
            (
                await session.execute(
                    select(GroupJoinRequest.group_id, func.count())
                    .where(
                        GroupJoinRequest.group_id.in_(owned_ids),
                        GroupJoinRequest.status == "pending",
                    )
                    .group_by(GroupJoinRequest.group_id)
                )
            ).all()
        )
    return [
        serialize_group(
            g,
            counts.get(g.id, 0),
            pending_request_count=(pending.get(g.id, 0) if g.owner_id == user.id else None),
        )
        for g in groups
    ]


@router.get("/groups/discover")
async def discover_groups(
    q: str | None = Query(default=None, max_length=NAME_MAX),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Public groups the caller is NOT already a member of. Private groups are
    never listed (they are code-only and must not leak into the directory)."""
    my_group_ids = select(GroupMember.group_id).where(GroupMember.user_id == user.id)
    stmt = (
        select(Group)
        .where(Group.visibility == "public")
        .where(Group.id.not_in(my_group_ids))
    )
    if q and q.strip():
        needle = f"%{_escape_like(q.strip().lower())}%"
        stmt = stmt.where(
            or_(
                func.lower(Group.name).like(needle, escape="\\"),
                func.lower(func.coalesce(Group.description, "")).like(needle, escape="\\"),
            )
        )
    stmt = stmt.order_by(Group.created_at.desc()).limit(limit).offset(offset)
    groups = (await session.scalars(stmt)).all()
    if not groups:
        return []
    ids = [g.id for g in groups]
    counts = dict(
        (
            await session.execute(
                select(GroupMember.group_id, func.count())
                .where(GroupMember.group_id.in_(ids))
                .group_by(GroupMember.group_id)
            )
        ).all()
    )
    my_pending = set(
        (
            await session.scalars(
                select(GroupJoinRequest.group_id).where(
                    GroupJoinRequest.user_id == user.id,
                    GroupJoinRequest.group_id.in_(ids),
                    GroupJoinRequest.status == "pending",
                )
            )
        ).all()
    )
    return [
        {
            "id": g.id,
            "name": g.name,
            "description": g.description,
            "member_count": counts.get(g.id, 0),
            "request_status": "pending" if g.id in my_pending else "none",
        }
        for g in groups
    ]


@router.get("/groups/{gid}")
async def group_detail(
    gid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    group, _ = await get_group_for_member(session, gid, user)
    rows = (
        await session.execute(
            select(GroupMember, User)
            .join(User, User.id == GroupMember.user_id)
            .where(GroupMember.group_id == gid)
            .order_by(GroupMember.joined_at)
        )
    ).all()
    pending = (
        await _pending_request_count(session, gid) if group.owner_id == user.id else None
    )
    payload = serialize_group(group, member_count=len(rows), pending_request_count=pending)
    payload["members"] = [serialize_group_member(m, u) for m, u in rows]
    return payload


@router.post("/groups/join")
async def join_group(
    body: GroupJoinIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    code = body.invite_code.strip().upper()
    group = await session.scalar(select(Group).where(Group.invite_code == code))
    if group is None:
        raise HTTPException(status_code=404, detail="Unknown invite code")
    group_id = group.id
    member = await session.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group_id, GroupMember.user_id == user.id
        )
    )
    if member is None:
        session.add(GroupMember(group_id=group_id, user_id=user.id, role="member"))
        # Resolve any lingering pending request for this user+group so a later
        # re-request is never blocked by a ghost pending row (the partial-unique
        # index only frees the slot once the row is no longer pending). The user
        # got in via the code, so their own request is effectively approved.
        await session.execute(
            update(GroupJoinRequest)
            .where(
                GroupJoinRequest.group_id == group_id,
                GroupJoinRequest.user_id == user.id,
                GroupJoinRequest.status == "pending",
            )
            .values(status="approved", decided_at=utcnow(), decided_by=user.id)
        )
        try:
            await record(
                session,
                request.app.state.broker,
                group_id=group_id,
                user=user,
                type_="member_joined",
            )
            await session.commit()
        except IntegrityError:
            # Concurrent duplicate join: the other request won; treat as joined.
            await session.rollback()
            group = await session.get(Group, group_id)
            if group is None:
                raise HTTPException(status_code=404, detail="Unknown invite code") from None
    return serialize_group(group, member_count=await _member_count(session, group_id))


@router.post("/groups/{gid}/request")
async def request_to_join(
    gid: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Ask to join a PUBLIC group. A private or unknown group returns 404 (no
    leak); an existing membership or pending request returns 409."""
    group = await session.get(Group, gid)
    if group is None or group.visibility != "public":
        raise HTTPException(status_code=404, detail="Group not found")
    already_member = await session.scalar(
        select(GroupMember.id).where(
            GroupMember.group_id == gid, GroupMember.user_id == user.id
        )
    )
    if already_member is not None:
        raise HTTPException(status_code=409, detail="You are already a member of this group")
    already_pending = await session.scalar(
        select(GroupJoinRequest.id).where(
            GroupJoinRequest.group_id == gid,
            GroupJoinRequest.user_id == user.id,
            GroupJoinRequest.status == "pending",
        )
    )
    if already_pending is not None:
        raise HTTPException(
            status_code=409, detail="You already have a pending request to join this group"
        )
    req = GroupJoinRequest(group_id=gid, user_id=user.id, status="pending")
    session.add(req)
    try:
        # The precheck above races on Postgres READ COMMITTED; the partial-unique
        # index (one pending row per group+user) is the authoritative guard.
        await session.flush()
        await record(
            session,
            request.app.state.broker,
            group_id=gid,
            user=user,
            type_="join_requested",
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="You already have a pending request to join this group"
        ) from None
    return {
        "id": req.id,
        "group_id": gid,
        "user_id": user.id,
        "status": req.status,
        "created_at": iso_z(req.created_at),
    }


@router.get("/groups/{gid}/requests")
async def list_join_requests(
    gid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    group, _ = await get_group_for_member(session, gid, user)
    _require_owner(group, user, "view join requests")
    rows = (
        await session.execute(
            select(GroupJoinRequest, User)
            .join(User, User.id == GroupJoinRequest.user_id)
            .where(GroupJoinRequest.group_id == gid, GroupJoinRequest.status == "pending")
            .order_by(GroupJoinRequest.created_at)
        )
    ).all()
    return [serialize_join_request(req, u) for req, u in rows]


async def _load_request_for_group(
    session: AsyncSession, gid: int, req_id: int
) -> GroupJoinRequest:
    req = await session.get(GroupJoinRequest, req_id)
    if req is None or req.group_id != gid:
        raise HTTPException(status_code=404, detail="Request not found")
    return req


@router.post("/groups/{gid}/requests/{req_id}/approve")
async def approve_join_request(
    gid: int,
    req_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    group, _ = await get_group_for_member(session, gid, user)
    _require_owner(group, user, "approve join requests")
    actor_id = user.id
    req = await _load_request_for_group(session, gid, req_id)
    if req.status != "pending":
        raise HTTPException(status_code=409, detail="Request already decided")
    req_user_id = req.user_id
    member = await session.scalar(
        select(GroupMember).where(
            GroupMember.group_id == gid, GroupMember.user_id == req_user_id
        )
    )
    if member is None:
        session.add(GroupMember(group_id=gid, user_id=req_user_id, role="member"))
        joining_user = await session.get(User, req_user_id)
        try:
            # member_joined is attributed to the person who joined (as with the
            # invite-code path), not to the approving owner. record() flushes,
            # so a duplicate-membership race surfaces here as IntegrityError.
            await record(
                session,
                request.app.state.broker,
                group_id=gid,
                user=joining_user,
                type_="member_joined",
            )
        except IntegrityError:
            # A concurrent join won the race; drop our duplicate insert and
            # reload the request (locals, not expired ORM attrs, are used below).
            await session.rollback()
            req = await _load_request_for_group(session, gid, req_id)
    req.status = "approved"
    req.decided_at = utcnow()
    req.decided_by = actor_id
    await session.commit()
    return {"ok": True, "status": "approved"}


@router.post("/groups/{gid}/requests/{req_id}/reject")
async def reject_join_request(
    gid: int,
    req_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    group, _ = await get_group_for_member(session, gid, user)
    _require_owner(group, user, "reject join requests")
    req = await _load_request_for_group(session, gid, req_id)
    if req.status != "pending":
        raise HTTPException(status_code=409, detail="Request already decided")
    req.status = "rejected"
    req.decided_at = utcnow()
    req.decided_by = user.id
    await session.commit()
    return {"ok": True, "status": "rejected"}


@router.delete("/groups/{gid}/members/{user_id}")
async def remove_member(
    gid: int,
    user_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    group, _ = await get_group_for_member(session, gid, user)
    _require_owner(group, user, "remove members")
    if user_id == user.id:
        raise HTTPException(
            status_code=400, detail="You cannot remove yourself; use leave instead"
        )
    if user_id == group.owner_id:
        raise HTTPException(status_code=400, detail="The group owner cannot be removed")
    member = await session.scalar(
        select(GroupMember).where(
            GroupMember.group_id == gid, GroupMember.user_id == user_id
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    removed_user = await session.get(User, user_id)
    removed_user_name = removed_user.display_name if removed_user is not None else None
    # The removed member's personal pipeline goes with them, exactly like leave;
    # their comments and activity (conversation history) stay.
    await session.execute(
        delete(Application).where(
            Application.user_id == user_id,
            Application.company_id.in_(select(Company.id).where(Company.group_id == gid)),
        )
    )
    await session.execute(
        delete(PortalStatus).where(
            PortalStatus.user_id == user_id,
            PortalStatus.portal_id.in_(select(Portal.id).where(Portal.group_id == gid)),
        )
    )
    # Drop every join request (pending or decided) for this user+group so no
    # stale pending row blocks them from requesting again after removal.
    await session.execute(
        delete(GroupJoinRequest).where(
            GroupJoinRequest.group_id == gid, GroupJoinRequest.user_id == user_id
        )
    )
    await session.delete(member)
    await record(
        session,
        request.app.state.broker,
        group_id=gid,
        user=user,
        type_="member_removed",
        detail={"removed_user_id": user_id, "removed_user_name": removed_user_name},
    )
    await session.commit()
    return {"ok": True}


@router.post("/groups/{gid}/leave")
async def leave_group(
    gid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _, member = await get_group_for_member(session, gid, user)
    others = int(
        await session.scalar(
            select(func.count())
            .select_from(GroupMember)
            .where(GroupMember.group_id == gid, GroupMember.user_id != user.id)
        )
        or 0
    )
    if others == 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "You are the last member. Leaving would abandon the group, "
                "and group deletion is not supported yet."
            ),
        )
    if member.role == "owner":
        raise HTTPException(
            status_code=400, detail="Owner cannot leave while other members remain"
        )
    # The leaver's personal pipeline goes with them; shared data, their
    # comments and their activity rows stay (conversation history).
    await session.execute(
        delete(Application).where(
            Application.user_id == user.id,
            Application.company_id.in_(select(Company.id).where(Company.group_id == gid)),
        )
    )
    await session.execute(
        delete(PortalStatus).where(
            PortalStatus.user_id == user.id,
            PortalStatus.portal_id.in_(select(Portal.id).where(Portal.group_id == gid)),
        )
    )
    await session.delete(member)
    await session.commit()
    return {"ok": True}


@router.patch("/groups/{gid}")
async def update_group(
    gid: int,
    body: GroupPatchIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    group, _ = await get_group_for_member(session, gid, user)
    _require_owner(group, user, "update the group")
    data = body.model_dump(exclude_unset=True)
    if data.get("name") is not None:
        group.name = data["name"]
    if data.get("visibility") is not None:
        group.visibility = data["visibility"]
    if "description" in data:
        group.description = data["description"]
    await session.commit()
    return serialize_group(
        group,
        member_count=await _member_count(session, gid),
        pending_request_count=await _pending_request_count(session, gid),
    )


@router.post("/groups/{gid}/regenerate-invite")
async def regenerate_invite(
    gid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    group, _ = await get_group_for_member(session, gid, user)
    _require_owner(group, user, "regenerate the invite code")
    group.invite_code = await _generate_invite_code(session)
    await session.commit()
    return serialize_group(
        group,
        member_count=await _member_count(session, gid),
        pending_request_count=await _pending_request_count(session, gid),
    )
