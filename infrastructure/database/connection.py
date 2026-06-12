"""
Database connection management with async SQLAlchemy.
SQLite by default; Postgres when DATABASE_URL points at one.
"""

import logging
import subprocess
from typing import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from infrastructure.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Resolve and normalise the database URL
database_url = settings.resolved_database_url
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
# asyncpg uses "ssl" not "sslmode"
database_url = database_url.replace("sslmode=", "ssl=")

# SQLite does not support connection pooling — use different engine args
_is_sqlite = "sqlite" in database_url

if _is_sqlite:
    # Set per-connection PRAGMAs via sqlite3's init_command equivalent.
    # aiosqlite passes connect_args through to sqlite3.connect().
    # timeout=5 sets the busy timeout to 5 seconds (same as PRAGMA busy_timeout=5000).
    engine = create_async_engine(
        database_url,
        echo=settings.log_level == "DEBUG",
        connect_args={"timeout": 30},  # 30s busy timeout for concurrent writes
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA busy_timeout = 30000")  # 30s in ms
        cursor.execute("PRAGMA synchronous = NORMAL")  # faster writes, still safe with WAL
        cursor.close()
else:
    engine = create_async_engine(
        database_url,
        echo=settings.log_level == "DEBUG",
        pool_size=20,
        max_overflow=40,
        pool_pre_ping=True,
        pool_recycle=3600,
    )

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Base class for models
Base = declarative_base()


async def init_db() -> None:
    """Initialize database and run migrations.

    For Postgres backends: runs Alembic migrations.
    For SQLite backends: skips Alembic entirely, uses create_all() directly.
    """
    import os

    # ── SQLite: set pragmas and create tables directly, skip Alembic ──────────
    if _is_sqlite:
        from domains.models.db_models import Token, AdaThought, FactSlot  # noqa: F401
        async with engine.begin() as conn:
            # WAL mode persists on the database file — only needs to be set once
            # but is safe to re-run. Enables concurrent readers + single writer.
            await conn.execute(text("PRAGMA journal_mode = WAL"))
            await conn.execute(text("PRAGMA busy_timeout = 5000"))
            await conn.execute(text("PRAGMA foreign_keys = ON"))
            await conn.run_sync(Base.metadata.create_all)
            await _sqlite_upgrade(conn)
        logger.info("SQLite: database tables created, WAL mode enabled")
        return

    # ── Postgres: run Alembic migrations ─────────────────────────────────────
    import sys as _sys

    app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    alembic_ini = os.path.join(app_root, "alembic.ini")

    migrations_applied = False

    if os.path.exists(alembic_ini):
        try:
            result = subprocess.run(
                [_sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=app_root,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                logger.info("Database migrations applied successfully")
                migrations_applied = True
            else:
                logger.error(f"Migration failed (rc={result.returncode}): {result.stderr}")
        except Exception as e:
            logger.error(f"Failed to run migrations: {e}")
    else:
        logger.warning(f"alembic.ini not found at {alembic_ini}")

    # Fallback: create tables directly if migrations didn't run
    if not migrations_applied:
        logger.info("Falling back to Base.metadata.create_all()")
        from domains.models.db_models import Token, AdaThought, FactSlot  # noqa: F401
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created via metadata.create_all()")
        except Exception as e:
            logger.error(f"Failed to create tables via metadata.create_all(): {e}")


async def _sqlite_upgrade(conn) -> None:
    """Lightweight in-place upgrades for existing SQLite databases.
    create_all only creates NEW tables — columns added to existing
    tables (e.g. ada_thoughts.space_id, migration 0002) must be ALTERed
    here. Idempotent."""
    cols = [row[1] for row in
            (await conn.execute(text("PRAGMA table_info(ada_thoughts)"))).all()]
    if cols and "space_id" not in cols:
        await conn.execute(text(
            "ALTER TABLE ada_thoughts ADD COLUMN space_id VARCHAR(64) "
            "NOT NULL DEFAULT 'main'"))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ada_thoughts_space_id "
            "ON ada_thoughts (space_id)"))
        logger.info("SQLite upgrade: added ada_thoughts.space_id")

    # Backfill fact_slots from existing thoughts' metadata when the
    # slots table is empty but thoughts exist (pre-0002 databases).
    n_slots = (await conn.execute(
        text("SELECT COUNT(*) FROM fact_slots"))).scalar() or 0
    n_thoughts = (await conn.execute(
        text("SELECT COUNT(*) FROM ada_thoughts WHERE archived = 0"))).scalar() or 0
    if n_slots == 0 and n_thoughts > 0:
        import json as _json
        from ada.memory.thought_persistence import slot_rows
        from ada.memory.thought_space import StoredThought
        rows = (await conn.execute(text(
            "SELECT thought_id, space_id, content, speaker, extra_data "
            "FROM ada_thoughts WHERE archived = 0"))).all()
        inserted = 0
        for tid, space_id, content, speaker, extra in rows:
            meta = extra if isinstance(extra, dict) else _json.loads(extra or "{}")
            stored = StoredThought(thought_id=tid, content=content,
                                   speaker=speaker, space_id=space_id or "main",
                                   metadata=meta or {})
            for sr in slot_rows(stored):
                await conn.execute(text(
                    "INSERT INTO fact_slots (space_id,thought_id,entity,layer,"
                    "role,value,predicate,key,version,is_current) VALUES "
                    "(:space_id,:thought_id,:entity,:layer,:role,:value,"
                    ":predicate,:key,:version,:is_current)"), sr)
                inserted += 1
        # supersede old versions
        await conn.execute(text(
            "UPDATE fact_slots SET is_current=0 WHERE key IS NOT NULL AND "
            "version < (SELECT MAX(version) FROM fact_slots f2 "
            "WHERE f2.key = fact_slots.key AND f2.space_id = fact_slots.space_id)"))
        logger.info(f"SQLite upgrade: backfilled {inserted} fact_slots rows "
                    f"from {n_thoughts} existing thoughts")


async def close_db() -> None:
    """Close database connections"""
    await engine.dispose()
    logger.info("Database connections closed")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting database session"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
