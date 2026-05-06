"""Centralised configuration. Reads from backend/.env. Never hard-code secrets."""

from datetime import date
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor. Always import this; never instantiate Settings directly."""
    return Settings()
