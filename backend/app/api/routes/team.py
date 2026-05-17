"""Team-tab endpoint — user's roster as a Yahoo-style starter/bench list.

GET /api/team/{league_id}?date=YYYY-MM-DD returns the user's roster grouped
into three buckets (starters / bench / ir). Each player carries:
  - season per-game stats
  - status / injury_note
  - the game on the requested date (None if no game)
  - a per-date projection (Stage 1: per_game × home × b2b × availability)

Stage-2 follow-ups (not implemented yet): opponent defensive rating,
minutes trend, write back to Yahoo for real lineup edits.
"""

from __future__ import annotations

from datetime import date as date_type, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import (
    League,
    NbaSchedule,
    Player,
    PlayerStats,
    ProjectionCache,
    RosterPlayer,
    Team,
    User,
)
from app.security import get_current_user

router = APIRouter(prefix="/api/team", tags=["team"])

# Yahoo NBA stat-id → column key on the frontend
STAT_COLUMNS = {
    "12": "pts",
    "15": "reb",
    "16": "ast",
    "17": "stl",
    "18": "blk",
    "19": "tov",
}
GP_STAT_ID = "0"

# Slot → bucket. Anything not listed goes to "starters".
SLOT_BUCKET = {
    "BN": "bench",
    "IR": "ir",
    "IR+": "ir",
    "IL": "ir",
    "IL+": "ir",
    "NA": "ir",
}

# Display order within a bucket
SLOT_ORDER = [
    "PG", "SG", "G", "SF", "PF", "F", "C", "Util",
    "BN",
    "IR", "IR+", "IL", "IL+", "NA",
]

# Availability buckets — keyed by Yahoo's `status` field
_AVAIL_OUT = {"OUT", "O", "IL", "IL-LT", "NA", "SUSP"}
_AVAIL_QUESTIONABLE = {"INJ", "GTD", "DTD", "Q"}

# How far back/forward the date picker is allowed to query.
_MAX_DATE_OFFSET_DAYS = 30


def _slot_weight(slot: str | None) -> int:
    if slot is None:
        return 999
    try:
        return SLOT_ORDER.index(slot)
    except ValueError:
        return 998


def _availability_factor(status: str | None) -> float:
    s = (status or "").upper()
    if s in _AVAIL_OUT:
        return 0.0
    if s in _AVAIL_QUESTIONABLE:
        return 0.7
    return 1.0


def _b2b_factor(team_games: list[NbaSchedule], target_date: date_type) -> float:
    """0.93 for the 2nd of a B2B; 1.05 with 2+ days rest before the game; else 1.0.

    team_games is already sorted ascending by game_date.
    """
    prev: date_type | None = None
    for g in team_games:
        if g.game_date == target_date:
            if prev is None:
                # First game of the lookahead window — can't tell rest.
                return 1.0
            gap = (target_date - prev).days
            if gap == 1:
                return 0.93
            if gap >= 3:
                return 1.05
            return 1.0
        if g.game_date < target_date:
            prev = g.game_date
    return 1.0


def _per_date_projection(
    base_per_game: float | None,
    game: NbaSchedule | None,
    player_team: str | None,
    team_games: list[NbaSchedule],
    status: str | None,
) -> float | None:
    """Stage-1 per-date projection.

    Returns None if there's no game that day (caller renders "—").
    Returns 0.0 if the player is OUT/IL — we want the row to show a 0 number,
    not "no game".
    """
    if game is None or base_per_game is None or player_team is None:
        return None
    avail = _availability_factor(status)
    if avail == 0.0:
        return 0.0
    is_home = game.home_team_abbr == player_team
    home_factor = 1.03 if is_home else 0.97
    b2b = _b2b_factor(team_games, game.game_date)
    return round(base_per_game * home_factor * b2b * avail, 2)


class GameOnDate(BaseModel):
    date: str
    opponent: str
    home: bool
    status: str  # scheduled/live/final/postponed
    tipoff_at: str | None
    is_back_to_back: bool


class SeasonStats(BaseModel):
    gp: int | None
    pts: float | None
    reb: float | None
    ast: float | None
    stl: float | None
    blk: float | None
    tov: float | None


class RosterPlayerView(BaseModel):
    name: str
    nba_team: str | None
    eligible_positions: list[str]
    selected_position: str | None
    status: str | None
    status_full: str | None
    injury_note: str | None
    projected_fps_per_game: float | None  # season avg, unchanged
    projected_fps_on_date: float | None  # Stage-1 per-date projection (null if no game)
    game_on_date: GameOnDate | None
    season_stats: SeasonStats


class RosterBucket(BaseModel):
    label: str
    players: list[RosterPlayerView]


class TeamResponse(BaseModel):
    league_id: int
    league_name: str
    team_name: str
    manager_name: str | None
    requested_date: str
    starters: RosterBucket
    bench: RosterBucket
    ir: RosterBucket


def _parse_date(value: str | None) -> date_type:
    if not value:
        return datetime.now(timezone.utc).date()
    try:
        d = date_type.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid date '{value}', expected YYYY-MM-DD")
    today = datetime.now(timezone.utc).date()
    offset = abs((d - today).days)
    if offset > _MAX_DATE_OFFSET_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"date must be within ±{_MAX_DATE_OFFSET_DAYS} days of today",
        )
    return d


