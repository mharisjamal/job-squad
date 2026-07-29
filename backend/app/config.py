"""Environment-driven settings, read at create_app() time (not import time)."""

import os
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# .env support (stdlib only: no python-dotenv, no lockfile churn)
# ---------------------------------------------------------------------------


def parse_env_text(text: str) -> dict[str, str]:
    """Parse .env content. Malformed lines are skipped, never fatal.

    Splits on the first "=" so connection strings keep their query params,
    drops an optional "export " prefix, and unwraps matching quotes.
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def read_env_file(path: Path) -> dict[str, str]:
    """Values from one .env file; an unreadable or missing file yields {}."""
    try:
        return parse_env_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}


def apply_env_files(paths: Iterable[Path]) -> None:
    """Merge the given files (later wins) into os.environ without clobbering.

    A real environment variable always beats a file value, so Render's
    dashboard settings and CI stay authoritative over any stray local file.
    """
    merged: dict[str, str] = {}
    for path in paths:
        merged.update(read_env_file(path))
    for key, value in merged.items():
        os.environ.setdefault(key, value)


_ENV_FILES_LOADED = False


def default_env_files() -> tuple[Path, Path]:
    return REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"


def load_env_files(force: bool = False) -> None:
    """Load the repo's .env files once per process, before settings are read."""
    global _ENV_FILES_LOADED
    if _ENV_FILES_LOADED and not force:
        return
    _ENV_FILES_LOADED = True
    apply_env_files(default_env_files())


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_str(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


DEFAULT_PORT = 8100


def resolve_port() -> int:
    """PORT (injected by Render) wins, then JOBSQUAD_PORT, then the default."""
    for name in ("PORT", "JOBSQUAD_PORT"):
        raw = os.environ.get(name, "").strip()
        if raw:
            try:
                return int(raw)
            except ValueError:
                continue
    return DEFAULT_PORT


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    db_path: Path
    secret: str
    token_ttl_hours: int
    port: int
    # Set on hosted deployments (Render + Neon). Unset means local SQLite.
    database_url: str | None = None
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
        load_env_files()
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
            port=resolve_port(),
            database_url=_env_str("DATABASE_URL"),
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
