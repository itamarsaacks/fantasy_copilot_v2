"""Tools that read the user's own roster."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlalchemy import select

from app.agent.tools._helpers import get_context, player_view
from app.db.engine import SessionLocal
from app.db.models import League, Player, RosterPlayer, Team


@tool
async def get_my_roster(config: RunnableConfig) -> dict[str, Any]:
    """Return the user's fantasy roster in the currently-selected league.

    Output:
      - team_name, manager, league_name, league_scoring_type
      - players: list of {name, nba_team, primary_position, eligible_positions,
                          selected_position, status, percent_owned}

    Use this when the user asks anything about their own team — who's on it,
    who's starting, who's hurt, position breakdown.
    """
    user_id, league_id = get_context(config)
    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

        team_q = await db.execute(
            select(Team).where(Team.league_id == league_id, Team.is_user_team.is_(True))
        )
        team = team_q.scalar_one_or_none()
        if team is None:
            return {"error": "user does not have a team in this league"}

        rows = (
            await db.execute(
                select(RosterPlayer, Player)
                .join(Player, Player.id == RosterPlayer.player_id)
                .where(RosterPlayer.team_id == team.id)
            )
        ).all()

        return {
            "team_name": team.name,
            "manager": team.manager_name,
            "league_name": league.name,
            "league_scoring_type": league.scoring_type,
            "players": [
                {**player_view(p), "selected_position": rp.selected_position}
                for rp, p in rows
            ],
        }