@router.get("/{league_id}", response_model=TeamResponse)
async def get_team(
    league_id: int,
    date: str | None = Query(default=None, description="Target date YYYY-MM-DD, defaults to today"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    target_date = _parse_date(date)
    league = (
        await db.execute(
            select(League).where(League.id == league_id, League.user_id == user.id)
        )
    ).scalar_one_or_none()
    if league is None:
        raise HTTPException(status_code=404, detail="league not found")

    my_team = (
        await db.execute(
            select(Team).where(Team.league_id == league_id, Team.is_user_team.is_(True))
        )
    ).scalar_one_or_none()
    if my_team is None:
        raise HTTPException(status_code=404, detail="user's team not found in league")

    roster_rows = (
        await db.execute(
            select(RosterPlayer, Player)
            .join(Player, Player.id == RosterPlayer.player_id)
            .where(RosterPlayer.team_id == my_team.id)
        )
    ).all()

    player_ids = [p.id for _, p in roster_rows]

    # Projections (per-game horizon) — base for per-date computation
    proj_rows = (
        await db.execute(
            select(ProjectionCache).where(
                ProjectionCache.league_id == league_id,
                ProjectionCache.horizon == "per_game",
                ProjectionCache.player_id.in_(player_ids),
            )
        )
    ).scalars().all()
    proj_by_player = {p.player_id: p for p in proj_rows}

    # Season stats — collapse the long table into {player_id: {stat_id: value}}
    relevant_stat_ids = [GP_STAT_ID] + list(STAT_COLUMNS.keys())
    stat_rows = (
        await db.execute(
            select(PlayerStats).where(
                PlayerStats.scope == "season",
                PlayerStats.player_id.in_(player_ids),
                PlayerStats.stat_id.in_(relevant_stat_ids),
            )
        )
    ).scalars().all()
    stats_by_player: dict[int, dict[str, float]] = {}
    for s in stat_rows:
        prev = stats_by_player.setdefault(s.player_id, {})
        prev[s.stat_id] = float(s.value)

    # Schedule window: include a day before so we can detect B2Bs that span
    # across the requested date. Forward window covers 14 days for "is this
    # a B2B going into the next day" logic.
    window_start = target_date - timedelta(days=2)
    window_end = target_date + timedelta(days=14)
    teams_in_roster = {p.nba_team_abbr for _, p in roster_rows if p.nba_team_abbr}
    games_by_team: dict[str, list[NbaSchedule]] = {}
    if teams_in_roster:
        schedule = (
            await db.execute(
                select(NbaSchedule).where(
                    NbaSchedule.game_date >= window_start,
                    NbaSchedule.game_date < window_end,
                    or_(
                        NbaSchedule.home_team_abbr.in_(teams_in_roster),
                        NbaSchedule.away_team_abbr.in_(teams_in_roster),
                    ),
                )
            )
        ).scalars().all()
        for g in sorted(schedule, key=lambda x: x.game_date):
            games_by_team.setdefault(g.home_team_abbr, []).append(g)
            games_by_team.setdefault(g.away_team_abbr, []).append(g)

    buckets: dict[str, list[RosterPlayerView]] = {
        "starters": [],
        "bench": [],
        "ir": [],
    }

    for rp, p in roster_rows:
        proj = proj_by_player.get(p.id)
        base_pg = float(proj.projected_value) if proj and proj.projected_value else None

        team_games = games_by_team.get(p.nba_team_abbr or "", [])

        game_today = next((g for g in team_games if g.game_date == target_date), None)
        game_on_date: GameOnDate | None = None
        if game_today is not None:
            is_home = game_today.home_team_abbr == p.nba_team_abbr
            # Is this game the 2nd of a B2B?
            prev_dates = [g.game_date for g in team_games if g.game_date < target_date]
            is_b2b = bool(prev_dates) and (target_date - max(prev_dates)).days == 1
            game_on_date = GameOnDate(
                date=game_today.game_date.isoformat(),
                opponent=game_today.away_team_abbr if is_home else game_today.home_team_abbr,
                home=is_home,
                status=game_today.status,
                tipoff_at=game_today.tipoff_at.isoformat() if game_today.tipoff_at else None,
                is_back_to_back=is_b2b,
            )

        date_proj = _per_date_projection(
            base_pg, game_today, p.nba_team_abbr, team_games, p.status
        )

        # Season per-game stats
        s = stats_by_player.get(p.id, {})
        gp_val = s.get(GP_STAT_ID)
        gp = int(gp_val) if gp_val and gp_val > 0 else None

        def _per_game(stat_id: str) -> float | None:
            v = s.get(stat_id)
            if v is None or not gp:
                return None
            return round(v / gp, 1)

        season = SeasonStats(
            gp=gp,
            pts=_per_game("12"),
            reb=_per_game("15"),
            ast=_per_game("16"),
            stl=_per_game("17"),
            blk=_per_game("18"),
            tov=_per_game("19"),
        )

        view = RosterPlayerView(
            name=p.full_name,
            nba_team=p.nba_team_abbr,
            eligible_positions=p.eligible_positions or [],
            selected_position=rp.selected_position,
            status=p.status,
            status_full=p.status_full,
            injury_note=p.injury_note,
            projected_fps_per_game=round(base_pg, 2) if base_pg is not None else None,
            projected_fps_on_date=date_proj,
            game_on_date=game_on_date,
            season_stats=season,
        )

        bucket_key = SLOT_BUCKET.get((rp.selected_position or "").upper(), "starters")
        buckets[bucket_key].append(view)

    for key in buckets:
        buckets[key].sort(key=lambda v: _slot_weight(v.selected_position))

    return TeamResponse(
        league_id=league.id,
        league_name=league.name,
        team_name=my_team.name,
        manager_name=my_team.manager_name,
        requested_date=target_date.isoformat(),
        starters=RosterBucket(label="Starters", players=buckets["starters"]),
        bench=RosterBucket(label="Bench", players=buckets["bench"]),
        ir=RosterBucket(label="Injured Reserve", players=buckets["ir"]),
    )
