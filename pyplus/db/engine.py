from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pyplus.config import settings

log = logging.getLogger(__name__)


def _db_url() -> str:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{settings.db_path}"


engine = create_async_engine(
    _db_url(),
    echo=False,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Run Alembic migrations to bring the schema to head."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    log.info("Running database migrations…")

    def _run_alembic() -> None:
        from alembic import command
        from alembic.config import Config

        cfg = Config()
        cfg.set_main_option(
            "script_location",
            str(Path(__file__).parent.parent.parent / "migrations"),
        )
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{settings.db_path}")
        command.upgrade(cfg, "head")

    # Alembic uses sync I/O; run in a thread pool to avoid blocking the event loop.
    await asyncio.get_running_loop().run_in_executor(None, _run_alembic)
    log.info("Database ready at %s", settings.db_path)
