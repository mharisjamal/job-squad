"""Group endpoints: create, list, detail, join by code, leave, rename."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..activity import record
from ..deps import get_current_user, get_group_for_member, get_session
from ..models import Group, GroupMember, User
from ..schemas import (
    GroupCreateIn,
    GroupJoinIn,
    GroupRenameIn,
    serialize_group,
    serialize_group_member,
)

router = APIRouter(tags=["groups"])

# Unambiguous subset of A-Z0-9 (no O/0, I/1/L) for invite codes.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


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
    )
    session.add(group)
    await session.flush()
    session.add(GroupMember(group_id=group.id, user_id=user.id, role="owner"))
    await session.commit()
    return serialize_group(group, member_count=1)


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
    counts = dict(
        (
            await session.execute(
                select(GroupMember.group_id, func.count())
                .where(GroupMember.group_id.in_([g.id for g in groups]))
                .group_by(GroupMember.group_id)
            )
        ).all()
    )
    return [serialize_group(g, counts.get(g.id, 0)) for g in groups]


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
    payload = serialize_group(group, member_count=len(rows))
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
    member = await session.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group.id, GroupMember.user_id == user.id
        )
    )
    if member is None:
        session.add(GroupMember(group_id=group.id, user_id=user.id, role="member"))
        await record(
            session,
            request.app.state.broker,
            group_id=group.id,
            user=user,
            type_="member_joined",
        )
        await session.commit()
    return serialize_group(group, member_count=await _member_count(session, group.id))


@router.post("/groups/{gid}/leave")
async def leave_group(
    gid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    group, member = await get_group_for_member(session, gid, user)
    others = await session.scalar(
        select(func.count())
        .select_from(GroupMember)
        .where(GroupMember.group_id == gid, GroupMember.user_id != user.id)
    )
    if member.role == "owner" and int(others or 0) > 0:
        raise HTTPException(
            status_code=400, detail="Owner cannot leave while other members remain"
        )
    if int(others or 0) == 0:
        # Last member left: remove the group and its data (FK cascades the membership).
        await session.delete(group)
    else:
        await session.delete(member)
    await session.commit()
    return {"ok": True}


@router.patch("/groups/{gid}")
async def rename_group(
    gid: int,
    body: GroupRenameIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    group, _ = await get_group_for_member(session, gid, user)
    if group.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the group owner can rename the group")
    group.name = body.name
    await session.commit()
    return serialize_group(group, member_count=await _member_count(session, gid))
