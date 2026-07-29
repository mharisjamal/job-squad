"""Dual-backend plumbing: URL normalization, dialect branch, PORT precedence.

Nothing here needs a live Postgres: create_async_engine does not connect.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.config import DEFAULT_PORT, Settings, resolve_port
from app.db import (
    POSTGRES_MAX_OVERFLOW,
    POSTGRES_POOL_SIZE,
    init_db,
    make_engine,
    make_sessionmaker,
    normalize_database_url,
)
from app.models import Company, Group, User

# The exact shape Neon hands out, pooled host included.
NEON_URL = (
    "postgresql://jobsquad_owner:npg_secret@ep-cool-name-123456-pooler"
    ".eu-central-1.aws.neon.tech/jobsquad?sslmode=require&channel_binding=require"
)


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------


def test_neon_url_is_converted_and_stripped():
    url, connect_args = normalize_database_url(NEON_URL)
    assert url == (
        "postgresql+asyncpg://jobsquad_owner:npg_secret@ep-cool-name-123456-pooler"
        ".eu-central-1.aws.neon.tech/jobsquad?prepared_statement_cache_size=0"
    )
    # asyncpg chokes on both of these, so neither may survive in the URL.
    assert "sslmode" not in url
    assert "channel_binding" not in url
    # TLS moves into connect_args, and asyncpg's own cache is off (PgBouncer).
    assert connect_args == {"statement_cache_size": 0, "ssl": True}


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
def test_all_postgres_schemes_normalize_to_asyncpg(scheme):
    url, _ = normalize_database_url(f"{scheme}://u:p@host:5432/db?sslmode=require")
    assert url == (
        "postgresql+asyncpg://u:p@host:5432/db?prepared_statement_cache_size=0"
    )


def test_driver_connect_args_are_clean():
    """What the driver layer actually receives from the URL: the SQLAlchemy
    cache switch (its adapter pops it) and none of Neon's rejected params."""
    engine = make_engine(database_url=NEON_URL)
    try:
        _, connect_kwargs = engine.dialect.create_connect_args(engine.url)
        assert connect_kwargs["prepared_statement_cache_size"] == 0
        assert "sslmode" not in connect_kwargs
        assert "channel_binding" not in connect_kwargs
        assert connect_kwargs["host"].endswith("aws.neon.tech")
    finally:
        engine.sync_engine.dispose()


@pytest.mark.parametrize("sslmode", ["require", "verify-ca", "verify-full"])
def test_ssl_enabled_for_secure_sslmodes(sslmode):
    _, connect_args = normalize_database_url(f"postgresql://u:p@h/db?sslmode={sslmode}")
    assert connect_args["ssl"] is True


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@h/db",
        "postgresql://u:p@h/db?sslmode=disable",
        "postgresql://u:p@h/db?sslmode=prefer",
    ],
)
def test_ssl_left_to_the_driver_otherwise(url):
    normalized, connect_args = normalize_database_url(url)
    assert "ssl" not in connect_args
    assert connect_args["statement_cache_size"] == 0
    assert "sslmode" not in normalized


def test_statement_cache_disabled_even_without_pooler_host():
    """Applied unconditionally: harmless direct, essential behind PgBouncer."""
    _, connect_args = normalize_database_url("postgresql://u:p@direct.neon.tech/db")
    assert connect_args["statement_cache_size"] == 0


def test_password_with_special_characters_survives():
    url, _ = normalize_database_url("postgresql://u:p%40ss%2Fword@h/db?sslmode=require")
    assert url.startswith("postgresql+asyncpg://u:p%40ss%2Fword@h/db")


def test_whitespace_is_trimmed():
    url, _ = normalize_database_url(f"  {NEON_URL}  ")
    assert url.startswith("postgresql+asyncpg://")


def test_non_postgres_url_passes_through():
    url, connect_args = normalize_database_url("sqlite+aiosqlite:///./x.db")
    assert url == "sqlite+aiosqlite:///./x.db"
    assert connect_args == {}


# ---------------------------------------------------------------------------
# Engine construction
# ---------------------------------------------------------------------------


def test_postgres_engine_is_built_with_pooling_settings():
    engine = make_engine(database_url=NEON_URL)
    try:
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "asyncpg"
        assert engine.pool.size() == POSTGRES_POOL_SIZE
        assert engine.pool._max_overflow == POSTGRES_MAX_OVERFLOW
        assert engine.pool._pre_ping is True
    finally:
        engine.sync_engine.dispose()


def test_sqlite_engine_when_no_database_url(tmp_path):
    engine = make_engine(tmp_path / "local.db")
    try:
        assert engine.dialect.name == "sqlite"
    finally:
        engine.sync_engine.dispose()


def test_make_engine_needs_one_of_the_two():
    with pytest.raises(ValueError):
        make_engine()


