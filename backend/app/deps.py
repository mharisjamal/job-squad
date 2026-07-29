"""Shared dependencies: DB session, current user, group membership guards.

Scoping rule (frozen contract): a resource that does not exist OR lives in a
group the caller is not a member of returns 404, so existence never leaks.
403 is reserved for known-but-forbidden actions.
"""

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Company, Group, GroupMember, Portal, User
from .security import jwt_decode


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def _query_token_allowed(path: str) -> bool:
    """?access_token= is honored only where headers are impossible:
    SSE (EventSource) and CSV downloads (<a href>)."""
    return path.endswith("/sse") or "/export/" in path


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    if _query_token_allowed(request.url.path):
        token = request.query_params.get("access_token")
        return token or None
    return None


async def get_current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = jwt_decode(token, request.app.state.settings.secret)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


async def require_member(session: AsyncSession, group_id: int, user: User) -> GroupMember:
    member = await session.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group_id, GroupMember.user_id == user.id
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return member


async def get_group_for_member(
    session: AsyncSession, group_id: int, user: User
) -> tuple[Group, GroupMember]:
    group = await session.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    member = await require_member(session, group_id, user)
    return group, member


async def get_company_for_member(
    session: AsyncSession, company_id: int, user: User
) -> Company:
    company = await session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    member = await session.scalar(
        select(GroupMember).where(
            GroupMember.group_id == company.group_id, GroupMember.user_id == user.id
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


async def get_portal_for_member(
    session: AsyncSession, portal_id: int, user: User
) -> Portal:
    portal = await session.get(Portal, portal_id)
    if portal is None:
        raise HTTPException(status_code=404, detail="Portal not found")
    member = await session.scalar(
        select(GroupMember).where(
            GroupMember.group_id == portal.group_id, GroupMember.user_id == user.id
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Portal not found")
    return portal
