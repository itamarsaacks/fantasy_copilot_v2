"""SQLAlchemy ORM models — full schema.

Conventions:
- All times are TIMESTAMPTZ (Postgres timezone-aware).
- Big variable structures live in JSONB columns.
- Every concrete table has created_at / updated_at where it makes sense.
- Soft delete only on user-facing entities (User, League). Sync data is hard-delete.
- LangGraph owns the conversations table — it is NOT defined here.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Users + Leagues (Phase 2)
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    yahoo_guid: Mapped[str] = mapped_column(String, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)

    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    token_expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))

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
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    leagues: Mapped[list["League"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class League(Base):
    __tablename__ = "leagues"
    __table_args__ = (UniqueConstraint("user_id", "league_key", name="uq_user_league"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    league_key: Mapped[str] = mapped_column(String, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Yahoo raw values: point, headpoint, head, roto
    scoring_type: Mapped[str] = mapped_column(String, nullable=False)
    num_teams: Mapped[int] = mapped_column(Integer, nullable=False)
    current_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    season: Mapped[str] = mapped_column(String, nullable=False)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

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
    teams: Mapped[list["Team"]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Fantasy teams + rosters + FAs (Phase 3)
# ---------------------------------------------------------------------------


class Team(Base):
    """A fantasy team in a league."""

    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("league_id", "team_key", name="uq_league_team"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(
        ForeignKey("leagues.id", ondelete="CASCADE"), index=True, nullable=False
    )
    team_key: Mapped[str] = mapped_column(String, index=True, nullable=False)
    team_id_in_league: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    manager_name: Mapped[str | None] = mapped_column(String, nullable=True)
    manager_id: Mapped[str | None] = mapped_column(String, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    is_user_team: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Standings — h2h leagues use W/L/T; points leagues use points_for/against.
    wins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    losses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ties: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    points_for: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    points_against: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    clinched_playoffs: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    division_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Waiver / FAAB economics
    faab_balance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    waiver_priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    number_of_moves: Mapped[int | None] = mapped_column(Integer, nullable=True)
    number_of_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)

    draft_grade: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    league: Mapped[League] = relationship(back_populates="teams")
    roster_entries: Mapped[list["RosterPlayer"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class Player(Base):
    """NBA player identity. Shared across all leagues."""

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    yahoo_player_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    yahoo_player_id: Mapped[int] = mapped_column(Integer, index=True)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # Multi-valued: a player might be PG, SG. Stored as a list in JSONB.
    eligible_positions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    primary_position: Mapped[str | None] = mapped_column(String, nullable=True)

    nba_team_abbr: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)  # IL, GTD, OUT, ...
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    uniform_number: Mapped[str | None] = mapped_column(String, nullable=True)

    # Yahoo-global ownership signals (latest known value at last sync).
    percent_owned: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    percent_owned_delta: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    percent_started: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Draft-analysis (Yahoo-global, set during preseason; informative for trades).
    draft_avg_pick: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    draft_avg_round: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    draft_avg_cost: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    draft_percent_drafted: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RosterPlayer(Base):
    """A player currently on a fantasy team's roster (latest snapshot)."""

    __tablename__ = "roster_players"
    __table_args__ = (UniqueConstraint("team_id", "player_id", name="uq_team_player"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True, nullable=False
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True, nullable=False
    )
    selected_position: Mapped[str | None] = mapped_column(String, nullable=True)  # PG, BN, IL, ...

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    team: Mapped[Team] = relationship(back_populates="roster_entries")


class FreeAgent(Base):
    """Players currently unowned in a league (latest snapshot)."""

    __tablename__ = "free_agents"
    __table_args__ = (UniqueConstraint("league_id", "player_id", name="uq_league_fa"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(
        ForeignKey("leagues.id", ondelete="CASCADE"), index=True, nullable=False
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Yahoo distinguishes: A=available, FA=free agent, W=on waivers
    waiver_status: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Stats / schedule / news / trades — schema only, populated in later phases
# ---------------------------------------------------------------------------


class PlayerStats(Base):
    """Yahoo-sourced stat snapshots. Append-only, time-series.

    Scope: which window the stats cover (season, last_7, last_14, last_30).
    """

    __tablename__ = "player_stats"
    __table_args__ = (
        UniqueConstraint(
            "player_id", "league_key", "scope", "stat_id", "as_of_date", name="uq_player_stat_snap"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True, nullable=False
    )
    league_key: Mapped[str] = mapped_column(String, index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False)  # season, last_7, last_14, last_30
    stat_id: Mapped[str] = mapped_column(String, nullable=False)  # PTS, REB, AST, ...
    value: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class NbaGameLog(Base):
    """Per-player per-game stat lines."""

    __tablename__ = "nba_game_logs"
    __table_args__ = (UniqueConstraint("player_id", "game_id", name="uq_player_game"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True, nullable=False
    )
    game_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    game_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    opponent_abbr: Mapped[str | None] = mapped_column(String, nullable=True)
    is_home: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    minutes: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # The full boxscore lives in JSONB so we don't have to migrate every time
    # we want a new stat line column.
    box: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class NbaSchedule(Base):
    """The NBA game schedule."""

    __tablename__ = "nba_schedule"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    game_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    home_team_abbr: Mapped[str] = mapped_column(String, nullable=False)
    away_team_abbr: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # scheduled, live, final
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class NewsItem(Base):
    """Injury / roster / status news for NBA players."""

    __tablename__ = "news_items"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_news_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    player_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL"), index=True, nullable=True
    )
    nba_team_abbr: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # injury, GTD, OUT, return, ...
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)  # 0.000 - 1.000
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class Trade(Base):
    """Trades within a league."""

    __tablename__ = "trades"
    __table_args__ = (UniqueConstraint("league_id", "trade_key", name="uq_league_trade"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(
        ForeignKey("leagues.id", ondelete="CASCADE"), index=True, nullable=False
    )
    trade_key: Mapped[str] = mapped_column(String, nullable=False)
    proposer_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    accepter_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    proposed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    # players_offered / players_received: list of player_keys per side
    players_offered: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    players_received: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Projections — cache (current) + history (daily snapshot)
# ---------------------------------------------------------------------------


class ProjectionCache(Base):
    """Current projection per (player, league, horizon). Overwritten on invalidation.

    `stale=true` means inputs changed and the row needs recompute. Background
    worker drains stale rows.
    """

    __tablename__ = "projection_cache"
    __table_args__ = (
        UniqueConstraint(
            "player_id", "league_id", "horizon", name="uq_projection_cache_unique"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True, nullable=False
    )
    league_id: Mapped[int] = mapped_column(
        ForeignKey("leagues.id", ondelete="CASCADE"), index=True, nullable=False
    )
    horizon: Mapped[str] = mapped_column(
        String, nullable=False
    )  # next_7_days, this_week, rest_of_season
    projected_value: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    stale: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    computed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProjectionHistory(Base):
    """Daily snapshot of projections for trend analytics."""

    __tablename__ = "projection_history"
    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "league_id",
            "horizon",
            "snapshot_date",
            name="uq_projection_history_unique",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True, nullable=False
    )
    league_id: Mapped[int] = mapped_column(
        ForeignKey("leagues.id", ondelete="CASCADE"), index=True, nullable=False
    )
    horizon: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    projected_value: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
