"""LangGraph PostgresSaver — owns conversation memory.

Singleton lifecycle: started in app.main lifespan. The agent module pulls
the live saver via get_checkpointer() at invocation time (NOT at module
import) because the saver requires an active asyncio event loop.

Each /api/chat call invokes the agent with config:
  {"configurable": {"thread_id": "<uuid>", "user_id": ..., "league_id": ...}}
LangGraph automatically:
  - loads the prior message state for that thread_id
  - appends new messages
  - persists the updated state
"""

from __future__ import annotations

import logging
from typing import Optional

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from app.config import get_settings

log = logging.getLogger(__name__)

_pool: Optional[AsyncConnectionPool] = None
_saver: Optional[AsyncPostgresSaver] = None


def _to_psycopg_dsn(database_url: str) -> str:
    """Convert SQLAlchemy-style URL to plain psycopg DSN.

    SQLAlchemy: postgresql+asyncpg://user:pwd@host/db
    psycopg:    postgresql://user:pwd@host/db
    """
    return database_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


async def start() -> None:
    """Create the connection pool + saver. Called from app lifespan startup."""
    global _pool, _saver
    if _saver is not None:
        return

    settings = get_settings()
    dsn = _to_psycopg_dsn(settings.database_url)

    _pool = AsyncConnectionPool(
        conninfo=dsn,
        max_size=10,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    await _pool.open()

    _saver = AsyncPostgresSaver(_pool)
    # First-run idempotent setup of the langgraph checkpoint tables.
    await _saver.setup()

    log.info("langgraph PostgresSaver ready")


async def stop() -> None:
    """Tear down on shutdown."""
    global _pool, _saver
    _saver = None
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_checkpointer() -> AsyncPostgresSaver:
    """Return the live checkpointer. Raises if start() hasn't run yet."""
    if _saver is None:
        raise RuntimeError(
            "checkpointer not initialized — make sure app.main lifespan is running"
        )
    return _saver
