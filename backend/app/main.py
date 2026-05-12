"""FastAPI entrypoint."""

# Load backend/.env BEFORE any other import — defends against shells that
# pre-set keys to empty strings (which would otherwise win over .env via
# pydantic-settings precedence).
from pathlib import Path  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

import logging  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

# App-wide logging at INFO. uvicorn configures its own loggers; this sets the
# `app.*` tree so freshness/sync/etc INFO lines actually surface.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("app").setLevel(logging.INFO)
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text, update
from starlette.middleware.base import BaseHTTPMiddleware

from app.agent import checkpointer as agent_checkpointer
from app.api.routes import admin as admin_routes
from app.api.routes import auth as auth_routes
from app.api.routes import chat as chat_routes
from app.api.routes import conversations as conversation_routes
from app.api.routes import team as team_routes
from app.config import get_settings
from app.db.engine import SessionLocal, engine
from app.db.models import User
from app.jobs import freshness
from app.security import COOKIE_NAME

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify DB reachable at startup. Fail fast if it isn't.
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    # LangGraph checkpointer (conversation memory). Must be started inside the
    # event loop, before any agent invocation — but tests sometimes skip it.
    await agent_checkpointer.start()
    freshness.start()
    try:
        yield
    finally:
        await freshness.stop()
        await agent_checkpointer.stop()
        await engine.dispose()


app = FastAPI(title="Fantasy Copilot v2", lifespan=lifespan)


# Debounce interval for last_seen_at writes — same user pinging us 100x/sec
# should not produce 100 UPDATEs.
_LAST_SEEN_DEBOUNCE = timedelta(seconds=60)
_last_seen_writes: dict[int, datetime] = {}


def _decode_user_id_quiet(token: str) -> int | None:
    """JWT decode that NEVER raises. A bad/expired cookie is just None."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        return int(payload["sub"])
    except Exception:
        return None


class LastSeenMiddleware(BaseHTTPMiddleware):
    """Stamp users.last_seen_at when an authenticated request comes in.

    Never blocks the request, never raises. Debounced in-memory.
    """

    async def dispatch(self, request: Request, call_next):
        token = request.cookies.get(COOKIE_NAME)
        user_id = _decode_user_id_quiet(token) if token else None
        if user_id is not None:
            now = datetime.now(timezone.utc)
            last = _last_seen_writes.get(user_id)
            if last is None or now - last > _LAST_SEEN_DEBOUNCE:
                _last_seen_writes[user_id] = now
                try:
                    async with SessionLocal() as session:
                        await session.execute(
                            update(User).where(User.id == user_id).values(last_seen_at=now)
                        )
                        await session.commit()
                except Exception:
                    log.exception("failed to update last_seen_at for user=%s", user_id)
        return await call_next(request)


# Order matters: middleware is applied in REVERSE registration order, so the
# LAST one registered is the OUTERMOST. We register LastSeen first (innermost)
# and CORS second (outermost) — CORS preflights short-circuit before LastSeen,
# so we never touch the DB for OPTIONS requests with no cookie.
app.add_middleware(LastSeenMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(admin_routes.router)
app.include_router(chat_routes.router)
app.include_router(conversation_routes.router)
app.include_router(team_routes.router)


@app.get("/health")
async def health():
    settings = get_settings()
    return {
        "status": "ok",
        "app_mode": settings.app_mode,
        "as_of_date": settings.as_of_date.isoformat() if settings.as_of_date else None,
    }
