"""Roster-reading tools for the deep agent.

Each tool reads (user_id, league_id) from the LangChain RunnableConfig at
call time. That is how we keep the agent stateless and instantiate it once.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlalchemy import select

from app.db.engine import SessionLocal
from app.db.models import League, Player, RosterPlayer, Team, User


def _ctx(config: RunnableConfig) -> tuple[int, int]:
    """Pull (user_id, league_id) from config. Raises if either is missing."""
    cfg = (config or {}).get("configurable") or {}
    user_id = cfg.get("user_id")
    league_id = cfg.get("league_id")
    if not user_id or not league_id:
        raise ValueError("agent config missing user_id or league_id")
    return int(user_id), int(league_id)


@tool
async def get_my_roster(config: RunnableConfig) -> dict[str, Any]:
    """Return the user's fantasy roster in their currently-selected league.

    Output is a dict with fields:
      - team_name: the user's team name
      - manager: the user's manager nickname
      - league_name: the league the team is in
      - league_scoring_type: e.g. point, headpoint, head, roto
      - players: a list of {name, nba_team, primary_position, eligible_positions,
                            selected_position, status (e.g. INJ/GTD/null),
                            percent_owned}

    Use this when the user asks anything about their own roster — who they have,
    who is starting, who is hurt, etc. The data is fresh as of the last sync.
    """
    user_id, league_id = _ctx(config)
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        league = await db.get(League, league_id)
        if not user or not league or league.user_id != user_id:
            return {"error": "league not found for this user"}

        team_q = await db.execute(
            select(Team).where(Team.league_id == league.id, Team.is_user_team.is_(True))
        )
        team = team_q.scalar_one_or_none()
        if team is None:
            return {"error": "user does not have a team in this league"}

        rows_q = await db.execute(
            select(RosterPlayer, Player)
            .join(Player, Player.id == RosterPlayer.player_id)
            .where(RosterPlayer.team_id == team.id)
        )
        rows = rows_q.all()

        return {
            "team_name": team.name,
            "manager": team.manager_name,
            "league_name": league.name,
            "league_scoring_type": league.scoring_type,
            "players": [
                {
                    "name": p.full_name,
                    "nba_team": p.nba_team_abbr,
                    "primary_position": p.primary_position,
                    "eligible_positions": p.eligible_positions,
                    "selected_position": rp.selected_position,
                    "status": p.status,
                    "percent_owned": float(p.percent_owned) if p.percent_owned else None,
                }
                for rp, p in rows
            ],
        }
