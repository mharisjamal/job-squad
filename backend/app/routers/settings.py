"""User AI settings (BYOK): read the config, save it, and test it.

The API key is stored encrypted at rest (Fernet, key derived from the app
secret) and is NEVER returned to the client or logged: reads report only
`key_set`. Provider presets fill the OpenAI-compatible base URL and default
model; the model stays user-editable.
"""

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import ai
from ..deps import get_current_user, get_session
from ..models import User, UserAISettings
from ..schemas import AISettingsPutIn
from ..security import decrypt_secret, encrypt_secret

router = APIRouter(tags=["settings"])

# ---------------------------------------------------------------------------
# base_url is a CREDENTIAL DESTINATION, not a cosmetic setting: the stored key
# is sent to it as "Authorization: Bearer <key>". Two rules follow.
#
# 1. https only, except loopback. A key must never travel in plaintext to a
#    remote host; a local model server on http://localhost stays usable.
# 2. Repointing the URL requires re-entering the key. Otherwise anyone holding
#    a token could point the victim's saved key at their own server and press
#    "Test" to receive it (a blank key deliberately keeps the stored one). This
#    is also the honest UX: a Gemini key is useless against Groq, so a genuine
#    provider switch always comes with that provider's key.
# ---------------------------------------------------------------------------

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

BASE_URL_KEY_REQUIRED = "Re-enter your API key when you change the provider or base URL."


def base_url_problem(base_url: str | None) -> str | None:
    """A user-facing reason this base URL may not be saved, or None when it is
    fine. An empty URL is not a problem here: nothing is ever sent to it (the
    client refuses to call without one)."""
    if not base_url or not base_url.strip():
        return None
    parts = urlsplit(base_url.strip())
    if parts.scheme not in ("https", "http"):
        return "The base URL must start with https://."
    host = (parts.hostname or "").lower()
    if not host:
        return "The base URL must include a host, for example https://api.groq.com/openai/v1."
    if parts.scheme == "http" and host not in _LOOPBACK_HOSTS:
        return "The base URL must use https:// (http:// is allowed only for localhost)."
    return None


def _same_endpoint(left: str | None, right: str | None) -> bool:
    """Compare two base URLs the way the client uses them (trailing / ignored)."""
    return (left or "").strip().rstrip("/") == (right or "").strip().rstrip("/")

# OpenAI-compatible presets. `custom` supplies its own base_url + model.
AI_PRESETS: dict[str, dict[str, str]] = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        # gemini-2.5-flash was blocked for new API keys by Google (404 "no longer
        # available to new users"), so the default is the current free-tier flash.
        # The model field stays user-editable for when Google rotates it again.
        "model": "gemini-2.0-flash",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    },
    "custom": {},
}


def _serialize(settings: UserAISettings | None) -> dict:
    """Public shape: provider/base_url/model plus key_set, never the key."""
    if settings is None:
        return {"provider": None, "base_url": None, "model": None, "key_set": False}
    return {
        "provider": settings.provider,
        "base_url": settings.base_url,
        "model": settings.model,
        "key_set": bool(settings.key_encrypted),
    }


@router.get("/settings/ai")
async def get_ai_settings(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    settings = await session.get(UserAISettings, user.id)
    return _serialize(settings)


@router.put("/settings/ai")
async def put_ai_settings(
    body: AISettingsPutIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    settings = await session.get(UserAISettings, user.id)
    preset = AI_PRESETS.get(body.provider, {})

    # Resolution order for base_url/model: an explicit body value wins; else a
    # preset value (only for gemini/groq); else the previously stored value.
    def _resolve(field: str, provided: str | None) -> str | None:
        provided = (provided or "").strip()
        if provided:
            return provided
        if preset.get(field):
            return preset[field]
        return getattr(settings, field) if settings is not None else None

    base_url = _resolve("base_url", body.base_url)
    model = _resolve("model", body.model)

    problem = base_url_problem(base_url)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    supplied_key = bool(body.key and body.key.strip())
    # Only a STORED key can be redirected, so that is exactly when the re-entry
    # is demanded; a first-time save has no secret to protect.
    if (
        settings is not None
        and settings.key_encrypted
        and not supplied_key
        and not _same_endpoint(base_url, settings.base_url)
    ):
        raise HTTPException(status_code=422, detail=BASE_URL_KEY_REQUIRED)

    if settings is None:
        settings = UserAISettings(user_id=user.id)
        session.add(settings)
    settings.provider = body.provider
    settings.base_url = base_url
    settings.model = model
    # A blank/omitted key keeps the stored ciphertext untouched.
    if body.key is not None and body.key.strip():
        settings.key_encrypted = encrypt_secret(
            body.key.strip(), request.app.state.settings.secret
        )
    await session.commit()
    return _serialize(settings)


@router.post("/settings/ai/test")
async def test_ai_settings(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    settings = await session.get(UserAISettings, user.id)
    if settings is None or not settings.key_encrypted:
        return {"ok": False, "error": "Configure your AI provider and key first."}
    api_key = decrypt_secret(settings.key_encrypted, request.app.state.settings.secret)
    if not api_key:
        return {"ok": False, "error": "Stored API key could not be read. Re-enter it."}
    try:
        await ai.chat_completion(
            base_url=settings.base_url or "",
            api_key=api_key,
            model=settings.model or "",
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            temperature=0.0,
        )
    except ai.AIError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:  # noqa: BLE001 - the test button must never 500
        return {"ok": False, "error": "The AI test failed unexpectedly."}
    return {"ok": True}
