"""Database engine/session factory and schema initialization.

Two backends: local SQLite (the zero-configuration default) and Postgres when
DATABASE_URL is set (Render + Neon). Everything SQLite-specific (the PRAGMAs
and the hand-rolled migration) is branched on the dialect.
"""

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base

# Render's free instance has 512 MB, and Neon's free tier is connection-frugal.
POSTGRES_POOL_SIZE = 5
POSTGRES_MAX_OVERFLOW = 5
_SSL_REQUIRED_MODES = ("require", "verify-ca", "verify-full")


def normalize_database_url(raw: str) -> tuple[str, dict]:
    """Turn a hosted Postgres URL into an asyncpg URL plus connect_args.

    Neon and Render hand out URLs like
    postgresql://u:p@host/db?sslmode=require&channel_binding=require
    asyncpg understands neither query parameter and raises on them, so every
    parameter is stripped and TLS is passed through connect_args instead.

    Also disables prepared statement caching on both layers: Neon's "-pooler"
    host is PgBouncer in transaction mode, where cached prepared statements
    break. asyncpg's own cache is turned off through connect_args, and
    SQLAlchemy's wrapper cache through the one query parameter it consumes
    itself (prepared_statement_cache_size never reaches asyncpg). Applied to
    every Postgres URL: harmless on a direct connection, impossible to forget
    when the host later moves behind the pooler.
    """
    parts = urlsplit(raw.strip())
    scheme = parts.scheme.lower()
    if scheme in ("postgres", "postgresql") or scheme.startswith("postgresql+"):
        sslmode = ""
        for chunk in parts.query.split("&"):
            key, _, value = chunk.partition("=")
            if key.strip().lower() == "sslmode":
                sslmode = value.strip().lower()
        url = urlunsplit(
            (
                "postgresql+asyncpg",
                parts.netloc,
                parts.path,
                "prepared_statement_cache_size=0",
                "",
            )
        )
        connect_args: dict = {"statement_cache_size": 0}
        if sslmode in _SSL_REQUIRED_MODES:
            connect_args["ssl"] = True
        return url, connect_args
    # Anything else (a full SQLAlchemy URL, say) is passed through untouched.
    return raw.strip(), {}


def make_engine(db_path: Path | None = None, database_url: str | None = None) -> AsyncEngine:
    """Postgres when database_url is given, else local SQLite at db_path."""
    if database_url:
        url, connect_args = normalize_database_url(database_url)
        return create_async_engine(
            url,
            echo=False,
            connect_args=connect_args,
            pool_pre_ping=True,
            pool_size=POSTGRES_POOL_SIZE,
            max_overflow=POSTGRES_MAX_OVERFLOW,
        )

    if db_path is None:
        raise ValueError("make_engine needs either db_path or database_url")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    dialect = engine.dialect.name
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if dialect == "sqlite":
            await conn.execute(text("PRAGMA journal_mode=WAL"))
        if dialect == "postgresql":
            await _migrate_postgres(conn)
    if dialect == "sqlite":
        # The hand-rolled PRAGMA-based migration is SQLite-only.
        await _migrate(engine)


async def _migrate_postgres(conn) -> None:
    """Idempotent column top-ups for the hosted Postgres database (Render + Neon).

    create_all adds missing TABLES (resumes) but never adds COLUMNS to a table
    that already exists, and this project deliberately has no Alembic. Both
    statements are IF NOT EXISTS, so every boot may run them against the live
    database with real data and change nothing after the first time. The FK
    rides on the ALTER itself: when the column already exists the whole
    statement is skipped, so the constraint can never be added twice.
    """
    await conn.execute(
        text(
            "ALTER TABLE applications ADD COLUMN IF NOT EXISTS resume_id BIGINT"
            " REFERENCES resumes(id) ON DELETE SET NULL"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_applications_resume_id"
            " ON applications (resume_id)"
        )
    )


async def _migrate(engine: AsyncEngine) -> None:
    """Idempotent schema top-ups for databases created before a column existed.

    create_all adds missing TABLES but never missing COLUMNS, and this project
    deliberately has no Alembic. Runs in AUTOCOMMIT because the table rebuild
    below has to toggle the foreign_keys pragma, which SQLite ignores inside a
    transaction. Safe to run repeatedly and on a fresh database.
    """
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        rows = (await conn.execute(text("PRAGMA table_info(users)"))).all()
        if rows:
            columns = {row[1] for row in rows}
            if "email" not in columns:
                await conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(320)"))
            if "avatar_url" not in columns:
                await conn.execute(text("ALTER TABLE users ADD COLUMN avatar_url TEXT"))
            # Column 3 of PRAGMA table_info is "notnull": an older schema still
            # marks password_hash NOT NULL, which social accounts cannot satisfy.
            if any(row[1] == "password_hash" and row[3] for row in rows):
                await _rebuild_users_table(conn)
            await conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)")
            )
        app_rows = (await conn.execute(text("PRAGMA table_info(applications)"))).all()
        if app_rows:
            app_columns = {row[1] for row in app_rows}
            if "resume_id" not in app_columns:
                # ADD COLUMN with a REFERENCES clause is legal in SQLite as
                # long as the default is NULL (it is). Existing rows keep
                # their data and get resume_id NULL.
                await conn.execute(
                    text(
                        "ALTER TABLE applications ADD COLUMN resume_id BIGINT"
                        " REFERENCES resumes(id) ON DELETE SET NULL"
                    )
                )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_applications_resume_id"
                    " ON applications (resume_id)"
                )
            )


async def _rebuild_users_table(conn) -> None:
    """Standard SQLite table rebuild to make password_hash nullable.

    The documented SQLite procedure: foreign_keys OFF, rebuild inside one
    transaction, foreign_keys back ON. Dropping users would otherwise trip the
    child tables that reference it, even though the rebuilt table restores
    every id moments later. Ids and rows are preserved.
    """
    await conn.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        await conn.execute(text("BEGIN"))
        await _rebuild_users_statements(conn)
        await conn.execute(text("COMMIT"))
    except Exception:
        await conn.execute(text("ROLLBACK"))
        raise
    finally:
        await conn.execute(text("PRAGMA foreign_keys=ON"))


async def _rebuild_users_statements(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS ix_users_email"))
    await conn.execute(
        text(
            "CREATE TABLE users_migration_new ("
            " id INTEGER NOT NULL PRIMARY KEY,"
            " username VARCHAR(30) NOT NULL,"
            " display_name TEXT NOT NULL,"
            " password_hash TEXT,"
            " email VARCHAR(320),"
            " avatar_url TEXT,"
            " created_at DATETIME,"
            " UNIQUE (username))"
        )
    )
    await conn.execute(
        text(
            "INSERT INTO users_migration_new"
            " (id, username, display_name, password_hash, email, avatar_url, created_at)"
            " SELECT id, username, display_name, password_hash, email, avatar_url, created_at"
            " FROM users"
        )
    )
    await conn.execute(text("DROP TABLE users"))
    await conn.execute(text("ALTER TABLE users_migration_new RENAME TO users"))
