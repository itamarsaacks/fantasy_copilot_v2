"""Players tab — searchable/sortable list of every NBA player in the
user's league universe (rostered anywhere + free agents).

GET /api/players/{league_id} accepts:
  search       name substring (case-insensitive)
  position     PG | SG | SF | PF | C (exact match against eligible_positions)
  availability all | available | owned | my_team
  sort_by      proj | owned | pts | reb | ast | stl | blk | name | season_fps
  sort_dir     asc | desc (default desc; name defaults to asc)
  limit        page size, max 100 (default 50)
  offset       pagination cursor

Returns season per-game stats, the cached league projection (per-game
horizon), Yahoo ownership signals, and the player's league-context
(free agent / on which team).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import (
    FreeAgent,
    League,
    Player,
    PlayerStats,
    ProjectionCache,
    RosterPlayer,
    Team,
    User,
)
from app.security import get_current_user

router = APIRouter(prefix="/api/players", tags=["players"])

# Yahoo stat-id → per-game column on the response
STAT_COLUMNS = {
    "12": "pts",
    "15": "reb",
    "16": "ast",
    "17": "stl",
    "18": "blk",
    "19": "tov",
}
GP_STAT_ID = "0"

_SORT_FIELDS = {"proj", "owned", "pts", "reb", "ast", "stl", "blk", "name", "season_fps"}
_AVAIL_OPTIONS = {"all", "available", "owned", "my_team"}

# Filterable position vocabulary differs per league — some leagues use full
# PG/SG/SF/PF/C, others use simplified G/F/FC/Util. We discover the actual
# vocabulary from the league's player universe at query time and skip these
# non-position roster slots when surfacing chips to the frontend.
_NON_POSITION_SLOTS = {"BN", "IR", "IR+", "IL", "IL+", "NA", "Util"}


class PlayerSeasonStats(BaseModel):
    gp: int | None
    pts: float | None
    reb: float | None
    ast: float | None
    stl: float | None
    blk: float | None
    tov: float | None


class PlayerOwnership(BaseModel):
    """In-league context for this player."""

    state: Literal["free_agent", "waivers", "on_team", "my_team"]
    team_name: str | None  # populated for on_team / my_team
    waiver_status: str | None  # A / FA / W (when free_agent / waivers)


class PlayerView(BaseModel):
    id: int
    name: str
    nba_team: str | None
    eligible_positions: list[str]
    primary_position: str | None
    status: str | None
    status_full: str | None
    injury_note: str | None
    image_url: str | None
    percent_owned: float | None
    percent_started: float | None
    projected_fps_per_game: float | None
    season_fps_per_game: float | None  # derived from projection components if available
    season_stats: PlayerSeasonStats
    ownership: PlayerOwnership


class PlayersResponse(BaseModel):
    league_id: int
    total: int
    limit: int
    offset: int
    available_positions: list[str]  # league-aware filter chips
    items: list[PlayerView]


def _per_game(value: float | None, gp: int | None) -> float | None:
    if value is None or not gp:
        return None
    return round(value / gp, 1)


@router.get("/{league_id}", response_model=PlayersResponse)
async def get_players(
    league_id: int,
    search: str | None = Query(default=None, max_length=80),
    position: str | None = Query(default=None),
    availability: str = Query(default="all"),
    sort_by: str = Query(default="proj"),
    sort_dir: str = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    # Validate inputs
    if availability not in _AVAIL_OPTIONS:
        raise HTTPException(400, f"availability must be one of {sorted(_AVAIL_OPTIONS)}")
    if sort_by not in _SORT_FIELDS:
        raise HTTPException(400, f"sort_by must be one of {sorted(_SORT_FIELDS)}")
    if sort_dir not in {"asc", "desc"}:
        raise HTTPException(400, "sort_dir must be asc or desc")
    if position is not None:
        position = position.strip()
        if not position:
            position = None

    league = (
        await db.execute(
            select(League).where(League.id == league_id, League.user_id == user.id)
        )
    ).scalar_one_or_none()
    if league is None:
        raise HTTPException(404, "league not found")

    my_team = (
        await db.execute(
            select(Team).where(Team.league_id == league_id, Team.is_user_team.is_(True))
        )
    ).scalar_one_or_none()
    my_team_id = my_team.id if my_team else None

    # ------------------------------------------------------------------
    # Build the universe of player rows: rostered-in-this-league OR FA.
    # We left-join FreeAgent and RosterPlayer (via teams in this league)
    # and decorate each player with state + team_name + waiver_status.
    # ------------------------------------------------------------------
    league_teams = select(Team.id).where(Team.league_id == league_id).subquery()

    # Subquery: a player's roster row in this league (if any)
    roster_sq = (
        select(
            RosterPlayer.player_id,
            RosterPlayer.team_id,
            Team.name.label("team_name"),
            Team.is_user_team.label("is_user_team"),
        )
        .join(Team, Team.id == RosterPlayer.team_id)
        .where(Team.league_id == league_id)
        .subquery()
    )
    fa_sq = (
        select(FreeAgent.player_id, FreeAgent.waiver_status)
        .where(FreeAgent.league_id == league_id)
        .subquery()
    )

    state_expr = case(
        (
            roster_sq.c.is_user_team.is_(True),
            "my_team",
        ),
        (
            roster_sq.c.team_id.isnot(None),
            "on_team",
        ),
        (
            fa_sq.c.waiver_status == "W",
            "waivers",
        ),
        else_="free_agent",
    ).label("state")

    base = (
        select(
            Player.id,
            Player.full_name,
            Player.nba_team_abbr,
            Player.eligible_positions,
            Player.primary_position,
            Player.status,
            Player.status_full,
            Player.injury_note,
            Player.image_url,
            Player.percent_owned,
            Player.percent_started,
            roster_sq.c.team_name,
            roster_sq.c.is_user_team,
            roster_sq.c.team_id,
            fa_sq.c.waiver_status,
            state_expr,
        )
        .outerjoin(roster_sq, roster_sq.c.player_id == Player.id)
        .outerjoin(fa_sq, fa_sq.c.player_id == Player.id)
        .where(
            or_(
                roster_sq.c.team_id.isnot(None),
                fa_sq.c.player_id.isnot(None),
            )
        )
    )

    # Filters
    if search:
        # Diacritic-insensitive substring match — "jokic" matches "Jokić".
        # Requires the `unaccent` extension (created during onboarding/migrations).
        term = f"%{search.strip()}%"
        base = base.where(
            func.unaccent(Player.full_name).ilike(func.unaccent(term))
        )
    if position:
        # eligible_positions is a JSONB array. PG uses jsonb_path_exists-equivalent
        # via the `?` operator (key existence). For arrays it checks element
        # existence as a string.
        base = base.where(Player.eligible_positions.op("?")(position))
    if availability == "available":
        base = base.where(state_expr.in_(("free_agent", "waivers")))
    elif availability == "owned":
        base = base.where(state_expr.in_(("on_team", "my_team")))
    elif availability == "my_team":
        base = base.where(state_expr == "my_team")

    # Total count BEFORE pagination (for the "X of Y" UI hint).
    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Discover the position vocabulary actually used in this league's
    # universe (rostered + FA). Skip pure roster-slot labels.
    pos_rows = (
        await db.execute(
            select(func.distinct(func.jsonb_array_elements_text(Player.eligible_positions)))
            .select_from(Player)
            .outerjoin(roster_sq, roster_sq.c.player_id == Player.id)
            .outerjoin(fa_sq, fa_sq.c.player_id == Player.id)
            .where(
                or_(
                    roster_sq.c.team_id.isnot(None),
                    fa_sq.c.player_id.isnot(None),
                )
            )
        )
    ).scalars().all()
    available_positions = sorted(p for p in pos_rows if p and p not in _NON_POSITION_SLOTS)

    # Apply sort — projection sort joins projection_cache
    proj_sq = (
        select(ProjectionCache.player_id, ProjectionCache.projected_value.label("proj"))
        .where(
            ProjectionCache.league_id == league_id,
            ProjectionCache.horizon == "per_game",
        )
        .subquery()
    )
    base = base.add_columns(proj_sq.c.proj).outerjoin(
        proj_sq, proj_sq.c.player_id == Player.id
    )

    direction = "desc" if sort_dir == "desc" else "asc"
    nulls_last = direction == "desc"

    def _ord(col):
        if direction == "desc":
            return col.desc().nullslast() if nulls_last else col.desc()
        return col.asc().nullsfirst()

    if sort_by == "name":
        base = base.order_by(_ord(Player.full_name))
    elif sort_by == "owned":
        base = base.order_by(_ord(Player.percent_owned), Player.full_name.asc())
    elif sort_by == "proj" or sort_by == "season_fps":
        # Both sort by the same projection number today; season_fps gets a
        # dedicated computed column when we expose recent-form values.
        base = base.order_by(_ord(proj_sq.c.proj), Player.full_name.asc())
    else:
        # Per-stat sorts hit a separate ranked subquery below.
        base = base.order_by(_ord(proj_sq.c.proj), Player.full_name.asc())

    base = base.offset(offset).limit(limit)
    rows = (await db.execute(base)).all()
    if not rows:
        return PlayersResponse(
            league_id=league_id,
            total=total,
            limit=limit,
            offset=offset,
            available_positions=available_positions,
            items=[],
        )

    page_player_ids = [r.id for r in rows]

    # ------------------------------------------------------------------
    # Stat hydration — season per-game stats keyed by player_id
    # ------------------------------------------------------------------
    relevant_stat_ids = [GP_STAT_ID] + list(STAT_COLUMNS.keys())
    stat_rows = (
        await db.execute(
            select(PlayerStats).where(
                PlayerStats.scope == "season",
                PlayerStats.player_id.in_(page_player_ids),
                PlayerStats.stat_id.in_(relevant_stat_ids),
            )
        )
    ).scalars().all()
    stats_by_player: dict[int, dict[str, float]] = {}
    for s in stat_rows:
        stats_by_player.setdefault(s.player_id, {})[s.stat_id] = float(s.value)

    # If we sorted by a per-stat key (pts/reb/etc.), re-sort the page in
    # memory using the season per-game values. Total + pagination above
    # used projection ordering as a stable baseline — acceptable because
    # per-stat sorts on the global universe are rare and the page size
    # is small.
    if sort_by in {"pts", "reb", "ast", "stl", "blk"}:
        stat_id = {v: k for k, v in STAT_COLUMNS.items()}[sort_by]

        def _key(r):
            s = stats_by_player.get(r.id, {})
            gp = s.get(GP_STAT_ID)
            v = _per_game(s.get(stat_id), int(gp) if gp else None)
            return (v if v is not None else float("-inf"))

        rows = sorted(rows, key=_key, reverse=(sort_dir == "desc"))

    # ------------------------------------------------------------------
    # Build response views
    # ------------------------------------------------------------------
    items: list[PlayerView] = []
    for r in rows:
        s = stats_by_player.get(r.id, {})
        gp_val = s.get(GP_STAT_ID)
        gp = int(gp_val) if gp_val and gp_val > 0 else None
        season = PlayerSeasonStats(
            gp=gp,
            pts=_per_game(s.get("12"), gp),
            reb=_per_game(s.get("15"), gp),
            ast=_per_game(s.get("16"), gp),
            stl=_per_game(s.get("17"), gp),
            blk=_per_game(s.get("18"), gp),
            tov=_per_game(s.get("19"), gp),
        )

        ownership = PlayerOwnership(
            state=r.state,
            team_name=r.team_name,
            waiver_status=r.waiver_status,
        )

        items.append(
            PlayerView(
                id=r.id,
                name=r.full_name,
                nba_team=r.nba_team_abbr,
                eligible_positions=r.eligible_positions or [],
                primary_position=r.primary_position,
                status=r.status,
                status_full=r.status_full,
                injury_note=r.injury_note,
                image_url=r.image_url,
                percent_owned=float(r.percent_owned) if r.percent_owned is not None else None,
                percent_started=(
                    float(r.percent_started) if r.percent_started is not None else None
                ),
                projected_fps_per_game=float(r.proj) if r.proj is not None else None,
                season_fps_per_game=float(r.proj) if r.proj is not None else None,
                season_stats=season,
                ownership=ownership,
            )
        )

    return PlayersResponse(
        league_id=league_id,
        total=total,
        limit=limit,
        offset=offset,
        available_positions=available_positions,
        items=items,
    )
