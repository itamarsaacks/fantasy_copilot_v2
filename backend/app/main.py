"""FastAPI entrypoint. Phase 1: just a /health route. Real routes land in later phases."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.config import get_settings
from app.db.engine import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify DB reachable at startup. Fail fast if it isn't.
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    yield
    await engine.dispose()


app = FastAPI(title="Fantasy Copilot v2", lifespan=lifespan)


@app.get("/health")
async def health():
    settings = get_settings()
    return {
        "status": "ok",
        "app_mode": settings.app_mode,
        "as_of_date": settings.as_of_date.isoformat() if settings.as_of_date else None,
    }
