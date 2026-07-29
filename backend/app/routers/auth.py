"""Auth endpoints: register, login, me."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_current_user, get_session
from ..models import User
from ..schemas import LoginIn, RegisterIn, serialize_user
from ..security import hash_password, make_token, verify_password

router = APIRouter(tags=["auth"])


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
    user = User(
        username=body.username,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
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
    user = await session.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"token": _token_for(request, user), "user": serialize_user(user)}


@router.get("/auth/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    return serialize_user(user)
