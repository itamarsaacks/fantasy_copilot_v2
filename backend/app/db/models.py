"""SQLAlchemy ORM models. Phase 2: users + leagues. More tables land in Phase 3."""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class User(Base):
    """A Yahoo-authenticated user of our app."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    yahoo_guid: Mapped[str] = mapped_column(String, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # Yahoo OAuth tokens. Plaintext for now — encrypt at rest in a later phase.
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    token_expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))

    # True when refresh fails — UI shows reconnect banner.
    auth_broken: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # Soft delete — preserves history for analytics.
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    leagues: Mapped[list["League"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class League(Base):
    """A Yahoo Fantasy NBA league the user belongs to."""

    __tablename__ = "leagues"
    __table_args__ = (UniqueConstraint("user_id", "league_key", name="uq_user_league"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    league_key: Mapped[str] = mapped_column(String, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # roto, head2head_points, head2head_categories
    scoring_type: Mapped[str] = mapped_column(String, nullable=False)
    num_teams: Mapped[int] = mapped_column(Integer, nullable=False)
    current_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    season: Mapped[str] = mapped_column(String, nullable=False)
    # Full Yahoo settings blob — stat_categories, stat_modifiers, roster_positions, etc.
    settings_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="leagues")
