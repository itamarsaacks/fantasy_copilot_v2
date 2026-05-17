"""Trades tab — builder data endpoint.

GET /api/trades/{league_id} returns everything the frontend needs to
present a trade builder:

  my_team   the user's team + roster + per-game projections
  partners  every other team in the league with same shape

Deltas (give vs receive) are computed client-side by summing fps
per-game for the selected players on each side — keeps the endpoint
pure and cacheable.

Out of scope for v1 (see BACKLOG → Trades tab):
- Trade history view (no ingest yet)
- Submitting a real proposal to Yahoo (needs write OAuth scope)
- Server-side position-eligibility validation ("you'd be left with no PG")
- Auto-suggesting trade partners based on roster gaps
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import (
    League,
    Player,
    ProjectionCache,
    RosterPlayer,
    Team,
    User,
)
from app.security import get_current_user

router = APIRouter(prefix="/api/trades", tags=["trades"])


class TradePlayer(BaseModel):
    player_id: int
    name: str
    nba_team: str | None
    eligible_positions: list[str]
    selected_position: str | None
    status: str | None
    injury_note: str | None
    projected_fps_per_game: float | None


class TradeTeam(BaseModel):
    team_id: int
    name: str
    manager_name: str | None
    is_user_team: bool
    players: list[TradePlayer]


class TradesBuilderResponse(BaseModel):
    league_id: int
    league_name: str
    scoring_type: str
    my_team: TradeTeam | None
    partners: list[TradeTeam]


@router.get("/{league_id}", response_model=TradesBuilderResponse)
async def get_trades_builder(
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
        raise HTTPException(404, "league not found")

    teams = (
        await db.execute(
            select(Team)
            .where(Team.league_id == league_id)
            .order_by(Team.is_user_team.desc(), Team.name.asc())
        )
    ).scalars().all()
    if not teams:
        return TradesBuilderResponse(
            league_id=league_id,
            league_name=league.name,
            scoring_type=league.scoring_type,
            my_team=None,
            partners=[],
        )

    team_ids = [t.id for t in teams]

    # Roster rows for every team in the league (one query).
    roster_rows = (
        await db.execute(
            select(RosterPlayer, Player)
            .join(Player, Player.id == RosterPlayer.player_id)
            .where(RosterPlayer.team_id.in_(team_ids))
        )
    ).all()

    # Bucket roster rows by team_id.
    by_team: dict[int, list[tuple[RosterPlayer, Player]]] = {}
    all_player_ids: list[int] = []
    for rp, p in roster_rows:
        by_team.setdefault(rp.team_id, []).append((rp, p))
        all_player_ids.append(p.id)

    # Projections in one query.
    proj_by_player: dict[int, float] = {}
    if all_player_ids:
        proj_rows = (
            await db.execute(
                select(ProjectionCache).where(
                    ProjectionCache.league_id == league_id,
                    ProjectionCache.horizon == "per_game",
                    ProjectionCache.player_id.in_(all_player_ids),
                )
            )
        ).scalars().all()
        for proj in proj_rows:
            if proj.projected_value is not None:
                proj_by_player[proj.player_id] = float(proj.projected_value)

    def _team_view(t: Team) -> TradeTeam:
        rows = by_team.get(t.id, [])
        # Sort: starters by slot order then bench/IR; simplest: keep DB
        # order. Trade UI doesn't need lineup-slot grouping.
        players = [
            TradePlayer(
                player_id=p.id,
                name=p.full_name,
                nba_team=p.nba_team_abbr,
                eligible_positions=p.eligible_positions or [],
                selected_position=rp.selected_position,
                status=p.status,
                injury_note=p.injury_note,
                projected_fps_per_game=(
                    round(proj_by_player[p.id], 2) if p.id in proj_by_player else None
                ),
            )
            for rp, p in rows
        ]
        # Most-valuable player first within each team.
        players.sort(
            key=lambda v: (
                v.projected_fps_per_game is None,
                -(v.projected_fps_per_game or 0.0),
                v.name,
            )
        )
        return TradeTeam(
            team_id=t.id,
            name=t.name,
            manager_name=t.manager_name,
            is_user_team=t.is_user_team,
            players=players,
        )

    my_team: TradeTeam | None = None
    partners: list[TradeTeam] = []
    for t in teams:
        tv = _team_view(t)
        if t.is_user_team and my_team is None:
            my_team = tv
        else:
            partners.append(tv)

    return TradesBuilderResponse(
        league_id=league_id,
        league_name=league.name,
        scoring_type=league.scoring_type,
        my_team=my_team,
        partners=partners,
    )
