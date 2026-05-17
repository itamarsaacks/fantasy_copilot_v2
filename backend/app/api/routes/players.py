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

from datetime import date as date_type, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import (
    FreeAgent,
    League,
    NbaGameLog,
    NbaSchedule,
    NewsItem,
    Player,
    PlayerStats,
    ProjectionCache,
    RosterPlayer,
    Team,
    User,
)
from app.engine.projection import (
    CATEGORY_LEAGUE_TYPES,
    POINTS_LEAGUE_TYPES,
    _CategoryValuator,
    _PointsValuator,
)
from app.security import get_current_user
from app.services.player_history import fetch_and_cache_logs
from app.services.yahoo_auth import get_fresh_access_token

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


# ===========================================================================
# Player detail — single player over an arbitrary date range
# ===========================================================================

_AVAIL_OUT = {"OUT", "O", "IL", "IL-LT", "NA", "SUSP"}
_AVAIL_QUESTIONABLE = {"INJ", "GTD", "DTD", "Q"}

_MAX_DETAIL_PAST_DAYS = 365
_MAX_DETAIL_FUTURE_DAYS = 90
_DEFAULT_DETAIL_DAYS_BACK = 30


def _availability_factor(status: str | None) -> float:
    s = (status or "").upper()
    if s in _AVAIL_OUT:
        return 0.0
    if s in _AVAIL_QUESTIONABLE:
        return 0.7
    return 1.0


def _b2b_factor(team_games_in_window: list[date_type], target_date: date_type) -> float:
    """1-day rest before → 0.93. 3+ days rest before → 1.05. Else 1.0."""
    prev: date_type | None = None
    sorted_dates = sorted(team_games_in_window)
    for d in sorted_dates:
        if d == target_date:
            if prev is None:
                return 1.0
            gap = (target_date - prev).days
            if gap == 1:
                return 0.93
            if gap >= 3:
                return 1.05
            return 1.0
        if d < target_date:
            prev = d
    return 1.0


class PlayerDetailMeta(BaseModel):
    id: int
    yahoo_player_key: str
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


class PlayerDetailOwnership(BaseModel):
    state: Literal["free_agent", "waivers", "on_team", "my_team"]
    team_name: str | None
    waiver_status: str | None


class DateRangeMeta(BaseModel):
    start: str
    end: str
    today: str


class GameLogRow(BaseModel):
    date: str
    opponent: str | None
    home: bool | None
    is_back_to_back: bool
    minutes: float | None
    stats: dict[str, float]  # raw stat-id keyed values
    fantasy_points: float | None


class StatsAggregate(BaseModel):
    games_played: int
    totals: dict[str, float]
    per_game: dict[str, float]
    fantasy_points_total: float | None
    fantasy_points_per_game: float | None
    games_log: list[GameLogRow]


class ProjectedGameRow(BaseModel):
    date: str
    opponent: str
    home: bool
    is_back_to_back: bool
    projected_fps: float | None


class ProjectionAggregate(BaseModel):
    games_projected: int
    fantasy_points_total: float | None
    fantasy_points_per_game: float | None
    games_log: list[ProjectedGameRow]


class PlayerNewsItem(BaseModel):
    title: str
    body: str | None
    url: str | None
    kind: str
    confidence: float | None
    source: str
    published_at: str


class PlayerDetailResponse(BaseModel):
    player: PlayerDetailMeta
    ownership: PlayerDetailOwnership
    date_range: DateRangeMeta
    base_projection_per_game: float | None  # league projection_cache value
    actual: StatsAggregate
    projection: ProjectionAggregate
    news: list[PlayerNewsItem]


