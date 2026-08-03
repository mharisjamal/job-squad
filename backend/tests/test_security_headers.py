"""Framing protection (F5): /connect mints a 365-day extension credential on
one click, so every response refuses to be framed."""

import pytest

EXPECTED = {
    "x-frame-options": "DENY",
    "content-security-policy": "frame-ancestors 'none'",
}


def _assert_framing_denied(response):
    for header, value in EXPECTED.items():
        assert response.headers.get(header) == value, (header, response.headers)


@pytest.mark.parametrize("path", ["/health", "/api/auth/config", "/api/groups"])
async def test_headers_on_unauthenticated_routes(client, path):
    """Present on a plain 200, on a public route, and on a 401 alike."""
    _assert_framing_denied(await client.get(path))


async def test_headers_on_an_authenticated_route(client, register):
    account = await register(username="haris")
    resp = await client.get("/api/auth/me", headers=account["headers"])
    assert resp.status_code == 200
    _assert_framing_denied(resp)


async def test_headers_on_the_public_share_route(client):
    """The one unauthenticated route outside /api still gets them, and the
    response itself is unchanged (an unknown token is still a 404)."""
    resp = await client.get("/r/" + "a" * 32)
    assert resp.status_code == 404
    _assert_framing_denied(resp)


async def test_headers_on_the_spa_catch_all(client):
    """The SPA fallback keeps serving (a missing build is still its own 404)."""
    resp = await client.get("/connect")
    _assert_framing_denied(resp)


async def test_headers_on_a_validation_error(client, register):
    account = await register(username="haris")
    resp = await client.post(
        "/api/capture", json={"company_name": "X"}, headers=account["headers"]
    )
    assert resp.status_code == 422
    _assert_framing_denied(resp)
