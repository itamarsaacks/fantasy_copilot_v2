"""Team-tab endpoint — user's roster as a Yahoo-style starter/bench list.

GET /api/team/{league_id} returns the user's roster grouped into three
buckets (starters / bench / ir) and ordered by Yahoo lineup slot. Each
player carries projection + status + season per-game stats + next game.

Read-only; no agent involvement.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
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


def _slot_weight(slot: str | None) -> int:
    if slot is None:
        return 999
    try:
        return SLOT_ORDER.index(slot)
    except ValueError:
        return 998


class NextGame(BaseModel):
    date: str
    opponent: str
    home: bool
    status: str
    tipoff_at: str | None
    is_today: bool


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
    projected_fps_per_game: float | None
    games_this_week: int
    back_to_back_count: int
    next_game: NextGame | None
    season_stats: SeasonStats


class RosterBucket(BaseModel):
    label: str
    total_projected_fps_per_game: float
    players: list[RosterPlayerView]


class TeamResponse(BaseModel):
    league_id: int
    league_name: str
    team_name: str
    manager_name: str | None
    starters: RosterBucket
    bench: RosterBucket
    ir: RosterBucket
    total_projected_fps_per_game: float


@router.get("/{league_id}", response_model=TeamResponse)
async def get_team(
    league_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
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

    # Projections (per-game horizon)
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
        # Take the most recent as_of_date if duplicates exist
        prev = stats_by_player.setdefault(s.player_id, {})
        prev[s.stat_id] = float(s.value)

    # Schedule for next 14 days — bucket by team to share across players
    today = datetime.now(timezone.utc).date()
    until = today + timedelta(days=14)
    teams_in_roster = {p.nba_team_abbr for _, p in roster_rows if p.nba_team_abbr}
    games_by_team: dict[str, list[NbaSchedule]] = {}
    if teams_in_roster:
        schedule = (
            await db.execute(
                select(NbaSchedule).where(
                    NbaSchedule.game_date >= today,
                    NbaSchedule.game_date < until,
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
    total_fps = 0.0

    for rp, p in roster_rows:
        proj = proj_by_player.get(p.id)
        fps = float(proj.projected_value) if proj and proj.projected_value else None
        if fps is not None:
            total_fps += fps

        team_games = games_by_team.get(p.nba_team_abbr or "", [])
        b2b = 0
        prev_date = None
        for g in team_games:
            if prev_date is not None and (g.game_date - prev_date).days == 1:
                b2b += 1
            prev_date = g.game_date

        next_game: NextGame | None = None
        next_window = [g for g in team_games if g.game_date >= today]
        if next_window:
            g = next_window[0]
            is_home = g.home_team_abbr == p.nba_team_abbr
            next_game = NextGame(
                date=g.game_date.isoformat(),
                opponent=g.away_team_abbr if is_home else g.home_team_abbr,
                home=is_home,
                status=g.status,
                tipoff_at=g.tipoff_at.isoformat() if g.tipoff_at else None,
                is_today=g.game_date == today,
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
            projected_fps_per_game=fps,
            games_this_week=len(team_games),
            back_to_back_count=b2b,
            next_game=next_game,
            season_stats=season,
        )

        bucket_key = SLOT_BUCKET.get((rp.selected_position or "").upper(), "starters")
        buckets[bucket_key].append(view)

    # Sort each bucket by slot order
    for key in buckets:
        buckets[key].sort(key=lambda v: _slot_weight(v.selected_position))

    def _make_bucket(label: str, players: list[RosterPlayerView]) -> RosterBucket:
        total = round(sum(v.projected_fps_per_game or 0 for v in players), 1)
        return RosterBucket(label=label, total_projected_fps_per_game=total, players=players)

    return TeamResponse(
        league_id=league.id,
        league_name=league.name,
        team_name=my_team.name,
        manager_name=my_team.manager_name,
        starters=_make_bucket("Starters", buckets["starters"]),
        bench=_make_bucket("Bench", buckets["bench"]),
        ir=_make_bucket("Injured Reserve", buckets["ir"]),
        total_projected_fps_per_game=round(total_fps, 1),
    )
