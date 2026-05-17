"""Centralised configuration. Reads from backend/.env. Never hard-code secrets.

We call load_dotenv(override=True) at module import — BEFORE pydantic-settings
constructs Settings — so that backend/.env wins over any (possibly empty)
shell environment variables. This is critical: a parent shell with
ANTHROPIC_API_KEY="" or JWT_SECRET="" would otherwise silently override
the real values in .env, breaking the agent and JWT auth.
"""

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/.env is two parents up from this file (backend/app/config.py).
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Database
    database_url: str = Field(
        default="postgresql+asyncpg://fantasy:fantasy_dev_password@localhost:5432/fantasy_copilot"
    )

    # --- App mode
    app_mode: Literal["live", "replay"] = "replay"
    as_of_date: date | None = None

    # --- Yahoo OAuth (Phase 2)
    yahoo_client_id: str = ""
    yahoo_client_secret: str = ""
    yahoo_redirect_uri: str = ""

    # --- Anthropic / Agent (Phase 4)
    anthropic_api_key: str = ""

    # --- LangSmith (Phase 4)
    langsmith_api_key: str = ""
    langsmith_tracing: bool = False
    langsmith_project: str = "fantasy-copilot-v2"

    # --- Tavily (Phase 7.5 — web search for news/status)
    tavily_api_key: str = ""

    # --- JWT
    jwt_secret: str = "dev-only-secret-replace-in-env"
    jwt_algorithm: str = "HS256"
    cookie_domain: str = "localhost"
    cookie_secure: bool = False

    # --- Admin endpoints
    admin_secret: str = ""

    # Comma-separated User.id values that may hit /api/admin/* via cookie auth.
    # Empty = no one is admin via cookie (X-Admin-Secret routes still work).
    # We use User.id rather than email because we don't currently capture
    # email from Yahoo; revisit when we add an email field for public launch.
    admin_user_ids: str = ""

    @property
    def admin_user_id_set(self) -> set[int]:
        out: set[int] = set()
        for chunk in (self.admin_user_ids or "").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                out.add(int(chunk))
            except ValueError:
                continue
        return out


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor. Always import this; never instantiate Settings directly."""
    return Settings()
