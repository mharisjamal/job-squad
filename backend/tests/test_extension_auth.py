"""Extension tokens (Phase E1): minting, use, revocation, the lateral-movement
guard on the management routes, the hourly last_used_at bump, and the new-table
migration."""

from datetime import timedelta

import pytest
from sqlalchemy import inspect, select

from app.db import init_db
from app.models import ExtensionToken, Group, User, utcnow
from app.security import jwt_decode, make_extension_token


async def _pair(client, headers, label=None):
    """Run the pairing POST and return the response body (token shown once)."""
    body = {} if label is None else {"label": label}
    resp = await client.post("/api/auth/extension-token", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ext_headers(paired: dict) -> dict:
    return {"Authorization": f"Bearer {paired['token']}"}


# ---------------------------------------------------------------------------
# Minting and shape
# ---------------------------------------------------------------------------


async def test_create_returns_token_once_with_ext_claims(client, register, asgi_app):
    account = await register(username="haris")
    paired = await _pair(client, account["headers"], label="Chrome laptop")
    assert set(paired) == {"token", "id", "label", "created_at"}
    assert paired["label"] == "Chrome laptop"
    assert paired["created_at"].endswith("Z")

    payload = jwt_decode(paired["token"], asgi_app.state.settings.secret)
    assert payload["typ"] == "ext"
    assert payload["sub"] == str(account["user"]["id"])
    assert isinstance(payload["jti"], str) and payload["jti"]
    # 365 days, give or take the clock: comfortably beyond the session TTL.
    assert payload["exp"] - int(utcnow().timestamp()) > 300 * 86400


async def test_session_token_has_no_typ_claim(client, register, asgi_app):
    """Session tokens are unchanged by E1."""
    account = await register(username="haris")
    payload = jwt_decode(account["token"], asgi_app.state.settings.secret)
    assert "typ" not in payload
    assert "jti" not in payload


async def test_body_is_optional(client, register):
    account = await register(username="haris")
    resp = await client.post("/api/auth/extension-token", headers=account["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["label"] is None


# ---------------------------------------------------------------------------
# Using an extension token
# ---------------------------------------------------------------------------


async def test_extension_token_works_on_the_allowed_routes(client, register, make_group):
    """The capture surface, and nothing else."""
    account = await register(username="haris")
    group = await make_group(account["headers"])
    paired = await _pair(client, account["headers"])
    headers = _ext_headers(paired)

    resp = await client.get("/api/groups", headers=headers)
    assert resp.status_code == 200
    assert [g["id"] for g in resp.json()] == [group["id"]]

    resp = await client.get(
        "/api/capture/lookup",
        params={"group_id": group["id"], "company_name": "TechCorp"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(
        "/api/capture/lookup",
        json={"group_id": group["id"], "company_name": "TechCorp"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(
        "/api/capture",
        json={"group_id": group["id"], "company_name": "TechCorp"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # A route a session token may use freely is still closed to the extension.
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 401
    assert (await client.get("/api/auth/me", headers=account["headers"])).status_code == 200


async def test_revoked_token_is_401(client, register):
    account = await register(username="haris")
    paired = await _pair(client, account["headers"])
    assert (await client.get("/api/groups", headers=_ext_headers(paired))).status_code == 200

    resp = await client.delete(
        f"/api/auth/extension-tokens/{paired['id']}", headers=account["headers"]
    )
    assert resp.status_code == 200
    # Still signature-valid, but the row says no.
    resp = await client.get("/api/groups", headers=_ext_headers(paired))
    assert resp.status_code == 401


async def test_forged_jti_is_401(client, register, asgi_app):
    """A validly signed ext token whose jti has no row is refused."""
    account = await register(username="haris")
    token = make_extension_token(
        account["user"]["id"], asgi_app.state.settings.secret, "deadbeef" * 4
    )
    resp = await client.get("/api/groups", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_another_users_jti_is_401(client, register, asgi_app):
    """A token whose sub does not own the jti row is refused, so one user's
    token cannot be replayed as another's."""
    owner = await register(username="haris")
    other = await register(username="ali")
    paired = await _pair(client, owner["headers"])
    payload = jwt_decode(paired["token"], asgi_app.state.settings.secret)
    forged = make_extension_token(
        other["user"]["id"], asgi_app.state.settings.secret, payload["jti"]
    )
    resp = await client.get("/api/groups", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


async def test_unknown_typ_claim_is_401(client, register, asgi_app):
    from app.security import jwt_encode

    account = await register(username="haris")
    token = jwt_encode(
        {
            "sub": str(account["user"]["id"]),
            "exp": int(utcnow().timestamp()) + 3600,
            "typ": "something-else",
        },
        asgi_app.state.settings.secret,
    )
    resp = await client.get("/api/groups", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_extension_token_not_honored_as_query_param(client, register):
    """The ?access_token= allowlist (SSE + exports) is unchanged: an extension
    token is no more usable there than a session token."""
    account = await register(username="haris")
    paired = await _pair(client, account["headers"])
    resp = await client.get("/api/groups", params={"access_token": paired["token"]})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# last_used_at is bumped at most hourly
# ---------------------------------------------------------------------------


async def _token_row(asgi_app, token_id: int) -> ExtensionToken:
    async with asgi_app.state.sessionmaker() as session:
        row = await session.get(ExtensionToken, token_id)
        assert row is not None
        return row


async def test_last_used_at_is_bumped_at_most_hourly(client, register, asgi_app):
    account = await register(username="haris")
    paired = await _pair(client, account["headers"])
    headers = _ext_headers(paired)

    assert (await _token_row(asgi_app, paired["id"])).last_used_at is None

    await client.get("/api/groups", headers=headers)
    first = (await _token_row(asgi_app, paired["id"])).last_used_at
    assert first is not None

    # Several more calls inside the hour must not write again.
    for _ in range(3):
        await client.get("/api/groups", headers=headers)
    assert (await _token_row(asgi_app, paired["id"])).last_used_at == first

    # Age the row past the window: the next call bumps it.
    async with asgi_app.state.sessionmaker() as session:
        row = await session.get(ExtensionToken, paired["id"])
        row.last_used_at = first - timedelta(hours=2)
        await session.commit()
    await client.get("/api/groups", headers=headers)
    bumped = (await _token_row(asgi_app, paired["id"])).last_used_at
    assert bumped is not None and bumped > first - timedelta(hours=2)
    assert bumped >= first


async def test_listing_exposes_last_used_at(client, register, asgi_app):
    account = await register(username="haris")
    paired = await _pair(client, account["headers"], label="Work Chrome")
    await client.get("/api/groups", headers=_ext_headers(paired))

    resp = await client.get("/api/auth/extension-tokens", headers=account["headers"])
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert set(rows[0]) == {"id", "label", "created_at", "last_used_at"}
    assert rows[0]["label"] == "Work Chrome"
    assert rows[0]["last_used_at"] is not None


# ---------------------------------------------------------------------------
# Management routes: session tokens only (lateral-movement guard)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/auth/extension-token"),
        ("get", "/api/auth/extension-tokens"),
        ("delete", "/api/auth/extension-tokens/{token_id}"),
    ],
)
async def test_extension_token_rejected_on_management_routes(
    client, register, method, path
):
    account = await register(username="haris")
    paired = await _pair(client, account["headers"])
    url = path.format(token_id=paired["id"])

    resp = await getattr(client, method)(url, headers=_ext_headers(paired))
    assert resp.status_code == 401, resp.text

    # The same call with a session token succeeds.
    resp = await getattr(client, method)(url, headers=account["headers"])
    assert resp.status_code == 200, resp.text


async def test_management_routes_are_scoped_to_me(client, register):
    owner = await register(username="haris")
    other = await register(username="ali")
    paired = await _pair(client, owner["headers"])

    # Someone else's token is invisible...
    resp = await client.get("/api/auth/extension-tokens", headers=other["headers"])
    assert resp.status_code == 200
    assert resp.json() == []
    # ...and unrevokable, as a 404 rather than a 403 (no existence leak).
    resp = await client.delete(
        f"/api/auth/extension-tokens/{paired['id']}", headers=other["headers"]
    )
    assert resp.status_code == 404
    # Still usable by its owner: the failed revoke changed nothing.
    assert (await client.get("/api/groups", headers=_ext_headers(paired))).status_code == 200


async def test_revoked_tokens_drop_out_of_the_listing(client, register):
    account = await register(username="haris")
    keep = await _pair(client, account["headers"], label="Keep")
    drop = await _pair(client, account["headers"], label="Drop")
    await client.delete(
        f"/api/auth/extension-tokens/{drop['id']}", headers=account["headers"]
    )
    resp = await client.get("/api/auth/extension-tokens", headers=account["headers"])
    assert [row["id"] for row in resp.json()] == [keep["id"]]


async def test_revoke_is_idempotent(client, register):
    account = await register(username="haris")
    paired = await _pair(client, account["headers"])
    for _ in range(2):
        resp = await client.delete(
            f"/api/auth/extension-tokens/{paired['id']}", headers=account["headers"]
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


async def test_management_routes_need_auth(client, register):
    account = await register(username="haris")
    paired = await _pair(client, account["headers"])
    assert (await client.post("/api/auth/extension-token")).status_code == 401
    assert (await client.get("/api/auth/extension-tokens")).status_code == 401
    resp = await client.delete(f"/api/auth/extension-tokens/{paired['id']}")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Migration: one new table, nothing else touched
# ---------------------------------------------------------------------------


async def test_extension_tokens_table_is_created(asgi_app):
    async with asgi_app.state.engine.connect() as conn:
        names = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
    assert "extension_tokens" in names


async def test_init_db_is_idempotent_and_preserves_extension_rows(asgi_app):
    engine = asgi_app.state.engine
    sessionmaker = asgi_app.state.sessionmaker

    async with sessionmaker() as session:
        user = User(username="haris", display_name="Haris", email="haris@example.com")
        session.add(user)
        await session.flush()
        session.add(Group(name="Squad", invite_code="ABC12345", owner_id=user.id))
        session.add(
            ExtensionToken(user_id=user.id, jti="a" * 32, label="Chrome laptop")
        )
        await session.commit()
        user_id = user.id

    # Every boot re-runs init_db against the live database.
    await init_db(engine)

    async with sessionmaker() as session:
        row = await session.scalar(
            select(ExtensionToken).where(ExtensionToken.user_id == user_id)
        )
        assert row is not None
        assert row.jti == "a" * 32
        assert row.label == "Chrome laptop"
        assert row.revoked is False
        assert row.last_used_at is None
        # The pre-existing rows are untouched.
        assert await session.scalar(select(Group).where(Group.owner_id == user_id))


# ---------------------------------------------------------------------------
# Scope: an extension token is a capture credential, not a session (F1b)
# ---------------------------------------------------------------------------


async def test_extension_token_is_refused_off_the_allowlist(
    client, register, make_group, make_company
):
    """A stolen extension token must not be walkable up into an account
    takeover: it cannot read a company, edit a group, regenerate an invite,
    touch AI settings, or upload a resume."""
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")
    paired = await _pair(client, account["headers"])
    headers = _ext_headers(paired)

    blocked = [
        ("put", "/api/settings/ai", {"json": {"provider": "groq", "key": "k"}}),
        ("post", f"/api/groups/{group['id']}/regenerate-invite", {}),
        ("patch", f"/api/groups/{group['id']}", {"json": {"visibility": "public"}}),
        ("get", f"/api/companies/{company['id']}", {}),
        ("post", "/api/resumes", {}),
        ("get", f"/api/groups/{group['id']}/companies", {}),
        ("get", f"/api/groups/{group['id']}/applications", {}),
        ("delete", f"/api/groups/{group['id']}/members/{account['user']['id']}", {}),
    ]
    for method, path, kwargs in blocked:
        resp = await getattr(client, method)(path, headers=headers, **kwargs)
        assert resp.status_code == 401, f"{method.upper()} {path} -> {resp.status_code}"

    # The invite code is unchanged and the group is still private: the rejected
    # calls did nothing.
    fresh = (
        await client.get(f"/api/groups/{group['id']}", headers=account["headers"])
    ).json()
    assert fresh["invite_code"] == group["invite_code"]
    assert fresh["visibility"] == "private"


async def test_session_tokens_are_unaffected_by_the_extension_scope(
    client, register, make_group, make_company
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")
    headers = account["headers"]

    assert (await client.get("/api/auth/me", headers=headers)).status_code == 200
    assert (await client.get(f"/api/companies/{company['id']}", headers=headers)).status_code == 200
    resp = await client.patch(
        f"/api/groups/{group['id']}", json={"visibility": "public"}, headers=headers
    )
    assert resp.status_code == 200
    resp = await client.put(
        "/api/settings/ai", json={"provider": "groq", "key": "k"}, headers=headers
    )
    assert resp.status_code == 200


def test_extension_route_allowlist_is_exact():
    from app.deps import extension_route_allowed

    assert extension_route_allowed("GET", "/api/groups")
    assert extension_route_allowed("GET", "/api/groups/")
    assert extension_route_allowed("get", "/api/groups")
    assert extension_route_allowed("POST", "/api/capture")
    assert extension_route_allowed("GET", "/api/capture/lookup")
    assert extension_route_allowed("POST", "/api/capture/lookup")
    # A prefix is not a match, and the method matters.
    assert not extension_route_allowed("POST", "/api/groups")
    assert not extension_route_allowed("GET", "/api/groups/1")
    assert not extension_route_allowed("GET", "/api/capture")
    assert not extension_route_allowed("DELETE", "/api/capture")
    assert not extension_route_allowed("GET", "/api/groups/1/companies")
