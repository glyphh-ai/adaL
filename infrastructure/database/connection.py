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
