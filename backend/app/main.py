"""FastAPI entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import auth as auth_routes
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

# CORS for the future Next.js frontend (added in Phase 8). Allow localhost dev origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)


@app.get("/health")
async def health():
    settings = get_settings()
    return {
        "status": "ok",
        "app_mode": settings.app_mode,
        "as_of_date": settings.as_of_date.isoformat() if settings.as_of_date else None,
    }
