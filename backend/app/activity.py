"""Activity recording + in-process SSE broadcasting (single-process app)."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Activity, Company, Portal, User
from .schemas import serialize_activity


class ActivityBroker:
    """Per-group fanout of activity payloads to SSE subscriber queues."""

    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue]] = {}

    def subscribe(self, group_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(group_id, set()).add(queue)
        return queue

    def unsubscribe(self, group_id: int, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(group_id)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(group_id, None)

    def publish(self, group_id: int, payload: dict) -> None:
        for queue in tuple(self._subscribers.get(group_id, ())):
            queue.put_nowait(payload)


async def record(
    session: AsyncSession,
    broker: ActivityBroker,
    *,
    group_id: int,
    user: User,
    type_: str,
    company: Company | None = None,
    portal: Portal | None = None,
    detail: dict | None = None,
) -> dict:
    """Insert an activity row and publish its wire payload to group subscribers.

    The caller commits right after; the row is flushed here so id/created_at exist.
    """
    row = Activity(
        group_id=group_id,
        user_id=user.id,
        type=type_,
        company_id=company.id if company is not None else None,
        portal_id=portal.id if portal is not None else None,
        detail=detail if detail is not None else {},
    )
    session.add(row)
    await session.flush()
    payload = serialize_activity(
        row,
        user.username,
        user.display_name,
        company.name if company is not None else None,
        portal.name if portal is not None else None,
    )
    broker.publish(group_id, payload)
    return payload
