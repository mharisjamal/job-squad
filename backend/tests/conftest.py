"""Test fixtures: fresh app + tmp SQLite DB per test, httpx ASGI client, helpers."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def asgi_app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSQUAD_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("JOBSQUAD_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("JOBSQUAD_TOKEN_TTL_HOURS", "1")
    from app.main import create_app

    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(asgi_app):
    transport = ASGITransport(app=asgi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
def register(client):
    async def _register(username="haris", password="password123", display_name=None):
        resp = await client.post(
            "/api/auth/register",
            json={
                "username": username,
                "display_name": display_name or username.title(),
                "password": password,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        return {
            "token": data["token"],
            "user": data["user"],
            "headers": {"Authorization": f"Bearer {data['token']}"},
        }

    return _register


@pytest.fixture
def make_group(client):
    async def _make_group(headers, name="Job Hunt 2026"):
        resp = await client.post("/api/groups", json={"name": name}, headers=headers)
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _make_group


@pytest.fixture
def make_company(client):
    async def _make_company(headers, gid, name="TechCorp", **extra):
        resp = await client.post(
            f"/api/groups/{gid}/companies", json={"name": name, **extra}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _make_company


@pytest.fixture
def make_portal(client):
    async def _make_portal(headers, gid, name="LinkedIn", **extra):
        resp = await client.post(
            f"/api/groups/{gid}/portals", json={"name": name, **extra}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _make_portal
