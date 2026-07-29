"""Auth endpoints: register, login (throttled, off-thread hashing), me."""

import time

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_current_user, get_session
from ..models import User
from ..schemas import LoginIn, RegisterIn, serialize_user
from ..security import hash_password, make_token, verify_password

router = APIRouter(tags=["auth"])

# In-process login throttle: (username, client_ip) -> monotonic failure times.
_FAILED_LOGINS: dict[tuple[str, str], list[float]] = {}
THROTTLE_WINDOW_SECONDS = 300.0
THROTTLE_MAX_FAILURES = 10


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _prune_failures(now: float) -> None:
    cutoff = now - THROTTLE_WINDOW_SECONDS
    for key in [k for k, times in _FAILED_LOGINS.items() if not times or times[-1] < cutoff]:
        _FAILED_LOGINS.pop(key, None)


def _is_throttled(key: tuple[str, str], now: float) -> bool:
    times = _FAILED_LOGINS.get(key)
    if times is None:
        return False
    cutoff = now - THROTTLE_WINDOW_SECONDS
    recent = [t for t in times if t >= cutoff]
    if recent:
        _FAILED_LOGINS[key] = recent
    else:
        _FAILED_LOGINS.pop(key, None)
    return len(recent) >= THROTTLE_MAX_FAILURES


def _token_for(request: Request, user: User) -> str:
    settings = request.app.state.settings
    return make_token(user.id, settings.secret, settings.token_ttl_hours)


@router.post("/auth/register")
async def register(
    body: RegisterIn, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    existing = await session.scalar(select(User).where(User.username == body.username))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already taken")
    password_hash = await anyio.to_thread.run_sync(hash_password, body.password)
    user = User(
        username=body.username,
        display_name=body.display_name,
        password_hash=password_hash,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Username already taken") from None
    return {"token": _token_for(request, user), "user": serialize_user(user)}


@router.post("/auth/login")
async def login(
    body: LoginIn, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    username = body.username.strip().lower()
    key = (username, _client_ip(request))
    now = time.monotonic()
    _prune_failures(now)
    if _is_throttled(key, now):
        raise HTTPException(
            status_code=429, detail="Too many attempts. Try again in a few minutes."
        )
    user = await session.scalar(select(User).where(User.username == username))
    valid = False
    if user is not None:
        # 250k-iteration PBKDF2 is CPU-bound; keep it off the event loop.
        valid = await anyio.to_thread.run_sync(
            verify_password, body.password, user.password_hash
        )
    if user is None or not valid:
        _FAILED_LOGINS.setdefault(key, []).append(time.monotonic())
        raise HTTPException(status_code=401, detail="Invalid username or password")
    _FAILED_LOGINS.pop(key, None)
    return {"token": _token_for(request, user), "user": serialize_user(user)}


@router.get("/auth/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    return serialize_user(user)