def test_settings_uses_database_url_when_present(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSQUAD_SECRET", "x")
    monkeypatch.setenv("DATABASE_URL", NEON_URL)
    assert Settings.load().database_url == NEON_URL
    monkeypatch.delenv("DATABASE_URL")
    assert Settings.load().database_url is None


# ---------------------------------------------------------------------------
# init_db dialect branch
# ---------------------------------------------------------------------------


async def test_init_db_runs_the_sqlite_migration(tmp_path):
    """SQLite still gets the WAL pragma and the hand-rolled migration."""
    engine = make_engine(tmp_path / "sqlite_branch.db")
    async with engine.begin() as conn:
        # A legacy users table (no email column, NOT NULL password_hash).
        await conn.execute(
            text(
                "CREATE TABLE users ("
                " id INTEGER NOT NULL PRIMARY KEY,"
                " username VARCHAR(30) NOT NULL UNIQUE,"
                " display_name TEXT NOT NULL,"
                " password_hash TEXT NOT NULL,"
                " created_at DATETIME)"
            )
        )

    await init_db(engine)

    async with engine.begin() as conn:
        info = {row[1]: row for row in (await conn.execute(text("PRAGMA table_info(users)"))).all()}
        assert "email" in info and "avatar_url" in info
        assert info["password_hash"][3] == 0  # migration ran
        mode = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
        assert mode.lower() == "wal"
    await engine.dispose()


class _FakeConnection:
    """Records what init_db does, so the dialect branch can be checked without
    a live database (a Postgres engine would have to connect for real)."""

    def __init__(self, log: list[str]):
        self._log = log

    async def run_sync(self, _fn):
        self._log.append("create_all")

    async def execute(self, statement):
        self._log.append(str(statement))


class _FakeEngine:
    def __init__(self, dialect_name: str):
        self.dialect = SimpleNamespace(name=dialect_name)
        self.log: list[str] = []

    def begin(self):
        log = self.log

        @asynccontextmanager
        async def _ctx():
            yield _FakeConnection(log)

        return _ctx()


@pytest.mark.parametrize(
    ("dialect", "expect_pragma", "expect_migration"),
    [("postgresql", False, False), ("sqlite", True, True)],
)
async def test_init_db_branches_on_dialect(
    monkeypatch, dialect, expect_pragma, expect_migration
):
    migrated: list[bool] = []

    async def _record_migrate(_engine):
        migrated.append(True)

    monkeypatch.setattr("app.db._migrate", _record_migrate)
    engine = _FakeEngine(dialect)

    await init_db(engine)

    assert "create_all" in engine.log  # both backends build the schema
    ran_pragma = any("PRAGMA" in statement.upper() for statement in engine.log)
    assert ran_pragma is expect_pragma
    assert bool(migrated) is expect_migration


async def test_tags_and_detail_round_trip_as_python_types(tmp_path):
    """The JSON/JSONB variant columns must behave identically on SQLite."""
    engine = make_engine(tmp_path / "json.db")
    await init_db(engine)
    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as session:
        user = User(username="haris", display_name="Haris", password_hash="x")
        session.add(user)
        await session.flush()
        group = Group(name="G", invite_code="ABCD2345", owner_id=user.id)
        session.add(group)
        await session.flush()
        session.add(
            Company(
                group_id=group.id,
                name="TechCorp",
                tags=["fintech", "remote"],
                created_by=user.id,
            )
        )
        await session.commit()

    async with sessionmaker() as session:
        company = await session.scalar(select(Company))
        assert company.tags == ["fintech", "remote"]
        assert isinstance(company.tags, list)
    await engine.dispose()


def test_jsonb_variant_is_used_for_postgres():
    from sqlalchemy.dialects import postgresql, sqlite

    from app.models import Company

    column = Company.__table__.c.tags.type
    assert "JSONB" in column.compile(dialect=postgresql.dialect()).upper()
    assert "JSON" in column.compile(dialect=sqlite.dialect()).upper()


# ---------------------------------------------------------------------------
# PORT precedence
# ---------------------------------------------------------------------------


def test_port_precedence(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("JOBSQUAD_PORT", raising=False)
    assert resolve_port() == DEFAULT_PORT

    monkeypatch.setenv("JOBSQUAD_PORT", "9001")
    assert resolve_port() == 9001

    # Render injects PORT and it must win.
    monkeypatch.setenv("PORT", "10000")
    assert resolve_port() == 10000

    # A junk PORT falls through to the next source rather than crashing boot.
    monkeypatch.setenv("PORT", "not-a-number")
    assert resolve_port() == 9001


def test_settings_port_follows_render_port(monkeypatch):
    monkeypatch.setenv("JOBSQUAD_SECRET", "x")
    monkeypatch.setenv("PORT", "10000")
    assert Settings.load().port == 10000
