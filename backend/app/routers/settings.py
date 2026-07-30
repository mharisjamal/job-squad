"""User AI settings (BYOK): read the config, save it, and test it.

The API key is stored encrypted at rest (Fernet, key derived from the app
secret) and is NEVER returned to the client or logged: reads report only
`key_set`. Provider presets fill the OpenAI-compatible base URL and default
model; the model stays user-editable.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import ai
from ..deps import get_current_user, get_session
from ..models import User, UserAISettings
from ..schemas import AISettingsPutIn
from ..security import decrypt_secret, encrypt_secret

router = APIRouter(tags=["settings"])

# OpenAI-compatible presets. `custom` supplies its own base_url + model.
AI_PRESETS: dict[str, dict[str, str]] = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
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
