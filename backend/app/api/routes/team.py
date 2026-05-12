"""Team-tab endpoint — user's roster with projections + status + schedule.

GET /api/team/{league_id} returns the user's roster grouped by position,
with each player's projection, status, and games-this-week from existing
DB tables. Read-only, no agent involvement. Powers the Team tab UI.
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
    ProjectionCache,
    RosterPlayer,
    Team,
    User,
)
from app.security import get_current_user

router = APIRouter(prefix="/api/team", tags=["team"])


class RosterPlayerView(BaseModel):
    name: str
    nba_team: str | None
    primary_position: str | None
    eligible_positions: list[str]
    selected_position: str | None
    status: str | None
    status_full: str | None
    injury_note: str | None
    percent_owned: float | None
    projected_fps_per_game: float | None
    games_this_week: int
    back_to_back_count: int


class TeamResponse(BaseModel):
    league_id: int
    league_name: str
    team_name: str
    manager_name: str | None
    by_position: dict[str, list[RosterPlayerView]]
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
    proj_rows = (
        (
            await db.execute(
                select(ProjectionCache).where(
                    ProjectionCache.league_id == league_id,
                    ProjectionCache.horizon == "per_game",
                    ProjectionCache.player_id.in_(player_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    proj_by_player = {p.player_id: p for p in proj_rows}

    # Pull next 7 days of schedule once, bucket by team — same trick as the
    # agent tool. Avoids N queries.
    today = datetime.now(timezone.utc).date()
    until = today + timedelta(days=7)
    teams_in_roster = {p.nba_team_abbr for _, p in roster_rows if p.nba_team_abbr}
    games_by_team: dict[str, list[NbaSchedule]] = {}
    if teams_in_roster:
        schedule = (
            (
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
            )
            .scalars()
            .all()
        )
        for g in sorted(schedule, key=lambda x: x.game_date):
            games_by_team.setdefault(g.home_team_abbr, []).append(g)
            games_by_team.setdefault(g.away_team_abbr, []).append(g)

    by_position: dict[str, list[RosterPlayerView]] = {}
    total_fps = 0.0

    for rp, p in roster_rows:
        proj = proj_by_player.get(p.id)
        fps = float(proj.projected_value) if proj and proj.projected_value else None
        if fps is not None:
            total_fps += fps

        team_games = games_by_team.get(p.nba_team_abbr or "", [])
        b2b = 0
        prev = None
        for g in team_games:
            if prev is not None and (g.game_date - prev).days == 1:
                b2b += 1
            prev = g.game_date

        view = RosterPlayerView(
            name=p.full_name,
            nba_team=p.nba_team_abbr,
            primary_position=p.primary_position,
            eligible_positions=p.eligible_positions or [],
            selected_position=rp.selected_position,
            status=p.status,
            status_full=p.status_full,
            injury_note=p.injury_note,
            percent_owned=float(p.percent_owned) if p.percent_owned is not None else None,
            projected_fps_per_game=fps,
            games_this_week=len(team_games),
            back_to_back_count=b2b,
        )

        # Bucket by primary_position. Two-position eligibility (G/F, F/C) is
        # informational — the grid shows them under their primary, the player
        # card surfaces full eligibility.
        bucket = (p.primary_position or "OTHER").upper()
        by_position.setdefault(bucket, []).append(view)

    # Sort each bucket by projection desc
    for bucket in by_position.values():
        bucket.sort(
            key=lambda v: (v.projected_fps_per_game or 0.0), reverse=True
        )

    return TeamResponse(
        league_id=league.id,
        league_name=league.name,
        team_name=my_team.name,
        manager_name=my_team.manager_name,
        by_position=by_position,
        total_projected_fps_per_game=round(total_fps, 1),
    )
