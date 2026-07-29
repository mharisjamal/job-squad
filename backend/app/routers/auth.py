"""Auth endpoints: config, register (open or email-OTP), login, me."""

import logging
import time
from datetime import timedelta
from urllib.parse import quote, urlencode

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_current_user, get_session
from ..identity import derive_username
from ..mailer import MailError, send_otp_email
from ..models import PendingRegistration, User, UserIdentity, utcnow
from ..oauth import (
    PROVIDERS,
    OAuthError,
    SocialProfile,
    authorize_params,
    exchange_code,
    fetch_profile,
)
from ..schemas import (
    LoginIn,
    RegisterIn,
    RegisterStartIn,
    RegisterVerifyIn,
    serialize_user,
)
from ..security import (
    generate_otp,
    hash_otp,
    hash_password,
    make_pkce_verifier,
    make_state_token,
    make_token,
    pkce_challenge,
    read_state_token,
    verify_otp,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

OTP_TTL_MINUTES = 10
OTP_RESEND_COOLDOWN_SECONDS = 60
OTP_MAX_ATTEMPTS = 5
OTP_STARTS_PER_IP_PER_HOUR = 10
_OTP_START_WINDOW_SECONDS = 3600.0

# In-process signup-start throttle: client_ip -> monotonic start times.
_OTP_STARTS: dict[str, list[float]] = {}

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


def _otp_start_throttled(ip: str, now: float) -> bool:
    cutoff = now - _OTP_START_WINDOW_SECONDS
    for key in [k for k, times in _OTP_STARTS.items() if not times or times[-1] < cutoff]:
        _OTP_STARTS.pop(key, None)
    recent = [t for t in _OTP_STARTS.get(ip, []) if t >= cutoff]
    if recent:
        _OTP_STARTS[ip] = recent
    else:
        _OTP_STARTS.pop(ip, None)
    return len(recent) >= OTP_STARTS_PER_IP_PER_HOUR


@router.get("/auth/config")
async def auth_config(request: Request) -> dict:
    """Public: lets the frontend pick the signup flow and social buttons."""
    settings = request.app.state.settings
    return {
        "otp_required": settings.otp_required,
        "providers": settings.enabled_providers,
    }


@router.post("/auth/register")
async def register(
    body: RegisterIn, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    if request.app.state.settings.otp_required:
        raise HTTPException(
            status_code=403, detail="Email verification is required on this server."
        )
    if await session.scalar(select(User.id).where(User.email == body.email)):
        raise HTTPException(
            status_code=409, detail="An account already exists for that email."
        )
    password_hash = await anyio.to_thread.run_sync(hash_password, body.password)
    user = User(
        username=await derive_username(session, body.email, body.display_name),
        display_name=body.display_name,
        password_hash=password_hash,
        email=body.email,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="An account already exists for that email."
        ) from None
    return {"token": _token_for(request, user), "user": serialize_user(user)}


@router.post("/auth/register/start")
async def register_start(
    body: RegisterStartIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    settings = request.app.state.settings
    if not settings.otp_required:
        # The route is effectively off on a LAN deployment.
        raise HTTPException(status_code=404, detail="Not found")

    now_monotonic = time.monotonic()
    ip = _client_ip(request)
    if _otp_start_throttled(ip, now_monotonic):
        raise HTTPException(
            status_code=429, detail="Too many signup attempts. Try again later."
        )

    now = utcnow()
    # Opportunistic cleanup so abandoned signups do not accumulate.
    await session.execute(
        delete(PendingRegistration).where(PendingRegistration.expires_at < now)
    )

    if await session.scalar(select(User.id).where(User.email == body.email)):
        raise HTTPException(
            status_code=409, detail="An account already exists for that email."
        )

    pending = await session.scalar(
        select(PendingRegistration).where(PendingRegistration.email == body.email)
    )
    if pending is not None:
        elapsed = (now - pending.last_sent_at).total_seconds()
        if elapsed < OTP_RESEND_COOLDOWN_SECONDS:
            raise HTTPException(
                status_code=429, detail="Wait a minute before requesting another code."
            )

    code = generate_otp()
    password_hash = await anyio.to_thread.run_sync(hash_password, body.password)
    otp_hash = hash_otp(code, body.email, settings.secret)
    expires_at = now + timedelta(minutes=OTP_TTL_MINUTES)

    if pending is None:
        pending = PendingRegistration(email=body.email)
        session.add(pending)
    # A repeat start for the same email replaces the details and the code.
    pending.display_name = body.display_name
    pending.password_hash = password_hash
    pending.otp_hash = otp_hash
    pending.attempts = 0
    pending.expires_at = expires_at
    pending.last_sent_at = now

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="An account already exists for that email."
        ) from None

    try:
        await anyio.to_thread.run_sync(
            send_otp_email, settings, body.email, code, body.display_name
        )
    except MailError as exc:
        logger.error("Verification email to %s failed: %s", body.email, exc)
        raise HTTPException(
            status_code=502,
            detail="Could not send the verification email. Check the server mail settings.",
        ) from None

    _OTP_STARTS.setdefault(ip, []).append(time.monotonic())
    return {"ok": True, "resend_after_seconds": OTP_RESEND_COOLDOWN_SECONDS}


@router.post("/auth/register/verify")
async def register_verify(
    body: RegisterVerifyIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    settings = request.app.state.settings
    if not settings.otp_required:
        raise HTTPException(status_code=404, detail="Not found")

    pending = await session.scalar(
        select(PendingRegistration).where(PendingRegistration.email == body.email)
    )
    if pending is None:
        raise HTTPException(
            status_code=404, detail="No pending signup for that email. Start again."
        )
    if pending.expires_at < utcnow():
        await session.delete(pending)
        await session.commit()
        raise HTTPException(
            status_code=410, detail="That code expired. Request a new one."
        )

    if not verify_otp(body.code, body.email, settings.secret, pending.otp_hash):
        pending.attempts += 1
        if pending.attempts >= OTP_MAX_ATTEMPTS:
            await session.delete(pending)
            await session.commit()
            raise HTTPException(
                status_code=429, detail="Too many wrong codes. Start the signup again."
            )
        await session.commit()
        raise HTTPException(status_code=401, detail="That code is not right.")

    user = User(
        username=await derive_username(session, pending.email, pending.display_name),
        display_name=pending.display_name,
        password_hash=pending.password_hash,
        email=pending.email,
    )
    session.add(user)
    await session.delete(pending)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="That email was just registered."
        ) from None
    return {"token": _token_for(request, user), "user": serialize_user(user)}


@router.post("/auth/login")
async def login(
    body: LoginIn, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    identifier = body.login_key
    key = (identifier, _client_ip(request))
    now = time.monotonic()
    _prune_failures(now)
    if _is_throttled(key, now):
        raise HTTPException(
            status_code=429, detail="Too many attempts. Try again in a few minutes."
        )
    # The identifier is an email or the derived username.
    user = await session.scalar(
        select(User).where((User.email == identifier) | (User.username == identifier))
    )
    if user is not None and user.password_hash is None:
        raise HTTPException(
            status_code=401,
            detail="That account signs in with Google, GitHub, or LinkedIn.",
        )
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


# ---------------------------------------------------------------------------
# Social sign-in
# ---------------------------------------------------------------------------


def _provider_or_404(request: Request, provider: str):
    config = PROVIDERS.get(provider)
    settings = request.app.state.settings
    if config is None or settings.provider_credentials(provider) is None:
        raise HTTPException(status_code=404, detail="Unknown or unconfigured provider")
    return config, settings


def _redirect_to_spa(settings, fragment: str) -> RedirectResponse:
    """The token rides the URL fragment so it never reaches a server log."""
    return RedirectResponse(
        url=f"{settings.public_url.rstrip('/')}/auth/callback#{fragment}", status_code=302
    )


@router.get("/auth/oauth/{provider}/start")
async def oauth_start(provider: str, request: Request, next: str | None = None):
    config, settings = _provider_or_404(request, provider)
    verifier = make_pkce_verifier()
    state_payload: dict = {"provider": provider}
    if config.supports_pkce:
        state_payload["v"] = verifier
    if next and next.startswith("/"):
        state_payload["next"] = next
    state = make_state_token(state_payload, settings.secret)
    params = authorize_params(
        settings, config, state, pkce_challenge(verifier) if config.supports_pkce else None
    )
    return RedirectResponse(
        url=f"{config.authorize_url}?{urlencode(params)}", status_code=302
    )


@router.get("/auth/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    config, settings = _provider_or_404(request, provider)
    if error or not code or not state:
        return _redirect_to_spa(settings, "error=access_denied")

    claims = read_state_token(state, settings.secret)
    if not claims or claims.get("provider") != provider:
        # Tampered, replayed from another provider, or older than the TTL.
        return _redirect_to_spa(settings, "error=invalid_state")

    try:
        access_token = await exchange_code(settings, config, code, claims.get("v"))
        profile = await fetch_profile(settings, config, access_token)
    except OAuthError as exc:
        logger.error("OAuth %s handshake failed: %s", provider, exc)
        return _redirect_to_spa(settings, "error=provider_error")

    if not profile.provider_user_id:
        return _redirect_to_spa(settings, "error=provider_error")

    try:
        user = await _resolve_social_user(session, profile)
    except _EmailUnverified:
        return _redirect_to_spa(settings, "error=email_unverified")
    except IntegrityError:
        await session.rollback()
        return _redirect_to_spa(settings, "error=account_conflict")

    token = _token_for(request, user)
    fragment = f"token={quote(token, safe='')}"
    next_path = claims.get("next")
    if isinstance(next_path, str) and next_path.startswith("/"):
        fragment += f"&next={quote(next_path, safe='/')}"
    return _redirect_to_spa(settings, fragment)


class _EmailUnverified(Exception):
    """The provider did not vouch for the email, so linking is unsafe."""


async def _resolve_social_user(session: AsyncSession, profile: SocialProfile) -> User:
    """Takeover-safe account resolution for a social profile."""
    # 1) Known identity: just log in.
    identity = await session.scalar(
        select(UserIdentity).where(
            UserIdentity.provider == profile.provider,
            UserIdentity.provider_user_id == profile.provider_user_id,
        )
    )
    if identity is not None:
        user = await session.get(User, identity.user_id)
        if user is not None:
            return user

    email = (profile.email or "").strip().lower() or None
    existing = None
    if email:
        existing = await session.scalar(select(User).where(User.email == email))

    # 2) Verified email matching an existing account: link it.
    if existing is not None:
        if not profile.email_verified:
            # 3) Unverified email must never take over an existing account.
            raise _EmailUnverified()
        session.add(
            UserIdentity(
                user_id=existing.id,
                provider=profile.provider,
                provider_user_id=profile.provider_user_id,
                email=email,
            )
        )
        if not existing.avatar_url and profile.avatar_url:
            existing.avatar_url = profile.avatar_url
        await session.commit()
        return existing

    # 3) No account to link, and the provider does not vouch for the address.
    if email and not profile.email_verified:
        raise _EmailUnverified()

    # 4) Brand new account: no password, provider display name and avatar.
    display_name = profile.display_name or (email.split("@")[0] if email else "New user")
    user = User(
        username=await derive_username(session, email, display_name),
        display_name=display_name,
        password_hash=None,
        email=email,
        avatar_url=profile.avatar_url,
    )
    session.add(user)
    await session.flush()
    session.add(
        UserIdentity(
            user_id=user.id,
            provider=profile.provider,
            provider_user_id=profile.provider_user_id,
            email=email,
        )
    )
    await session.commit()
    return user
