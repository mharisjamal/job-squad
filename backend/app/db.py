"""Async SQLite engine/session factory and schema initialization."""

from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base


def make_engine(db_path: Path) -> AsyncEngine:
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("PRAGMA journal_mode=WAL"))
    await _migrate(engine)


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
        if not rows:
            return
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
