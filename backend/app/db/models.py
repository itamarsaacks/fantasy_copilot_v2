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

    # Phase 7: stamped by middleware on every authenticated request. The
    # freshness controller treats users seen within the last ~10 min as active.
    last_seen_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True, index=True
    )

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
    # Yahoo's longer description ("Day-To-Day", "Out", "Doubtful")
    status_full: Mapped[str | None] = mapped_column(String, nullable=True)
    # Free-text injury notes from Yahoo ("Knee — expected back this week")
    injury_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    uniform_number: Mapped[str | None] = mapped_column(String, nullable=True)

    # ESPN player ID — populated by backfill_espn_player_ids.py (master plan §2.1).
    # Used to (a) source headshots from ESPN's roster endpoint and (b) link
    # to ESPN player pages in the UI. We map Yahoo → ESPN by
    # (normalized_name, nba_team_abbr) matching; confidence records how the
    # match was found. Nullable because some rookies / two-way players won't
    # match cleanly; the nightly reconcile retries unmatched rows.
    espn_player_id: Mapped[int | None] = mapped_column(
        Integer, unique=True, nullable=True, index=True
    )
    espn_player_id_confidence: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # 'exact' | 'fuzzy' | 'manual' | NULL
    # Relative path under frontend/public/headshots/, e.g. "lebron-james-1966.webp".
    # NULL = no headshot downloaded yet; frontend falls back to colored initials.
    # Pre-downloaded by scripts/download_headshots.py and committed to the
    # repo so the app has zero runtime third-party headshot dependency.
    headshot_path: Mapped[str | None] = mapped_column(String, nullable=True)

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
    # True = player was on the active list but did not play (or had a 0/0/0
    # line); written as a placeholder by sync_game_logs so a subsequent date
    # query doesn't re-fetch from Yahoo every time.
    did_not_play: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # 'yahoo' (normal nightly sync) | 'backfill' (one-shot backfill script).
    # Lets us distinguish backfill data from production sync if we ever need
    # to wipe and re-pull.
    source: Mapped[str] = mapped_column(
        String, nullable=False, default="yahoo", server_default="yahoo"
    )

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class NbaSchedule(Base):
    """The NBA game schedule."""

    __tablename__ = "nba_schedule"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    game_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    tipoff_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
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
# Player ownership history — derived from Yahoo transactions, used to
# answer "how did this player get to my team / when did I lose him."
# ---------------------------------------------------------------------------


class PlayerOwnershipEvent(Base):
    """A single ownership change for a player in a league.

    Walking these events ordered by occurred_at lets the UI reconstruct
    the full timeline ("was on team X, traded to team Y, dropped, picked
    up by free-agent claim by team Z, ...").

    Source = NULL means the player was a free agent before the event
    (added from FA). Dest = NULL means the player became a free agent
    (drop). transaction_key dedupes against Yahoo so re-running the
    sync is idempotent.
    """

    __tablename__ = "player_ownership_events"
    __table_args__ = (
        UniqueConstraint(
            "league_id",
            "player_id",
            "transaction_key",
            name="uq_pownerevt_unique",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(
        ForeignKey("leagues.id", ondelete="CASCADE"), index=True, nullable=False
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True, nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # add | drop | trade
    from_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    to_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    transaction_key: Mapped[str] = mapped_column(String, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
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


# ---------------------------------------------------------------------------
# Chat conversations (Phase 8.6)
# LangGraph manages its own checkpoint tables (created via PostgresSaver.setup);
# this table holds APP-level metadata: which user/league a thread belongs to,
# its title, when it was last touched, soft-delete state.
# ---------------------------------------------------------------------------


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("thread_id", name="uq_conversation_thread"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    league_id: Mapped[int] = mapped_column(
        ForeignKey("leagues.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The langgraph thread_id (uuid). Bridges this row to LangGraph checkpoints.
    thread_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False, default="New chat")
    last_message_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True, index=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
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
# Eval harness (Phase E2) — see docs/EVAL_HARNESS.md §7
# ---------------------------------------------------------------------------


class EvalRun(Base):
    """One harness invocation. Aggregates every PhrasingRun from that run."""

    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    git_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    git_branch: Mapped[str | None] = mapped_column(String, nullable=True)
    triggered_by: Mapped[str] = mapped_column(
        String, nullable=False, default="manual"
    )
    model: Mapped[str | None] = mapped_column(String, nullable=True)

    total_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_phrasings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    strict_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    soft_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    total_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost_usd: Mapped[float | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvalCaseResult(Base):
    """One phrasing x one repeat = one row.

    Intent dimensions are denormalized columns (not just tags) so the
    dashboard can index/slice quickly. See docs/EVAL_HARNESS.md §7.
    """

    __tablename__ = "eval_case_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    case_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    phrasing: Mapped[str] = mapped_column(Text, nullable=False)
    repeat_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    verdict: Mapped[str] = mapped_column(String, nullable=False, index=True)
    errored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    final_response: Mapped[str] = mapped_column(Text, nullable=False, default="")
    failure_reasons: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )

    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)

    langsmith_trace_id: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )
    langsmith_trace_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    langsmith_thread_id: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_thread_id: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )

    intent_question_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    intent_complexity: Mapped[str] = mapped_column(String, nullable=False, index=True)
    intent_domain: Mapped[str] = mapped_column(String, nullable=False, index=True)
    intent_answer_shape: Mapped[str] = mapped_column(String, nullable=False)

    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


# ===========================================================================
# Data foundation reformation tables (master plan §2.6, §2.10)
# ===========================================================================


class StandingsDailyCache(Base):
    """Lazy per-(league, team, date) cached fantasy-points total.

    Populated on first read by `services.standings.standings_at(league_id, date)`.
    Invalidated via `StandingsCacheInvalidation` sweeper after game-log changes.
    Not authoritative — always rebuildable from `nba_game_logs` + `roster_at`.
    """

    __tablename__ = "standings_daily_cache"

    league_id: Mapped[int] = mapped_column(
        ForeignKey("leagues.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    on_date: Mapped[date] = mapped_column(Date, primary_key=True)
    fps_total: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    computed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class StandingsCacheInvalidation(Base):
    """Pending invalidation rows enqueued by sync_game_logs after batch commit.

    A 5-min sweeper deletes affected `StandingsDailyCache` rows then deletes
    the invalidation rows. Sweeper-based instead of DB triggers because
    asyncpg + SQLAlchemy don't play well with Python-callback triggers.
    """

    __tablename__ = "standings_cache_invalidations"

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int | None] = mapped_column(
        ForeignKey("leagues.id", ondelete="CASCADE"), index=True, nullable=True
    )
    on_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # When NULL league_id: invalidate this date across all leagues (used
    # when a game log lands and we don't know which leagues are affected).
    enqueued_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class BackfillCursor(Base):
    """Resumable backfill progress.

    Long-running backfill jobs (game_logs over 2 seasons, transactions per
    league, headshot downloads) write a cursor row keyed by (job_name, scope)
    so a restart picks up from `last_completed_at` instead of from scratch.
    """

    __tablename__ = "backfill_cursor"
    __table_args__ = (
        UniqueConstraint("job_name", "scope", name="uq_backfill_cursor_job_scope"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String, nullable=False)
    # Free-form scope: a league_key, a player batch id, a date range,
    # whatever the job needs to identify "this slice of work."
    scope: Mapped[str] = mapped_column(String, nullable=False)
    last_completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    # Last successfully completed date (for date-range backfills).
    last_completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Job-specific state (next page token, next player_key, etc.).
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
