"""Test fixtures: fresh app + tmp SQLite DB per test, httpx ASGI client, helpers."""

import pytest
from httpx import ASGITransport, AsyncClient

# Optional integrations must be OFF for the base test app, whatever the
# ambient environment (or a concurrently active fixture) has set.
OPTIONAL_ENV_VARS = (
    "JOBSQUAD_RESEND_API_KEY",
    "JOBSQUAD_MAIL_FROM",
    "JOBSQUAD_SMTP_HOST",
    "JOBSQUAD_SMTP_USER",
    "JOBSQUAD_SMTP_PASSWORD",
    "JOBSQUAD_GOOGLE_CLIENT_ID",
    "JOBSQUAD_GOOGLE_CLIENT_SECRET",
    "JOBSQUAD_GITHUB_CLIENT_ID",
    "JOBSQUAD_GITHUB_CLIENT_SECRET",
    "JOBSQUAD_LINKEDIN_CLIENT_ID",
    "JOBSQUAD_LINKEDIN_CLIENT_SECRET",
    "DATABASE_URL",
)


@pytest.fixture(scope="session", autouse=True)
def _load_env_files_once():
    """Consume any developer .env up front so a later Settings.load() cannot
    re-inject its values after a fixture has deliberately cleared them."""
    from app.config import load_env_files

    load_env_files()


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Every test app runs on local SQLite with all integrations off, even on
    a machine whose .env configures a real database or provider."""
    for name in OPTIONAL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
async def asgi_app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSQUAD_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("JOBSQUAD_SECRET", "test-secret-not-for-production")
    monkeypatch.setenv("JOBSQUAD_TOKEN_TTL_HOURS", "1")
    for name in OPTIONAL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
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
    """Create an account. `username` is the handle the server should derive:
    it is sent as the email local part, so tests can still assert on it."""

    async def _register(
        username="haris", password="password123", display_name=None, email=None
    ):
        resp = await client.post(
            "/api/auth/register",
            json={
                "display_name": display_name or username.title(),
                "email": email or f"{username}@example.com",
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