def _parse_range(
    start: str | None, end: str | None
) -> tuple[date_type, date_type, date_type]:
    today = datetime.now(timezone.utc).date()
    try:
        s = date_type.fromisoformat(start) if start else today - timedelta(days=_DEFAULT_DETAIL_DAYS_BACK)
        e = date_type.fromisoformat(end) if end else today
    except ValueError:
        raise HTTPException(400, "start/end must be YYYY-MM-DD")
    if s > e:
        raise HTTPException(400, "start must be on/before end")
    if (today - s).days > _MAX_DETAIL_PAST_DAYS:
        raise HTTPException(400, f"start can't be more than {_MAX_DETAIL_PAST_DAYS} days in the past")
    if (e - today).days > _MAX_DETAIL_FUTURE_DAYS:
        raise HTTPException(400, f"end can't be more than {_MAX_DETAIL_FUTURE_DAYS} days in the future")
    return s, e, today


def _stats_dict_for_response(box: dict[str, Any]) -> dict[str, float]:
    """Return {stat_abbr: value} for the columns the UI cares about,
    sourced from a Yahoo-keyed box."""
    out: dict[str, float] = {}
    for stat_id, abbr in STAT_COLUMNS.items():
        v = box.get(stat_id)
        if v is None:
            continue
        try:
            out[abbr] = float(v)
        except (TypeError, ValueError):
            continue
    # Include minutes (Yahoo stat_id 2 = MIN) when present
    if "2" in box:
        try:
            out["min"] = float(box["2"])
        except (TypeError, ValueError):
            pass
    return out


