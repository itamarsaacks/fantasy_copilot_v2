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


async def _ensure_test_database_exists(test_database_url: str) -> None:
    """Create the test database if it doesn't exist.

    Tests target a separate DB so they can never corrupt dev data. The
    docker compose only creates `fantasy_copilot`; this bootstraps the
    `fantasy_copilot_test` companion DB on first run.
    """
    import re

    from sqlalchemy.ext.asyncio import create_async_engine

    m = re.match(r"^(.*)/([^/]+)$", test_database_url)
    if not m:
        raise RuntimeError(f"Cannot parse test_database_url: {test_database_url!r}")
    server_url, dbname = m.group(1), m.group(2)
    # Connect to the postgres maintenance DB to issue CREATE DATABASE.
    admin_engine = create_async_engine(
        f"{server_url}/postgres",
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        async with admin_engine.connect() as conn:
            from sqlalchemy import text

            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": dbname}
            )
            if not exists:
                # Identifier must be quoted; we control the value so this is safe.
                await conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    finally:
        await admin_engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def _test_engine(test_database_url: str):
    """Session-scoped async engine bound to the test DB.

    Creates the test database if missing, then builds the schema via
    Base.metadata.create_all. We don't run Alembic migrations in tests —
    too slow, and they're integration-tested by the smoke flow.

    The schema is left in place between sessions so subsequent test runs
    start instantly. The transactional `db_session` fixture rolls back
    every test's writes anyway, so the DB stays clean.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db.models import Base

    await _ensure_test_database_exists(test_database_url)
    engine = create_async_engine(test_database_url, echo=False, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
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
