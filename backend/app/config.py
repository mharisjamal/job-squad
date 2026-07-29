"""Environment-driven settings, read at create_app() time (not import time)."""

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    db_path: Path
    secret: str
    token_ttl_hours: int
    port: int

    @classmethod
    def load(cls) -> "Settings":
        db_raw = os.environ.get("JOBSQUAD_DB_PATH", "data/jobsquad.db")
        db_path = Path(db_raw)
        if not db_path.is_absolute():
            db_path = REPO_ROOT / db_path
        secret = os.environ.get("JOBSQUAD_SECRET", "").strip()
        if not secret:
            secret = _load_or_create_secret(REPO_ROOT / "data" / ".secret")
        return cls(
            repo_root=REPO_ROOT,
            db_path=db_path,
            secret=secret,
            token_ttl_hours=int(os.environ.get("JOBSQUAD_TOKEN_TTL_HOURS", "168")),
            port=int(os.environ.get("JOBSQUAD_PORT", "8100")),
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
