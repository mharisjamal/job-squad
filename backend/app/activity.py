"""Activity recording + in-process SSE broadcasting (single-process app)."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Activity, Company, Portal, User
from .schemas import serialize_activity

SUBSCRIBER_QUEUE_MAXSIZE = 500


class ActivityBroker:
    """Per-group fanout of activity payloads to SSE subscriber queues.

    Queues are bounded; a subscriber that falls SUBSCRIBER_QUEUE_MAXSIZE
    events behind is dropped: its backlog is discarded and a None sentinel
    is enqueued so its stream generator terminates instead of idling.
    """

    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue]] = {}

    def subscribe(self, group_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAXSIZE)
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
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                self._drop_subscriber(group_id, queue)

    def _drop_subscriber(self, group_id: int, queue: asyncio.Queue) -> None:
        self.unsubscribe(group_id, queue)
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        queue.put_nowait(None)


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
