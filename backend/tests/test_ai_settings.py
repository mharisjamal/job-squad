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
    assert body["model"] == "gemini-2.0-flash"
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


# ---------------------------------------------------------------------------
# base_url is a credential destination (F1a). The stored key is sent to it as a
# bearer token, so repointing it without re-entering the key was a working
# exfiltration path: PUT a new base_url with a blank key (which keeps the stored
# ciphertext), then press "Test" and the server hands the victim's key to the
# attacker's server.
# ---------------------------------------------------------------------------


async def _stored_key(asgi_app, user_id):
    async with asgi_app.state.sessionmaker() as session:
        row = await session.get(UserAISettings, user_id)
    return None if row is None else decrypt_secret(row.key_encrypted, TEST_SECRET)


async def test_repointing_base_url_without_a_key_is_422_and_keeps_the_key(
    client, register, asgi_app
):
    account = await register(username="haris")
    await _put(client, account["headers"], provider="groq", key="victim-key")

    resp = await _put(
        client, account["headers"], provider="custom",
        base_url="https://attacker.example.com", model="m",
    )
    assert resp.status_code == 422
    assert "Re-enter your API key" in resp.json()["detail"]

    # The settings row is untouched: same key, same endpoint.
    async with asgi_app.state.sessionmaker() as session:
        row = await session.get(UserAISettings, account["user"]["id"])
    assert row.base_url == "https://api.groq.com/openai/v1"
    assert decrypt_secret(row.key_encrypted, TEST_SECRET) == "victim-key"


async def test_the_exfiltration_path_is_closed_end_to_end(
    client, register, monkeypatch, asgi_app
):
    """The full proven attack: repoint, then press Test. The rejected PUT means
    the test call still goes to the real provider, never to the attacker."""
    account = await register(username="haris")
    await _put(client, account["headers"], provider="groq", key="victim-key")
    await _put(
        client, account["headers"], provider="custom",
        base_url="https://attacker.example.com", model="m",
    )

    captured = {}

    async def fake_chat_completion(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(ai_module, "chat_completion", fake_chat_completion)
    await client.post("/api/settings/ai/test", headers=account["headers"])
    assert captured["base_url"] == "https://api.groq.com/openai/v1"
    assert "attacker" not in captured["base_url"]


async def test_repointing_base_url_with_a_new_key_is_allowed(
    client, register, asgi_app
):
    account = await register(username="haris")
    await _put(client, account["headers"], provider="groq", key="old-key")
    resp = await _put(
        client, account["headers"], provider="custom",
        base_url="https://llm.example.com/v1", model="m", key="new-key",
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["base_url"] == "https://llm.example.com/v1"
    assert await _stored_key(asgi_app, account["user"]["id"]) == "new-key"


async def test_same_base_url_with_blank_key_still_works(client, register, asgi_app):
    """Changing only the model must not demand the key again."""
    account = await register(username="haris")
    await _put(client, account["headers"], provider="groq", key="original-key")
    resp = await _put(client, account["headers"], provider="groq", model="llama-3.1-8b")
    assert resp.status_code == 200, resp.text
    assert resp.json()["model"] == "llama-3.1-8b"
    assert await _stored_key(asgi_app, account["user"]["id"]) == "original-key"

    # A trailing slash is the same endpoint, not a change.
    resp = await _put(
        client, account["headers"], provider="custom",
        base_url="https://api.groq.com/openai/v1/", model="m",
    )
    assert resp.status_code == 200, resp.text
    assert await _stored_key(asgi_app, account["user"]["id"]) == "original-key"


async def test_plaintext_http_base_url_is_422(client, register):
    account = await register(username="haris")
    resp = await _put(
        client, account["headers"], provider="custom",
        base_url="http://evil.example.com", model="m", key="k",
    )
    assert resp.status_code == 422
    assert "https" in resp.json()["detail"]


async def test_localhost_http_base_url_is_allowed(client, register):
    """A local model server has no TLS and never leaves the machine."""
    account = await register(username="haris")
    for base_url in ("http://localhost:1234/v1", "http://127.0.0.1:8080/v1"):
        resp = await _put(
            client, account["headers"], provider="custom",
            base_url=base_url, model="m", key="k",
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["base_url"] == base_url


async def test_https_provider_base_url_is_allowed(client, register):
    account = await register(username="haris")
    resp = await _put(
        client, account["headers"], provider="custom",
        base_url="https://api.groq.com/openai/v1", model="m", key="k",
    )
    assert resp.status_code == 200, resp.text


async def test_non_http_schemes_are_422(client, register):
    account = await register(username="haris")
    for base_url in ("file:///etc/passwd", "ftp://host/x", "javascript:alert(1)", "//host/v1"):
        resp = await _put(
            client, account["headers"], provider="custom",
            base_url=base_url, model="m", key="k",
        )
        assert resp.status_code == 422, base_url


def test_base_url_problem_rules():
    from app.routers.settings import base_url_problem

    assert base_url_problem("https://api.groq.com/openai/v1") is None
    assert base_url_problem("http://localhost:1234/v1") is None
    assert base_url_problem("http://127.0.0.1:8080") is None
    assert base_url_problem(None) is None  # nothing configured, nothing sent
    assert base_url_problem("") is None
    assert base_url_problem("http://evil.example.com") is not None
    assert base_url_problem("http://localhost.evil.com") is not None
    assert base_url_problem("ftp://host/x") is not None
    assert base_url_problem("https://") is not None
