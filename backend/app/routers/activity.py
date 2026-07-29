"""Activity endpoints: paged feed + per-group SSE stream."""

import json

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from ..deps import get_current_user, get_session, require_member
from ..models import Activity, Company, GroupMember, Portal, User
from ..schemas import serialize_activity

router = APIRouter(tags=["activity"])


@router.get("/groups/{gid}/activity")
async def list_activity(
    gid: int,
    limit: int = Query(default=50, ge=1, le=200),
    before_id: int | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    await require_member(session, gid, user)
    query = (
        select(Activity, User, Company, Portal)
        .join(User, User.id == Activity.user_id)
        .outerjoin(Company, Company.id == Activity.company_id)
        .outerjoin(Portal, Portal.id == Activity.portal_id)
        .where(Activity.group_id == gid)
    )
    if before_id is not None:
        query = query.where(Activity.id < before_id)
    rows = (await session.execute(query.order_by(Activity.id.desc()).limit(limit))).all()
    return [
        serialize_activity(
            a,
            u.username,
            u.display_name,
            c.name if c is not None else None,
            p.name if p is not None else None,
        )
        for a, u, c, p in rows
    ]


@router.get("/groups/{gid}/activity/sse")
async def activity_sse(
    gid: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EventSourceResponse:
    await require_member(session, gid, user)
    # Release the DB connection before holding the stream open.
    await session.close()
    broker = request.app.state.broker
    sessionmaker = request.app.state.sessionmaker
    user_id = user.id

    async def _still_member() -> bool:
        async with sessionmaker() as check_session:
            member = await check_session.scalar(
                select(GroupMember).where(
                    GroupMember.group_id == gid, GroupMember.user_id == user_id
                )
            )
        return member is not None

    async def event_stream():
        queue = broker.subscribe(gid)
        try:
            # sse-starlette adds the SSE framing; yield event dicts only.
            yield {"event": "hello", "data": json.dumps({"group_id": gid})}
            while True:
                payload = await queue.get()
                if payload is None:
                    # Dropped by the broker (subscriber fell too far behind).
                    break
                # An ex-member's open stream must stop receiving group events.
                if not await _still_member():
                    break
                yield {"event": "activity", "data": json.dumps(payload)}
        finally:
            broker.unsubscribe(gid, queue)

    return EventSourceResponse(event_stream(), ping=15)
