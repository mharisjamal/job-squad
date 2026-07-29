"""Social sign-in: start redirect, state integrity, and the linking branches.

The provider handshake is monkeypatched (token exchange + profile fetch), so
these tests never touch the network.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.models import User, UserIdentity
from app.oauth import SocialProfile, normalize_profile
from app.security import make_state_token

PROVIDER_ENV = {
    "google": ("JOBSQUAD_GOOGLE_CLIENT_ID", "JOBSQUAD_GOOGLE_CLIENT_SECRET"),
    "github": ("JOBSQUAD_GITHUB_CLIENT_ID", "JOBSQUAD_GITHUB_CLIENT_SECRET"),
    "linkedin": ("JOBSQUAD_LINKEDIN_CLIENT_ID", "JOBSQUAD_LINKEDIN_CLIENT_SECRET"),
}
TEST_SECRET = "test-secret-not-for-production"


@pytest.fixture
async def social_app(tmp_path, monkeypatch):
    """An app with all three providers configured."""
    monkeypatch.setenv("JOBSQUAD_DB_PATH", str(tmp_path / "social.db"))
    monkeypatch.setenv("JOBSQUAD_SECRET", TEST_SECRET)
    monkeypatch.setenv("JOBSQUAD_PUBLIC_URL", "https://jobsquad.example")
    for provider, (id_var, secret_var) in PROVIDER_ENV.items():
        monkeypatch.setenv(id_var, f"{provider}-client-id")
        monkeypatch.setenv(secret_var, f"{provider}-client-secret")
    from app.main import create_app

    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def social_client(social_app):
    transport = ASGITransport(app=social_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
def fake_provider(monkeypatch):
    """Stub the provider handshake; the test sets the profile it returns."""
    state: dict = {"profile": None, "calls": []}

    async def _exchange(settings, provider, code, code_verifier):
        state["calls"].append({"code": code, "verifier": code_verifier})
        return "provider-access-token"

    async def _profile(settings, provider, access_token):
        return state["profile"]

    monkeypatch.setattr("app.routers.auth.exchange_code", _exchange)
    monkeypatch.setattr("app.routers.auth.fetch_profile", _profile)
    return state


def _profile(**overrides) -> SocialProfile:
    base = {
        "provider": "google",
        "provider_user_id": "google-123",
        "email": "haris@example.com",
        "email_verified": True,
        "display_name": "Haris Jamal",
        "avatar_url": "https://cdn.example/avatar.png",
    }
    base.update(overrides)
    return SocialProfile(**base)


def _fragment(response) -> dict:
    """Parse the fragment of the SPA redirect and assert nothing leaked to query."""
    location = response.headers["location"]
    parsed = urlparse(location)
    assert parsed.query == "", f"nothing may ride the query string: {location}"
    return {k: v[0] for k, v in parse_qs(parsed.fragment).items()}


# ---------------------------------------------------------------------------
# config + start
# ---------------------------------------------------------------------------


async def test_config_lists_only_configured_providers(social_client, client):
    resp = await social_client.get("/api/auth/config")
    assert resp.status_code == 200
    assert resp.json()["providers"] == ["google", "github", "linkedin"]

    # The default test app has no provider credentials.
    resp = await client.get("/api/auth/config")
    assert resp.json()["providers"] == []


async def test_start_404_when_provider_unconfigured(client):
    for provider in ("google", "github", "linkedin"):
        resp = await client.get(f"/api/auth/oauth/{provider}/start")
        assert resp.status_code == 404


async def test_start_404_for_unknown_provider(social_client):
    resp = await social_client.get("/api/auth/oauth/myspace/start")
    assert resp.status_code == 404


async def test_google_start_redirects_with_pkce(social_client):
    resp = await social_client.get("/api/auth/oauth/google/start")
    assert resp.status_code == 302
    location = urlparse(resp.headers["location"])
    assert location.netloc == "accounts.google.com"
    params = {k: v[0] for k, v in parse_qs(location.query).items()}
    assert params["client_id"] == "google-client-id"
    assert params["response_type"] == "code"
    assert params["scope"] == "openid email profile"
    assert params["redirect_uri"] == (
        "https://jobsquad.example/api/auth/oauth/google/callback"
    )
    assert params["code_challenge_method"] == "S256"
    assert params["code_challenge"]
    assert params["state"]


async def test_github_start_has_no_pkce_and_right_scopes(social_client):
    resp = await social_client.get("/api/auth/oauth/github/start")
    assert resp.status_code == 302
    location = urlparse(resp.headers["location"])
    assert location.netloc == "github.com"
    params = {k: v[0] for k, v in parse_qs(location.query).items()}
    assert params["scope"] == "read:user user:email"
    assert "code_challenge" not in params


async def test_linkedin_start(social_client):
    resp = await social_client.get("/api/auth/oauth/linkedin/start")
    assert resp.status_code == 302
    location = urlparse(resp.headers["location"])
    assert location.netloc == "www.linkedin.com"
    params = {k: v[0] for k, v in parse_qs(location.query).items()}
    assert params["scope"] == "openid profile email"


# ---------------------------------------------------------------------------
# callback: state handling
# ---------------------------------------------------------------------------


async def _start_state(social_client, provider="google") -> str:
    resp = await social_client.get(f"/api/auth/oauth/{provider}/start")
    return parse_qs(urlparse(resp.headers["location"]).query)["state"][0]


async def test_callback_tampered_state_redirects_with_error(social_client, fake_provider):
    fake_provider["profile"] = _profile()
    state = await _start_state(social_client)
    resp = await social_client.get(
        "/api/auth/oauth/google/callback",
        params={"code": "abc", "state": state + "x"},
    )
    assert resp.status_code == 302
    assert _fragment(resp) == {"error": "invalid_state"}


async def test_callback_expired_state_redirects_with_error(social_client, fake_provider):
    fake_provider["profile"] = _profile()
    stale = make_state_token({"provider": "google"}, TEST_SECRET, ttl_seconds=-10)
    resp = await social_client.get(
        "/api/auth/oauth/google/callback", params={"code": "abc", "state": stale}
    )
    assert _fragment(resp) == {"error": "invalid_state"}


async def test_callback_state_from_another_provider_rejected(social_client, fake_provider):
    fake_provider["profile"] = _profile()
    state = await _start_state(social_client, provider="github")
    resp = await social_client.get(
        "/api/auth/oauth/google/callback", params={"code": "abc", "state": state}
    )
    assert _fragment(resp) == {"error": "invalid_state"}


async def test_callback_provider_denied(social_client):
    resp = await social_client.get(
        "/api/auth/oauth/google/callback", params={"error": "access_denied"}
    )
    assert _fragment(resp) == {"error": "access_denied"}


async def test_callback_provider_error_is_generic(social_client, fake_provider, monkeypatch):
    from app.oauth import OAuthError

    async def _boom(settings, provider, code, code_verifier):
        raise OAuthError("token endpoint returned 401")

    monkeypatch.setattr("app.routers.auth.exchange_code", _boom)
    state = await _start_state(social_client)
    resp = await social_client.get(
        "/api/auth/oauth/google/callback", params={"code": "abc", "state": state}
    )
    assert _fragment(resp) == {"error": "provider_error"}


# ---------------------------------------------------------------------------
# callback: the four linking branches
# ---------------------------------------------------------------------------


async def _callback(social_client, provider="google"):
    state = await _start_state(social_client, provider)
    return await social_client.get(
        f"/api/auth/oauth/{provider}/callback",
        params={"code": "auth-code", "state": state},
    )


async def test_branch4_new_account_is_created(social_client, social_app, fake_provider):
    fake_provider["profile"] = _profile()
    resp = await _callback(social_client)
    assert resp.status_code == 302
    fragment = _fragment(resp)
    token = fragment["token"]
    assert token

    # The token authenticates.
    resp = await social_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "haris"
    assert body["display_name"] == "Haris Jamal"
    assert body["avatar_url"] == "https://cdn.example/avatar.png"

    async with social_app.state.sessionmaker() as session:
        user = await session.scalar(select(User))
        assert user.password_hash is None  # social-only account
        identity = await session.scalar(select(UserIdentity))
        assert identity.provider == "google"
        assert identity.provider_user_id == "google-123"
        assert identity.user_id == user.id


async def test_branch1_known_identity_logs_in_without_duplicating(
    social_client, social_app, fake_provider
):
    fake_provider["profile"] = _profile()
    await _callback(social_client)
    # Same provider user signs in again, this time with a changed display name.
    fake_provider["profile"] = _profile(display_name="Haris J")
    resp = await _callback(social_client)
    assert "token" in _fragment(resp)

    async with social_app.state.sessionmaker() as session:
        assert len((await session.scalars(select(User))).all()) == 1
        assert len((await session.scalars(select(UserIdentity))).all()) == 1


async def test_branch2_verified_email_links_to_existing_password_account(
    social_client, social_app, fake_provider
):
    # A password account exists for this address.
    resp = await social_client.post(
        "/api/auth/register",
        json={
            "display_name": "Haris",
            "email": "haris@example.com",
            "password": "password123",
        },
    )
    assert resp.status_code == 200
    existing_id = resp.json()["user"]["id"]

    fake_provider["profile"] = _profile(email_verified=True)
    resp = await _callback(social_client)
    token = _fragment(resp)["token"]
    resp = await social_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.json()["id"] == existing_id  # linked, not duplicated

    async with social_app.state.sessionmaker() as session:
        assert len((await session.scalars(select(User))).all()) == 1
        identity = await session.scalar(select(UserIdentity))
        assert identity.user_id == existing_id
        # The password still works: linking does not disable it.
        user = await session.get(User, existing_id)
        assert user.password_hash is not None


async def test_branch3_unverified_email_cannot_take_over(
    social_client, social_app, fake_provider
):
    resp = await social_client.post(
        "/api/auth/register",
        json={
            "display_name": "Haris",
            "email": "haris@example.com",
            "password": "password123",
        },
    )
    assert resp.status_code == 200

    fake_provider["profile"] = _profile(email_verified=False)
    resp = await _callback(social_client)
    assert _fragment(resp) == {"error": "email_unverified"}

    async with social_app.state.sessionmaker() as session:
        assert (await session.scalars(select(UserIdentity))).all() == []
        assert len((await session.scalars(select(User))).all()) == 1


async def test_unverified_email_creates_nothing_even_without_an_existing_user(
    social_client, social_app, fake_provider
):
    fake_provider["profile"] = _profile(email_verified=False)
    resp = await _callback(social_client)
    assert _fragment(resp) == {"error": "email_unverified"}
    async with social_app.state.sessionmaker() as session:
        assert (await session.scalars(select(User))).all() == []


async def test_social_account_cannot_password_login(
    social_client, social_app, fake_provider
):
    fake_provider["profile"] = _profile()
    await _callback(social_client)
    resp = await social_client.post(
        "/api/auth/login",
        json={"identifier": "haris@example.com", "password": "password123"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == (
        "That account signs in with Google, GitHub, or LinkedIn."
    )


async def test_next_path_is_carried_through_state(social_client, fake_provider):
    fake_provider["profile"] = _profile()
    resp = await social_client.get(
        "/api/auth/oauth/google/start", params={"next": "/g/1/board"}
    )
    state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
    resp = await social_client.get(
        "/api/auth/oauth/google/callback",
        params={"code": "auth-code", "state": state},
    )
    fragment = _fragment(resp)
    assert fragment["next"] == "/g/1/board"
    assert fragment["token"]


async def test_pkce_verifier_is_passed_to_the_token_exchange(
    social_client, fake_provider
):
    fake_provider["profile"] = _profile()
    await _callback(social_client)
    assert fake_provider["calls"][0]["verifier"]

    # GitHub does not support PKCE, so no verifier travels with it.
    fake_provider["profile"] = _profile(provider="github", provider_user_id="gh-1")
    await _callback(social_client, provider="github")
    assert fake_provider["calls"][1]["verifier"] is None


# ---------------------------------------------------------------------------
# profile normalization
# ---------------------------------------------------------------------------


def test_normalize_google_profile():
    profile = normalize_profile(
        "google",
        {
            "sub": "1234",
            "email": "haris@example.com",
            "email_verified": True,
            "name": "Haris",
            "picture": "https://cdn/x.png",
        },
    )
    assert profile.provider_user_id == "1234"
    assert profile.email_verified is True
    assert profile.avatar_url == "https://cdn/x.png"


def test_normalize_github_uses_primary_verified_email():
    profile = normalize_profile(
        "github",
        {"id": 99, "login": "harisj", "name": None, "email": None, "avatar_url": "a.png"},
        [
            {"email": "other@example.com", "primary": False, "verified": True},
            {"email": "haris@example.com", "primary": True, "verified": True},
        ],
    )
    assert profile.provider_user_id == "99"
    assert profile.email == "haris@example.com"
    assert profile.email_verified is True
    assert profile.display_name == "harisj"


def test_normalize_github_unverified_when_no_verified_address():
    profile = normalize_profile(
        "github",
        {"id": 7, "login": "ghost", "email": None},
        [{"email": "nope@example.com", "primary": True, "verified": False}],
    )
    assert profile.email_verified is False


def test_normalize_linkedin_profile():
    profile = normalize_profile(
        "linkedin",
        {
            "sub": "abc",
            "email": "haris@example.com",
            "email_verified": True,
            "given_name": "Haris",
            "family_name": "Jamal",
        },
    )
    assert profile.provider_user_id == "abc"
    assert profile.display_name == "Haris Jamal"