@router.get("/{league_id}/{player_id}", response_model=PlayerDetailResponse)
async def get_player_detail(
    league_id: int,
    player_id: int,
    start: str | None = Query(default=None, description="YYYY-MM-DD, defaults to 30 days ago"),
    end: str | None = Query(default=None, description="YYYY-MM-DD, defaults to today"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    start_date, end_date, today = _parse_range(start, end)

    league = (
        await db.execute(
            select(League).where(League.id == league_id, League.user_id == user.id)
        )
    ).scalar_one_or_none()
    if league is None:
        raise HTTPException(404, "league not found")

    player = await db.get(Player, player_id)
    if player is None:
        raise HTTPException(404, "player not found")

    # Ownership context within this league
    my_team = (
        await db.execute(
            select(Team).where(Team.league_id == league_id, Team.is_user_team.is_(True))
        )
    ).scalar_one_or_none()
    rp_row = (
        await db.execute(
            select(RosterPlayer, Team)
            .join(Team, Team.id == RosterPlayer.team_id)
            .where(
                RosterPlayer.player_id == player_id,
                Team.league_id == league_id,
            )
        )
    ).first()
    fa_row = (
        await db.execute(
            select(FreeAgent).where(
                FreeAgent.player_id == player_id,
                FreeAgent.league_id == league_id,
            )
        )
    ).scalar_one_or_none()

    if rp_row is not None:
        _rp, owning_team = rp_row
        is_mine = my_team is not None and owning_team.id == my_team.id
        ownership = PlayerDetailOwnership(
            state="my_team" if is_mine else "on_team",
            team_name=owning_team.name,
            waiver_status=None,
        )
    elif fa_row is not None and fa_row.waiver_status == "W":
        ownership = PlayerDetailOwnership(
            state="waivers", team_name=None, waiver_status=fa_row.waiver_status
        )
    elif fa_row is not None:
        ownership = PlayerDetailOwnership(
            state="free_agent", team_name=None, waiver_status=fa_row.waiver_status
        )
    else:
        ownership = PlayerDetailOwnership(
            state="free_agent", team_name=None, waiver_status=None
        )

    # Base per-game projection from the cached engine output (used in
    # the per-date projection formula below)
    base_proj_row = (
        await db.execute(
            select(ProjectionCache).where(
                ProjectionCache.league_id == league_id,
                ProjectionCache.player_id == player_id,
                ProjectionCache.horizon == "per_game",
            )
        )
    ).scalar_one_or_none()
    base_proj = float(base_proj_row.projected_value) if base_proj_row and base_proj_row.projected_value is not None else None

    # Schedule across the entire range (used for both actuals B2B context
    # and future-date projection)
    sched_rows: list[NbaSchedule] = []
    if player.nba_team_abbr:
        sched_rows = (
            await db.execute(
                select(NbaSchedule)
                .where(
                    NbaSchedule.game_date >= start_date,
                    NbaSchedule.game_date <= end_date,
                    or_(
                        NbaSchedule.home_team_abbr == player.nba_team_abbr,
                        NbaSchedule.away_team_abbr == player.nba_team_abbr,
                    ),
                )
                .order_by(NbaSchedule.game_date)
            )
        ).scalars().all()
        sched_rows = list(sched_rows)

    sched_dates = [g.game_date for g in sched_rows]

    # ------------------------------------------------------------------
    # ACTUAL portion — past games in range. Fetched + cached via the
    # player_history service.
    # ------------------------------------------------------------------
    access_token = await get_fresh_access_token(db, user)
    logs = await fetch_and_cache_logs(
        db,
        access_token=access_token,
        player=player,
        start=start_date,
        end=end_date,
        today=today,
    )

    # Pick a valuator for fps math from the league settings.
    valuator = None
    if league.scoring_type in POINTS_LEAGUE_TYPES:
        valuator = _PointsValuator.from_settings(league.settings_json or {})
    elif league.scoring_type in CATEGORY_LEAGUE_TYPES:
        valuator = _CategoryValuator.from_settings(league.settings_json or {})

    actual_games_log: list[GameLogRow] = []
    totals: dict[str, float] = {abbr: 0.0 for abbr in STAT_COLUMNS.values()}
    fps_total = 0.0
    fps_any = False
    games_played = 0
    minutes_total = 0.0
    minutes_any = False

    # Iterate the cached/fetched logs directly. We no longer rely on
    # sched_dates here because in regular-season-past the schedule rows
    # may not exist yet (we only sync forward 14 days). The logs list
    # is the source of truth for "what games did this player play in
    # the requested past range." Off-day placeholders ({_no_game: 1})
    # are filtered out.
    real_logs = [l for l in logs if (l.box or {}).get("_no_game") is None]
    actual_dates_in_order = sorted({l.game_date for l in real_logs})
    log_by_date: dict[date_type, NbaGameLog] = {l.game_date: l for l in real_logs}
    for d in actual_dates_in_order:
        if d > today:
            continue
        log_row = log_by_date[d]
        games_played += 1
        box = log_row.box or {}
        stats = _stats_dict_for_response(box)
        for abbr, v in stats.items():
            if abbr in totals:
                totals[abbr] += v
        if "min" in stats:
            minutes_total += stats["min"]
            minutes_any = True
        # FPS for this game
        fps_one: float | None = None
        if valuator is not None:
            fps_one_raw, _components = valuator.season_total(
                {k: float(v) for k, v in box.items() if isinstance(v, (int, float))}
            )
            if fps_one_raw is not None:
                fps_one = round(fps_one_raw, 2)
                fps_total += fps_one_raw
                fps_any = True

        # B2B detection: was the previous played game exactly one day before?
        idx = actual_dates_in_order.index(d)
        is_b2b = idx > 0 and (d - actual_dates_in_order[idx - 1]).days == 1

        actual_games_log.append(
            GameLogRow(
                date=d.isoformat(),
                opponent=log_row.opponent_abbr,
                home=log_row.is_home,
                is_back_to_back=is_b2b,
                minutes=stats.get("min"),
                stats=stats,
                fantasy_points=fps_one,
            )
        )

    per_game: dict[str, float] = {}
    if games_played:
        for abbr, total in totals.items():
            per_game[abbr] = round(total / games_played, 2)
        if minutes_any:
            per_game["min"] = round(minutes_total / games_played, 1)
            totals["min"] = round(minutes_total, 1)

    actual = StatsAggregate(
        games_played=games_played,
        totals={k: round(v, 2) for k, v in totals.items()},
        per_game=per_game,
        fantasy_points_total=round(fps_total, 2) if fps_any else None,
        fantasy_points_per_game=round(fps_total / games_played, 2) if (fps_any and games_played) else None,
        games_log=actual_games_log,
    )

    # ------------------------------------------------------------------
    # PROJECTION portion — future games in range.
    # ------------------------------------------------------------------
    projected_log: list[ProjectedGameRow] = []
    proj_fps_total = 0.0
    proj_games_count = 0
    if base_proj is not None and player.nba_team_abbr:
        avail = _availability_factor(player.status)
        for g in sched_rows:
            if g.game_date <= today:
                continue
            is_home = g.home_team_abbr == player.nba_team_abbr
            home_factor = 1.03 if is_home else 0.97
            b2b = _b2b_factor(sched_dates, g.game_date)
            proj_one = base_proj * home_factor * b2b * avail
            prev_dates = [pd for pd in sched_dates if pd < g.game_date]
            is_b2b = bool(prev_dates) and (g.game_date - max(prev_dates)).days == 1
            projected_log.append(
                ProjectedGameRow(
                    date=g.game_date.isoformat(),
                    opponent=g.away_team_abbr if is_home else g.home_team_abbr,
                    home=is_home,
                    is_back_to_back=is_b2b,
                    projected_fps=round(proj_one, 2),
                )
            )
            proj_fps_total += proj_one
            proj_games_count += 1

    projection = ProjectionAggregate(
        games_projected=proj_games_count,
        fantasy_points_total=round(proj_fps_total, 2) if proj_games_count else None,
        fantasy_points_per_game=round(proj_fps_total / proj_games_count, 2) if proj_games_count else None,
        games_log=projected_log,
    )

    # ------------------------------------------------------------------
    # News
    # ------------------------------------------------------------------
    news_rows = (
        await db.execute(
            select(NewsItem)
            .where(NewsItem.player_id == player_id)
            .order_by(NewsItem.published_at.desc())
            .limit(8)
        )
    ).scalars().all()
    news = [
        PlayerNewsItem(
            title=n.title,
            body=n.body,
            url=n.url,
            kind=n.kind,
            confidence=float(n.confidence) if n.confidence is not None else None,
            source=n.source,
            published_at=n.published_at.isoformat(),
        )
        for n in news_rows
    ]

    return PlayerDetailResponse(
        player=PlayerDetailMeta(
            id=player.id,
            yahoo_player_key=player.yahoo_player_key,
            name=player.full_name,
            nba_team=player.nba_team_abbr,
            eligible_positions=player.eligible_positions or [],
            primary_position=player.primary_position,
            status=player.status,
            status_full=player.status_full,
            injury_note=player.injury_note,
            image_url=player.image_url,
            percent_owned=float(player.percent_owned) if player.percent_owned is not None else None,
            percent_started=float(player.percent_started) if player.percent_started is not None else None,
        ),
        ownership=ownership,
        date_range=DateRangeMeta(
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            today=today.isoformat(),
        ),
        base_projection_per_game=round(base_proj, 2) if base_proj is not None else None,
        actual=actual,
        projection=projection,
        news=news,
    )


# ===========================================================================
# Player ownership timeline — drives the "while I owned him" UX on the
# detail drawer. First call to this endpoint triggers a one-time
# transactions sync for the league.
# ===========================================================================


class OwnershipEvent(BaseModel):
    occurred_at: str
    event_type: Literal["add", "drop", "trade"]
    from_team_id: int | None
    from_team_name: str | None
    to_team_id: int | None
    to_team_name: str | None
    transaction_key: str


class OwnershipInterval(BaseModel):
    """A continuous span of time the player belonged to one team.

    `team_id == None` means a free-agent interval (between drops and
    re-adds). `ended_at == None` means current ownership.
    """

    team_id: int | None
    team_name: str | None
    is_user_team: bool
    started_at: str
    ended_at: str | None


class OwnershipTimelineResponse(BaseModel):
    league_id: int
    player_id: int
    events: list[OwnershipEvent]
    intervals: list[OwnershipInterval]
    sync_summary: dict[str, int]


def _build_intervals(
    events: list[PlayerOwnershipEvent], teams_by_id: dict[int, Team]
) -> list[OwnershipInterval]:
    """Walk events oldest→newest and emit continuous ownership intervals."""
    sorted_events = sorted(events, key=lambda e: e.occurred_at)
    intervals: list[OwnershipInterval] = []
    current_team_id: int | None = None
    current_started: datetime | None = None

    def _flush(end_at: datetime | None):
        nonlocal current_team_id, current_started
        if current_started is None:
            return
        team = teams_by_id.get(current_team_id) if current_team_id else None
        intervals.append(
            OwnershipInterval(
                team_id=current_team_id,
                team_name=team.name if team else None,
                is_user_team=bool(team and team.is_user_team),
                started_at=current_started.isoformat(),
                ended_at=end_at.isoformat() if end_at else None,
            )
        )

    for ev in sorted_events:
        # After each event the player's "now owned by" state changes to
        # the destination team (or to no-team on a drop).
        new_owner = ev.to_team_id if ev.event_type in ("add", "trade") else None
        if current_started is None:
            current_team_id = new_owner
            current_started = ev.occurred_at
            continue
        if new_owner == current_team_id:
            continue
        _flush(ev.occurred_at)
        current_team_id = new_owner
        current_started = ev.occurred_at
    _flush(None)
    return intervals


@router.get(
    "/{league_id}/{player_id}/ownership", response_model=OwnershipTimelineResponse
)
async def get_player_ownership(
    league_id: int,
    player_id: int,
    sync: bool = Query(default=True, description="Refresh from Yahoo before returning"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    from app.jobs.sync_transactions import sync_league_transactions  # local import to avoid cycles

    league = (
        await db.execute(
            select(League).where(League.id == league_id, League.user_id == user.id)
        )
    ).scalar_one_or_none()
    if league is None:
        raise HTTPException(404, "league not found")
    if (await db.get(Player, player_id)) is None:
        raise HTTPException(404, "player not found")

    from app.db.models import PlayerOwnershipEvent  # local for clarity

    # Only run the (slow) sync if asked AND we have no events yet for this
    # league. Subsequent loads of a player drawer hit pure DB and return
    # in ~50ms. A future cron or admin button can force a re-sync.
    sync_summary = {"fetched": 0, "players_seen": 0, "events_written": 0}
    existing_count = (
        await db.execute(
            select(func.count())
            .select_from(PlayerOwnershipEvent)
            .where(PlayerOwnershipEvent.league_id == league_id)
        )
    ).scalar_one()
    if sync and existing_count == 0:
        try:
            sync_summary = await sync_league_transactions(
                db, user=user, league=league
            )
        except Exception as exc:  # noqa: BLE001
            sync_summary["error"] = str(exc)  # type: ignore[assignment]

    rows = (
        await db.execute(
            select(PlayerOwnershipEvent)
            .where(
                PlayerOwnershipEvent.league_id == league_id,
                PlayerOwnershipEvent.player_id == player_id,
            )
            .order_by(PlayerOwnershipEvent.occurred_at.asc())
        )
    ).scalars().all()

    # Resolve team names for the events + intervals
    team_ids_referenced: set[int] = set()
    for ev in rows:
        if ev.from_team_id:
            team_ids_referenced.add(ev.from_team_id)
        if ev.to_team_id:
            team_ids_referenced.add(ev.to_team_id)
    teams_by_id: dict[int, Team] = {}
    if team_ids_referenced:
        team_rows = (
            await db.execute(select(Team).where(Team.id.in_(team_ids_referenced)))
        ).scalars().all()
        teams_by_id = {t.id: t for t in team_rows}

    events = [
        OwnershipEvent(
            occurred_at=ev.occurred_at.isoformat(),
            event_type=ev.event_type,  # type: ignore[arg-type]
            from_team_id=ev.from_team_id,
            from_team_name=teams_by_id.get(ev.from_team_id).name if ev.from_team_id and teams_by_id.get(ev.from_team_id) else None,
            to_team_id=ev.to_team_id,
            to_team_name=teams_by_id.get(ev.to_team_id).name if ev.to_team_id and teams_by_id.get(ev.to_team_id) else None,
            transaction_key=ev.transaction_key,
        )
        for ev in rows
    ]
    intervals = _build_intervals(rows, teams_by_id)

    return OwnershipTimelineResponse(
        league_id=league_id,
        player_id=player_id,
        events=events,
        intervals=intervals,
        sync_summary=sync_summary,
    )
