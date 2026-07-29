"""Environment-driven settings, read at create_app() time (not import time)."""

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_str(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    db_path: Path
    secret: str
    token_ttl_hours: int
    port: int
    resend_api_key: str | None = None
    mail_from: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    smtp_from: str | None = None
    public_url: str = "http://localhost:8100"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
    linkedin_client_id: str | None = None
    linkedin_client_secret: str | None = None

    @property
    def otp_required(self) -> bool:
        """Email-OTP signup activates only when a mail transport is configured."""
        return bool(self.resend_api_key or self.smtp_host)

    def provider_credentials(self, provider: str) -> tuple[str, str] | None:
        """Client id/secret for an OAuth provider, or None when unconfigured."""
        client_id = getattr(self, f"{provider}_client_id", None)
        client_secret = getattr(self, f"{provider}_client_secret", None)
        if client_id and client_secret:
            return client_id, client_secret
        return None

    @property
    def enabled_providers(self) -> list[str]:
        return [
            provider
            for provider in ("google", "github", "linkedin")
            if self.provider_credentials(provider) is not None
        ]

    def redirect_uri(self, provider: str) -> str:
        return f"{self.public_url.rstrip('/')}/api/auth/oauth/{provider}/callback"

    @classmethod
    def load(cls) -> "Settings":
        db_raw = os.environ.get("JOBSQUAD_DB_PATH", "data/jobsquad.db")
        db_path = Path(db_raw)
        if not db_path.is_absolute():
            db_path = REPO_ROOT / db_path
        secret = os.environ.get("JOBSQUAD_SECRET", "").strip()
        if not secret:
            secret = _load_or_create_secret(REPO_ROOT / "data" / ".secret")
        smtp_user = _env_str("JOBSQUAD_SMTP_USER")
        return cls(
            repo_root=REPO_ROOT,
            db_path=db_path,
            secret=secret,
            token_ttl_hours=int(os.environ.get("JOBSQUAD_TOKEN_TTL_HOURS", "168")),
            port=int(os.environ.get("JOBSQUAD_PORT", "8100")),
            resend_api_key=_env_str("JOBSQUAD_RESEND_API_KEY"),
            mail_from=_env_str("JOBSQUAD_MAIL_FROM"),
            smtp_host=_env_str("JOBSQUAD_SMTP_HOST"),
            smtp_port=int(os.environ.get("JOBSQUAD_SMTP_PORT", "587")),
            smtp_user=smtp_user,
            smtp_password=_env_str("JOBSQUAD_SMTP_PASSWORD"),
            smtp_starttls=_env_flag("JOBSQUAD_SMTP_STARTTLS", True),
            smtp_from=_env_str("JOBSQUAD_SMTP_FROM") or smtp_user,
            public_url=(
                _env_str("JOBSQUAD_PUBLIC_URL") or "http://localhost:8100"
            ).rstrip("/"),
            google_client_id=_env_str("JOBSQUAD_GOOGLE_CLIENT_ID"),
            google_client_secret=_env_str("JOBSQUAD_GOOGLE_CLIENT_SECRET"),
            github_client_id=_env_str("JOBSQUAD_GITHUB_CLIENT_ID"),
            github_client_secret=_env_str("JOBSQUAD_GITHUB_CLIENT_SECRET"),
            linkedin_client_id=_env_str("JOBSQUAD_LINKEDIN_CLIENT_ID"),
            linkedin_client_secret=_env_str("JOBSQUAD_LINKEDIN_CLIENT_SECRET"),
        )


def _load_or_create_secret(path: Path) -> str:
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    generated = secrets.token_hex(32)
    # Owner-only permissions on POSIX; harmless no-op semantics on Windows.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(generated)
    return generated
