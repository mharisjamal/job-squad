"""Shared dependencies: DB session, current user, group membership guards.

Scoping rule (frozen contract): a resource that does not exist OR lives in a
group the caller is not a member of returns 404, so existence never leaks.
403 is reserved for known-but-forbidden actions.
"""

from collections.abc import AsyncIterator
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Company, ExtensionToken, Group, GroupMember, Portal, User, utcnow
from .security import EXTENSION_TOKEN_TYPE, jwt_decode

# An extension calls the API constantly; recording every call would turn each
# read into a write. One bump per hour is enough for a "last used" column.
EXTENSION_TOUCH_INTERVAL = timedelta(hours=1)

# An extension token sits on a browser profile for a year, which makes it the
# most stealable credential the product issues. It is therefore scoped to
# exactly what capture needs: list my groups, look companies up (one, or one
# board page's worth), save a posting. It can NOT read a company, edit a group,
# regenerate an invite code, touch AI settings or resumes, or mint another
# token, so a stolen one cannot be walked up into an account takeover.
EXTENSION_ALLOWED_ROUTES = frozenset(
    {
        ("GET", "/api/groups"),
        ("POST", "/api/capture"),
        ("GET", "/api/capture/lookup"),
        ("POST", "/api/capture/lookup"),
        # Phase E2: the on-page squad badges. Reads no more than the single
        # lookup already does, in one call instead of one per row.
        ("POST", "/api/capture/lookup/batch"),
    }
)


def extension_route_allowed(method: str, path: str) -> bool:
    """Exact method+path match, tolerating an optional trailing slash."""
    return (method.upper(), path.rstrip("/") or "/") in EXTENSION_ALLOWED_ROUTES


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


async def _authorize_extension_token(
    session: AsyncSession, payload: dict, user: User
) -> None:
    """An extension token is only good while its row exists and is not revoked.

    Revocation therefore takes effect on the very next request, even though the
    JWT itself stays signature-valid for its whole 365-day life.
    """
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    row = await session.scalar(select(ExtensionToken).where(ExtensionToken.jti == jti))
    if row is None or row.revoked or row.user_id != user.id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    now = utcnow()
    if row.last_used_at is None or now - row.last_used_at >= EXTENSION_TOUCH_INTERVAL:
        row.last_used_at = now
        await session.commit()


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
    # Session tokens carry no "typ" claim and behave exactly as before. Any
    # value other than the one kind we mint is refused rather than guessed at.
    kind = payload.get("typ")
    if kind is not None and kind != EXTENSION_TOKEN_TYPE:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if kind == EXTENSION_TOKEN_TYPE:
        await _authorize_extension_token(session, payload, user)
        if not extension_route_allowed(request.method, request.url.path):
            raise HTTPException(
                status_code=401, detail="This token cannot be used on this endpoint"
            )
    # Routes that must refuse extension tokens read this flag (see
    # require_session_user); anything else treats both kinds alike.
    request.state.extension_token = kind == EXTENSION_TOKEN_TYPE
    return user


def is_extension_request(request: Request) -> bool:
    """True when the authenticated caller presented an extension token."""
    return bool(getattr(request.state, "extension_token", False))


async def require_session_user(
    request: Request, user: User = Depends(get_current_user)
) -> User:
    """Lateral-movement guard: a stolen extension token cannot mint or manage
    extension tokens, so it is refused on those routes even though it is a
    valid credential everywhere else."""
    if is_extension_request(request):
        raise HTTPException(
            status_code=401, detail="Sign in to the app to manage extension tokens"
        )
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


def group_lock_statement(group_id: int):
    """SELECT ... FOR UPDATE for one group row.

    Ownership lives in three places that must move together (groups.owner_id
    plus two group_members.role rows) and no DB constraint can express that,
    so every writer of ownership or membership serializes on this row lock.
    SQLAlchemy's SQLite dialect omits FOR UPDATE, so local/CI is unchanged.
    """
    return (
        select(Group)
        .where(Group.id == group_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def get_group_for_member(
    session: AsyncSession, group_id: int, user: User, *, for_update: bool = False
) -> tuple[Group, GroupMember]:
    """Load a group the caller belongs to (404 otherwise, so nothing leaks).

    `for_update=True` locks the group row first, so a handler that changes who
    owns the group or who belongs to it tests its guards against state that no
    concurrent writer can invalidate before it commits.
    """
    if for_update:
        group = await session.scalar(group_lock_statement(group_id))
    else:
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
