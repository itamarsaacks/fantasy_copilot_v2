"""Games + NBA-standings endpoints — backs the Games tab (master plan §2.8).

Endpoints:
  GET  /api/games?date=YYYY-MM-DD
  GET  /api/games/{game_id}/box?league_id=N    (FPS computed per caller's league)
  GET  /api/nba/standings                       (conference standings — TODO Step 8.1)

All reads are Postgres-only — no live ESPN/Yahoo at request time.
Schedule + scores come from `nba_schedule` (synced by sync_schedule.py).
Box scores come from `nba_game_logs` (synced by sync_game_logs.py).
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import (
    League,
    NbaGameLog,
    NbaSchedule,
    Player,
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

router = APIRouter(prefix="/api/games", tags=["games"])


class GameTeam(BaseModel):
    abbr: str
    score: int | None
    is_home: bool


class GameSummary(BaseModel):
    game_id: str
    game_date: str
    status: str | None  # 'scheduled' | 'live' | 'final'
    tipoff_at: str | None
    home: GameTeam
    away: GameTeam


class GamesResponse(BaseModel):
    date: str
    games: list[GameSummary]


@router.get("", response_model=GamesResponse)
async def list_games(
    date: str | None = Query(default=None, description="YYYY-MM-DD; defaults to resolve_today()"),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> GamesResponse:
    """All NBA games on `date`. Empty list if no games (off-day)."""
    target = (
        date_type.fromisoformat(date)
        if date
        else resolve_today()
    )
    rows = (
        (
            await db.execute(
                select(NbaSchedule)
                .where(NbaSchedule.game_date == target)
                .order_by(NbaSchedule.tipoff_at.asc().nulls_last())
            )
        )
        .scalars()
        .all()
    )
    games = [
        GameSummary(
            game_id=g.game_id,
            game_date=g.game_date.isoformat(),
            status=g.status,
            tipoff_at=g.tipoff_at.isoformat() if g.tipoff_at else None,
            home=GameTeam(
                abbr=g.home_team_abbr,
                score=g.home_score,
                is_home=True,
            ),
            away=GameTeam(
                abbr=g.away_team_abbr,
                score=g.away_score,
                is_home=False,
            ),
        )
        for g in rows
    ]
    return GamesResponse(date=target.isoformat(), games=games)


class BoxLine(BaseModel):
    player_id: int
    full_name: str
    nba_team_abbr: str | None
    headshot_path: str | None
    minutes: float | None
    stats: dict[str, float]
    fantasy_points: float | None
    did_not_play: bool


class BoxResponse(BaseModel):
    game_id: str
    game_date: str
    home_abbr: str
    away_abbr: str
    home: list[BoxLine]
    away: list[BoxLine]


@router.get("/{game_id}/box", response_model=BoxResponse)
async def box_score(
    game_id: str,
    league_id: int | None = Query(default=None, description="Optional — compute fantasy_points per this league's scoring"),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> BoxResponse:
    """Per-player box score for a single NBA game.

    If `league_id` is provided AND owned by the caller, `fantasy_points`
    is computed via that league's scoring rules. Otherwise FPS is null.
    """
    sched = (
        await db.execute(select(NbaSchedule).where(NbaSchedule.game_id == game_id))
    ).scalar_one_or_none()
    if sched is None:
        raise HTTPException(404, f"game {game_id} not found")

    # Get all logs for this game
    logs = (
        (
            await db.execute(
                select(NbaGameLog, Player)
                .join(Player, NbaGameLog.player_id == Player.id)
                .where(NbaGameLog.game_id == game_id)
            )
        )
        .all()
    )

    # Pick valuator if league_id given + owned by caller
    valuator = None
    if league_id is not None:
        league = (
            await db.execute(
                select(League).where(
                    League.id == league_id, League.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if league is not None:
            settings = league.settings_json or {}
            if league.scoring_type in POINTS_LEAGUE_TYPES:
                valuator = _PointsValuator.from_settings(settings)
            elif league.scoring_type in CATEGORY_LEAGUE_TYPES:
                valuator = _CategoryValuator.from_settings(settings)

    home_lines: list[BoxLine] = []
    away_lines: list[BoxLine] = []
    for log_row, player in logs:
        box = log_row.box or {}
        stats = {k: float(v) for k, v in box.items() if isinstance(v, (int, float))}
        fps: float | None = None
        if valuator is not None and stats and not log_row.did_not_play:
            fps_raw, _ = valuator.season_total(stats)
            if fps_raw is not None:
                fps = round(float(fps_raw), 2)
        line = BoxLine(
            player_id=player.id,
            full_name=player.full_name,
            nba_team_abbr=player.nba_team_abbr,
            headshot_path=player.headshot_path,
            minutes=float(log_row.minutes) if log_row.minutes is not None else None,
            stats=stats,
            fantasy_points=fps,
            did_not_play=bool(log_row.did_not_play),
        )
        if player.nba_team_abbr == sched.home_team_abbr:
            home_lines.append(line)
        else:
            away_lines.append(line)

    # Sort each team's box by minutes desc, then name
    def _key(b: BoxLine) -> tuple[float, str]:
        return (-(b.minutes or 0.0), b.full_name)

    home_lines.sort(key=_key)
    away_lines.sort(key=_key)

    return BoxResponse(
        game_id=sched.game_id,
        game_date=sched.game_date.isoformat(),
        home_abbr=sched.home_team_abbr,
        away_abbr=sched.away_team_abbr,
        home=home_lines,
        away=away_lines,
    )
