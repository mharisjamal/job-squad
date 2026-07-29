"""Auth flow: register/me, duplicates, bad creds, validation, health, 401 gate."""


async def test_register_then_me(client, register):
    account = await register(username="haris", display_name="Haris")
    resp = await client.get("/api/auth/me", headers=account["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "haris"
    assert body["display_name"] == "Haris"
    assert body["id"] == account["user"]["id"]


async def test_register_normalizes_username_and_login_works(client, register):
    await register(username="haris")
    resp = await client.post(
        "/api/auth/login", json={"username": "HARIS", "password": "password123"}
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["username"] == "haris"


async def test_duplicate_username_409(client, register):
    await register(username="haris")
    resp = await client.post(
        "/api/auth/register",
        json={"username": "Haris", "display_name": "Other", "password": "password123"},
    )
    assert resp.status_code == 409


async def test_bad_password_login_401(client, register):
    await register(username="haris")
    resp = await client.post(
        "/api/auth/login", json={"username": "haris", "password": "wrong-password"}
    )
    assert resp.status_code == 401


async def test_unknown_user_login_401(client):
    resp = await client.post(
        "/api/auth/login", json={"username": "ghost", "password": "password123"}
    )
    assert resp.status_code == 401


async def test_short_password_422(client):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "haris", "display_name": "Haris", "password": "short"},
    )
    assert resp.status_code == 422


async def test_invalid_username_422(client):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "no spaces!", "display_name": "X", "password": "password123"},
    )
    assert resp.status_code == 422


async def test_health_needs_no_auth(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_unauthenticated_api_401(client):
    resp = await client.get("/api/groups")
    assert resp.status_code == 401


async def test_garbage_token_401(client):
    resp = await client.get("/api/groups", headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401
