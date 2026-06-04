"""Pytest fixtures for the backend test suite.

Two execution modes:

1. **Pure-unit mode (default)** — no Postgres needed. Tests that exercise
   pure-Python services (valuators, clock, league-rule extraction, helpers)
   should NOT depend on `db_session`. They run in CI without docker.

2. **DB-integration mode** — opt-in by depending on the `db_session`
   fixture. Spins up against a separate `fantasy_copilot_test` database
   on the same Postgres container. Each test runs inside a SAVEPOINT that
   is rolled back at teardown, so tests are isolated and fast.

The test DB URL is taken from `TEST_DATABASE_URL` if set, otherwise
defaults to the local docker Postgres with database name
`fantasy_copilot_test`. The dev DB (`fantasy_copilot`) is never touched.

Engineer note: this conftest deliberately does NOT import `app.db.engine`
at module load time, because that file calls `get_settings()` which reads
`.env` and fails if e.g. `JWT_SECRET` is missing in the CI environment.
We set os.environ defaults BEFORE any app import.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

# Environment defaults — set BEFORE any `app.*` import so `get_settings()`
# (called at module load in app.db.engine) has the values it needs. CI
# can override any of these via real env vars.
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("YAHOO_CLIENT_ID", "test-client-id")
os.environ.setdefault("YAHOO_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("ADMIN_SECRET", "test-admin-secret")
os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://fantasy:fantasy_dev_password@localhost:5432/fantasy_copilot_test",
)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Resolved test database URL. Override via `TEST_DATABASE_URL` env var."""
    return os.environ["TEST_DATABASE_URL"]


@pytest_asyncio.fixture(scope="session")
async def _test_engine(test_database_url: str):
    """Session-scoped async engine bound to the test DB.

    Creates the schema once for the session via Base.metadata.create_all,
    then drops it at the end. We don't run Alembic migrations in tests —
    too slow and they're integration-tested by the smoke flow.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db.models import Base

    engine = create_async_engine(test_database_url, echo=False, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(_test_engine) -> AsyncIterator:
    """Function-scoped session inside a SAVEPOINT that is rolled back.

    Pattern from SQLAlchemy docs ("Joining a Session into an External
    Transaction"). Each test gets a clean slate without paying the cost
    of recreating the schema.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    async with _test_engine.connect() as conn:
        trans = await conn.begin()
        async_session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield async_session
        finally:
            await async_session.close()
            await trans.rollback()
