"""OAuth 2.0 authorization-code sign-in for Google, GitHub and LinkedIn.

Hand-rolled with httpx to match this codebase's stdlib-first convention: no
OAuth library, client secrets never leave the server. Tests monkeypatch
exchange_code and fetch_profile, so no network is touched.
"""

from dataclasses import dataclass

import httpx

from .config import Settings

HTTP_TIMEOUT_SECONDS = 15


class OAuthError(RuntimeError):
    """Provider handshake failed; the callback maps this to an error redirect."""


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    authorize_url: str
    token_url: str
    profile_url: str
    scope: str
    supports_pkce: bool


PROVIDERS: dict[str, ProviderConfig] = {
    "google": ProviderConfig(
        name="google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        profile_url="https://openidconnect.googleapis.com/v1/userinfo",
        scope="openid email profile",
        supports_pkce=True,
    ),
    "github": ProviderConfig(
        name="github",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        profile_url="https://api.github.com/user",
        scope="read:user user:email",
        supports_pkce=False,
    ),
    "linkedin": ProviderConfig(
        name="linkedin",
        authorize_url="https://www.linkedin.com/oauth/v2/authorization",
        token_url="https://www.linkedin.com/oauth/v2/accessToken",
        profile_url="https://api.linkedin.com/v2/userinfo",
        scope="openid profile email",
        supports_pkce=True,
    ),
}

GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


@dataclass(frozen=True)
class SocialProfile:
    provider: str
    provider_user_id: str
    email: str | None
    email_verified: bool
    display_name: str
    avatar_url: str | None


def authorize_params(
    settings: Settings, provider: ProviderConfig, state: str, code_challenge: str | None
) -> dict:
    client_id, _ = settings.provider_credentials(provider.name)
    params = {
        "client_id": client_id,
        "redirect_uri": settings.redirect_uri(provider.name),
        "response_type": "code",
        "scope": provider.scope,
        "state": state,
    }
    if provider.supports_pkce and code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    return params


async def exchange_code(
    settings: Settings, provider: ProviderConfig, code: str, code_verifier: str | None
) -> str:
    """Trade the authorization code for an access token."""
    client_id, client_secret = settings.provider_credentials(provider.name)
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": settings.redirect_uri(provider.name),
    }
    if provider.supports_pkce and code_verifier:
        data["code_verifier"] = code_verifier
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(
                provider.token_url, data=data, headers={"Accept": "application/json"}
            )
    except httpx.HTTPError as exc:
        raise OAuthError(f"token request failed: {exc}") from exc
    if response.status_code >= 300:
        raise OAuthError(f"token endpoint returned {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise OAuthError("token endpoint returned a non-JSON body") from exc
    token = payload.get("access_token")
    if not token:
        raise OAuthError(f"no access_token in response: {payload.get('error', 'unknown')}")
    return token


async def fetch_profile(
    settings: Settings, provider: ProviderConfig, access_token: str
) -> SocialProfile:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(provider.profile_url, headers=headers)
            if response.status_code >= 300:
                raise OAuthError(f"profile endpoint returned {response.status_code}")
            data = response.json()
            emails: list[dict] = []
            if provider.name == "github" and not data.get("email"):
                # GitHub hides the address unless it is public; ask explicitly.
                email_response = await client.get(GITHUB_EMAILS_URL, headers=headers)
                if email_response.status_code < 300:
                    payload = email_response.json()
                    if isinstance(payload, list):
                        emails = payload
    except httpx.HTTPError as exc:
        raise OAuthError(f"profile request failed: {exc}") from exc
    except ValueError as exc:
        raise OAuthError("profile endpoint returned a non-JSON body") from exc
    return normalize_profile(provider.name, data, emails)


def normalize_profile(provider: str, data: dict, emails: list[dict] | None = None):
    """Map a provider payload onto SocialProfile."""
    if provider == "google":
        return SocialProfile(
            provider=provider,
            provider_user_id=str(data.get("sub") or ""),
            email=(data.get("email") or None),
            email_verified=bool(data.get("email_verified")),
            display_name=(data.get("name") or data.get("email") or "").strip(),
            avatar_url=data.get("picture"),
        )
    if provider == "linkedin":
        return SocialProfile(
            provider=provider,
            provider_user_id=str(data.get("sub") or ""),
            email=(data.get("email") or None),
            email_verified=bool(data.get("email_verified")),
            display_name=(
                data.get("name")
                or " ".join(
                    part
                    for part in (data.get("given_name"), data.get("family_name"))
                    if part
                )
                or data.get("email")
                or ""
            ).strip(),
            avatar_url=data.get("picture"),
        )
    if provider == "github":
        email = data.get("email") or None
        verified = bool(email)  # a public profile email is a confirmed one
        for entry in emails or []:
            if entry.get("primary") and entry.get("verified") and entry.get("email"):
                email = entry["email"]
                verified = True
                break
        return SocialProfile(
            provider=provider,
            provider_user_id=str(data.get("id") or ""),
            email=email,
            email_verified=verified,
            display_name=(data.get("name") or data.get("login") or "").strip(),
            avatar_url=data.get("avatar_url"),
        )
    raise OAuthError(f"unknown provider {provider}")
