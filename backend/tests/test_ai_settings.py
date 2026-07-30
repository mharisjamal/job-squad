"""BYOK AI settings: encrypted-at-rest key, preset filling, blank-keeps, and the
test endpoint (with a mocked AI client - no real network)."""

import app.ai as ai_module
from app.models import UserAISettings
from app.security import decrypt_secret, encrypt_secret

TEST_SECRET = "test-secret-not-for-production"


# ---------------------------------------------------------------------------
# Fernet primitives (unit)
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_round_trip():
    token = encrypt_secret("my-api-key", TEST_SECRET)
    assert token != "my-api-key"
    assert decrypt_secret(token, TEST_SECRET) == "my-api-key"


def test_encryption_is_nondeterministic():
    # Fernet embeds a random IV, so two encryptions differ (no ECB leakage).
    assert encrypt_secret("same", TEST_SECRET) != encrypt_secret("same", TEST_SECRET)


def test_decrypt_with_wrong_secret_returns_none():
    token = encrypt_secret("my-api-key", TEST_SECRET)
    assert decrypt_secret(token, "a-different-secret") is None


def test_decrypt_garbage_returns_none():
    assert decrypt_secret("not-a-token", TEST_SECRET) is None


async def _put(client, headers, **body):
    return await client.put("/api/settings/ai", json=body, headers=headers)


async def test_default_settings_are_empty(client, register):
    account = await register(username="haris")
    resp = await client.get("/api/settings/ai", headers=account["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "provider": None, "base_url": None, "model": None, "key_set": False
    }


async def test_gemini_preset_fills_base_url_and_model(client, register):
    account = await register(username="haris")
    resp = await _put(client, account["headers"], provider="gemini", key="sk-test-123")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "gemini"
    assert body["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert body["model"] == "gemini-2.5-flash"
    assert body["key_set"] is True
    # The key is NEVER echoed back.
    assert "key" not in body


async def test_groq_preset_and_custom_base_url(client, register):
    account = await register(username="haris")
    resp = await _put(client, account["headers"], provider="groq", key="gsk-test")
    assert resp.json()["base_url"] == "https://api.groq.com/openai/v1"
    assert resp.json()["model"] == "llama-3.3-70b-versatile"
    # Custom provider takes the caller's base_url + model verbatim.
    resp = await _put(
        client, account["headers"], provider="custom",
        base_url="https://llm.example.com/v1", model="my-model", key="k",
    )
    body = resp.json()
    assert body["provider"] == "custom"
    assert body["base_url"] == "https://llm.example.com/v1"
    assert body["model"] == "my-model"


async def test_model_is_user_editable_over_preset(client, register):
    account = await register(username="haris")
    resp = await _put(
        client, account["headers"], provider="gemini", model="gemini-2.0-flash", key="k"
    )
    assert resp.json()["model"] == "gemini-2.0-flash"


async def test_key_is_encrypted_at_rest_and_never_plaintext(client, register, asgi_app):
    account = await register(username="haris")
    await _put(client, account["headers"], provider="groq", key="super-secret-key")
    user_id = account["user"]["id"]
    async with asgi_app.state.sessionmaker() as session:
        row = await session.get(UserAISettings, user_id)
    assert row is not None
    assert row.key_encrypted is not None
    # Stored form is ciphertext, not the plaintext.
    assert row.key_encrypted != "super-secret-key"
    assert "super-secret-key" not in row.key_encrypted
    # It round-trips back through Fernet with the app secret.
    assert decrypt_secret(row.key_encrypted, TEST_SECRET) == "super-secret-key"


async def test_blank_key_keeps_the_stored_one(client, register, asgi_app):
    account = await register(username="haris")
    await _put(client, account["headers"], provider="groq", key="original-key")
    # A later PUT with no key (model change only) must not wipe the key.
    resp = await _put(client, account["headers"], provider="groq", model="llama-3.1-8b")
    assert resp.json()["key_set"] is True
    async with asgi_app.state.sessionmaker() as session:
        row = await session.get(UserAISettings, account["user"]["id"])
    assert decrypt_secret(row.key_encrypted, TEST_SECRET) == "original-key"


async def test_get_never_returns_the_key(client, register):
    account = await register(username="haris")
    await _put(client, account["headers"], provider="gemini", key="sk-abc")
    resp = await client.get("/api/settings/ai", headers=account["headers"])
    body = resp.json()
    assert set(body.keys()) == {"provider", "base_url", "model", "key_set"}
    assert body["key_set"] is True


async def test_invalid_provider_is_422(client, register):
    account = await register(username="haris")
    resp = await _put(client, account["headers"], provider="openai", key="k")
    assert resp.status_code == 422


async def test_settings_require_auth(client):
    assert (await client.get("/api/settings/ai")).status_code == 401
    assert (await client.put("/api/settings/ai", json={"provider": "gemini"})).status_code == 401


# ---------------------------------------------------------------------------
# Test endpoint (mocked client)
# ---------------------------------------------------------------------------


async def test_test_endpoint_ok_with_mocked_client(client, register, monkeypatch):
    account = await register(username="haris")
    await _put(client, account["headers"], provider="groq", key="the-key")

    captured = {}

    async def fake_chat_completion(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(ai_module, "chat_completion", fake_chat_completion)
    resp = await client.post("/api/settings/ai/test", headers=account["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}
    # The decrypted key reached the client (proves the full encrypt/decrypt path).
    assert captured["api_key"] == "the-key"
    assert captured["base_url"] == "https://api.groq.com/openai/v1"


async def test_test_endpoint_reports_provider_error(client, register, monkeypatch):
    account = await register(username="haris")
    await _put(client, account["headers"], provider="groq", key="bad")

    async def fake_chat_completion(**kwargs):
        raise ai_module.AIError("Your API key was rejected")

    monkeypatch.setattr(ai_module, "chat_completion", fake_chat_completion)
    resp = await client.post("/api/settings/ai/test", headers=account["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": False, "error": "Your API key was rejected"}


async def test_test_endpoint_without_settings(client, register):
    account = await register(username="haris")
    resp = await client.post("/api/settings/ai/test", headers=account["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert "Configure" in body["error"]
