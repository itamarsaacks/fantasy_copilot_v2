"""New endpoints introduced by the data-foundation reformation.

Per master plan §2.8:
  GET  /api/standings?league_id=N&date=YYYY-MM-DD
  GET  /api/teams/{team_id}/roster?date=YYYY-MM-DD
  GET  /api/waiver-planner/candidates?league_id=N&dates=YYYY-MM-DD,YYYY-MM-DD
  POST /api/team/simulate

All Postgres-only reads. Auth scoped by (user_id, league_key).
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import (
    FreeAgent,
    League,
    NbaSchedule,
    Player,
    ProjectionCache,
    RosterPlayer,
    Team,
    User,
)
from app.engine.projection import (
    _CategoryValuator,
    _PointsValuator,
    CATEGORY_LEAGUE_TYPES,
    POINTS_LEAGUE_TYPES,
)
from app.security import get_current_user
from app.services.clock import resolve_today
from app.services.game_logs import get_logs_for_players_on_date
from app.services.projection_window import (
    project_fps_for_window,
    project_fps_on_date,
)
from app.services.roster_history import roster_at
from app.services.standings import standings_at

router = APIRouter(tags=["foundation"])


# ===========================================================================
# Standings-on-date
# ===========================================================================


class StandingOnDate(BaseModel):
    team_id: int
    team_name: str
    manager_name: str | None
    fps_on_date: float | None
    rank_on_date: int


class StandingsResponse(BaseModel):
    league_id: int
    on_date: str
    standings: list[StandingOnDate]


@router.get("/api/standings", response_model=StandingsResponse)
async def standings_on_date(
    league_id: int = Query(...),
    date: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> StandingsResponse:
    target = date_type.fromisoformat(date) if date else resolve_today()
    league = (
        await db.execute(
            select(League).where(
                League.id == league_id, League.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if league is None:
        raise HTTPException(404, "league not found")

    rows = await standings_at(db, league_id, target)
    return StandingsResponse(
        league_id=league_id,
        on_date=target.isoformat(),
        standings=[
            StandingOnDate(
                team_id=r.team_id,
                team_name=r.team_name,
                manager_name=r.manager_name,
                fps_on_date=r.fps_on_date,
                rank_on_date=r.rank_on_date,
            )
            for r in rows
        ],
    )


# ===========================================================================
# Team roster on date
# ===========================================================================


class RosterPlayerView(BaseModel):
    player_id: int
    full_name: str
    nba_team_abbr: str | None
    headshot_path: str | None
    # FPS computed via the league's scoring rules for `on_date`. `null`
    # means the player did not play (DNP) or has no game-log row.
    fps_on_date: float | None = None
    did_not_play: bool = False


class TeamRosterResponse(BaseModel):
    team_id: int
    team_name: str
    on_date: str
    players: list[RosterPlayerView]


@router.get(
    "/api/teams/{team_id}/roster", response_model=TeamRosterResponse
)
async def team_roster_on_date(
    team_id: int,
    date: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TeamRosterResponse:
    target = date_type.fromisoformat(date) if date else resolve_today()

    # Auth: confirm caller owns the league this team lives in
    team = (
        await db.execute(select(Team).where(Team.id == team_id))
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(404, "team not found")
    league = (
        await db.execute(
            select(League).where(
                League.id == team.league_id, League.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if league is None:
        raise HTTPException(403, "not your league")

    slots = await roster_at(db, team_id, target)
    if not slots:
        return TeamRosterResponse(
            team_id=team_id, team_name=team.name, on_date=target.isoformat(), players=[]
        )

    player_ids = [s.player_id for s in slots]
    players = (
        (await db.execute(select(Player).where(Player.id.in_(player_ids))))
        .scalars()
        .all()
    )
    by_id = {p.id: p for p in players}

    # Compute per-player FPS-on-date using this league's scoring rules.
    settings = league.settings_json or {}
    valuator = None
    if league.scoring_type in POINTS_LEAGUE_TYPES:
        valuator = _PointsValuator.from_settings(settings)
    elif league.scoring_type in CATEGORY_LEAGUE_TYPES:
        valuator = _CategoryValuator.from_settings(settings)

    fps_by_player: dict[int, float | None] = {}
    dnp_by_player: dict[int, bool] = {}
    if valuator is not None:
        logs = await get_logs_for_players_on_date(db, player_ids, target)
        for pid in player_ids:
            row = logs.get(pid)
            if row is None:
                fps_by_player[pid] = None
                dnp_by_player[pid] = False
                continue
            if row.did_not_play:
                fps_by_player[pid] = None
                dnp_by_player[pid] = True
                continue
            box_floats = {
                k: float(v)
                for k, v in (row.box or {}).items()
                if isinstance(v, (int, float))
            }
            if not box_floats:
                fps_by_player[pid] = None
                dnp_by_player[pid] = False
                continue
            fps_one, _ = valuator.season_total(box_floats)
            fps_by_player[pid] = (
                round(float(fps_one), 2) if fps_one is not None else None
            )
            dnp_by_player[pid] = False

    return TeamRosterResponse(
        team_id=team_id,
        team_name=team.name,
        on_date=target.isoformat(),
        players=[
            RosterPlayerView(
                player_id=p.id,
                full_name=p.full_name,
                nba_team_abbr=p.nba_team_abbr,
                headshot_path=p.headshot_path,
                fps_on_date=fps_by_player.get(p.id),
                did_not_play=dnp_by_player.get(p.id, False),
            )
            for p in (by_id[s.player_id] for s in slots if s.player_id in by_id)
        ],
    )


# ===========================================================================
# Waiver-planner candidates
# ===========================================================================


class WaiverCandidate(BaseModel):
    player_id: int
    full_name: str
    nba_team_abbr: str | None
    position: str | None
    headshot_path: str | None
    games_on_selected_dates: int
    projected_fps_window: float


class WaiverPlannerResponse(BaseModel):
    league_id: int
    selected_dates: list[str]
    candidates: list[WaiverCandidate]


@router.get(
    "/api/waiver-planner/candidates", response_model=WaiverPlannerResponse
)
async def waiver_planner_candidates(
    league_id: int = Query(...),
    dates: str = Query(..., description="comma-separated YYYY-MM-DD"),
    top_n: int = Query(default=25, le=100),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WaiverPlannerResponse:
    """For each FA in the league, sum projected FPS across the selected dates.

    Result is ranked descending. Players with zero games across selected
    dates are excluded — blank-state UI message lives client-side ("no
    teams playing those dates" if EVERY FA returns 0).
    """
    league = (
        await db.execute(
            select(League).where(
                League.id == league_id, League.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if league is None:
        raise HTTPException(404, "league not found")

    selected_dates = [date_type.fromisoformat(d) for d in dates.split(",") if d]
    if not selected_dates:
        raise HTTPException(400, "dates must include at least one YYYY-MM-DD")

    fa_rows = (
        (
            await db.execute(
                select(FreeAgent, Player)
                .join(Player, FreeAgent.player_id == Player.id)
                .where(FreeAgent.league_id == league_id)
            )
        )
        .all()
    )

    candidates: list[WaiverCandidate] = []
    for fa, player in fa_rows:
        if not player.nba_team_abbr:
            continue
        games_q = (
            await db.execute(
                select(NbaSchedule.game_date)
                .where(NbaSchedule.game_date.in_(selected_dates))
                .where(
                    or_(
                        NbaSchedule.home_team_abbr == player.nba_team_abbr,
                        NbaSchedule.away_team_abbr == player.nba_team_abbr,
                    )
                )
            )
        ).all()
        games = len(games_q)
        if games == 0:
            continue
        projected = await project_fps_for_window(
            db, player.id, league_id, selected_dates
        )
        candidates.append(
            WaiverCandidate(
                player_id=player.id,
                full_name=player.full_name,
                nba_team_abbr=player.nba_team_abbr,
                position=player.primary_position,
                headshot_path=player.headshot_path,
                games_on_selected_dates=games,
                projected_fps_window=float(projected),
            )
        )

    candidates.sort(key=lambda c: -c.projected_fps_window)
    return WaiverPlannerResponse(
        league_id=league_id,
        selected_dates=[d.isoformat() for d in selected_dates],
        candidates=candidates[:top_n],
    )


# ===========================================================================
# Lineup what-if simulator
# ===========================================================================


class Swap(BaseModel):
    out_player_id: int
    in_player_id: int


class SimulateRequest(BaseModel):
    league_id: int
    dates: list[str] = Field(..., description="YYYY-MM-DD")
    swaps: list[Swap] = Field(default_factory=list)


class SimulateResponse(BaseModel):
    league_id: int
    dates: list[str]
    baseline_fps: float
    simulated_fps: float
    delta: float
    per_player_delta: dict[int, float]


@router.post("/api/team/simulate", response_model=SimulateResponse)
async def simulate_lineup(
    payload: SimulateRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SimulateResponse:
    """What-if: swap N players in/out, compute projected FPS over `dates`.

    `baseline_fps`  = user's current roster projection summed over `dates`.
    `simulated_fps` = after applying every swap.
    `delta`         = simulated - baseline.
    `per_player_delta` = contribution change keyed by added player_id.
    """
    league = (
        await db.execute(
            select(League).where(
                League.id == payload.league_id, League.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if league is None:
        raise HTTPException(404, "league not found")

    dates = [date_type.fromisoformat(d) for d in payload.dates]
    if not dates:
        raise HTTPException(400, "dates required")

    # Current roster
    my_team = (
        await db.execute(
            select(Team).where(
                Team.league_id == payload.league_id, Team.is_user_team.is_(True)
            )
        )
    ).scalar_one_or_none()
    if my_team is None:
        raise HTTPException(404, "no user team in league")

    roster_ids = [
        pid
        for (pid,) in (
            await db.execute(
                select(RosterPlayer.player_id).where(
                    RosterPlayer.team_id == my_team.id
                )
            )
        ).all()
    ]

    async def total_for(player_ids: list[int]) -> Decimal:
        total = Decimal(0)
        for pid in player_ids:
            total += await project_fps_for_window(
                db, pid, payload.league_id, dates
            )
        return total

    baseline = await total_for(roster_ids)

    sim_ids = list(roster_ids)
    per_player_delta: dict[int, float] = {}
    for swap in payload.swaps:
        if swap.out_player_id in sim_ids:
            sim_ids.remove(swap.out_player_id)
            out_proj = await project_fps_for_window(
                db, swap.out_player_id, payload.league_id, dates
            )
            per_player_delta[swap.out_player_id] = float(-out_proj)
        sim_ids.append(swap.in_player_id)
        in_proj = await project_fps_for_window(
            db, swap.in_player_id, payload.league_id, dates
        )
        per_player_delta[swap.in_player_id] = float(in_proj)

    simulated = await total_for(sim_ids)
    return SimulateResponse(
        league_id=payload.league_id,
        dates=[d.isoformat() for d in dates],
        baseline_fps=float(baseline),
        simulated_fps=float(simulated),
        delta=float(simulated - baseline),
        per_player_delta=per_player_delta,
    )
