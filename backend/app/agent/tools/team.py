"""Tools that read OTHER fantasy teams' rosters."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlalchemy import select

from app.agent.tools._helpers import fold_ascii, get_context, player_view
from app.db.engine import SessionLocal
from app.db.models import League, Player, RosterPlayer, Team


@tool
async def get_team_roster(team_name_or_manager: str, config: RunnableConfig) -> dict[str, Any]:
    """Return the roster of any team in the league by team name or manager nickname.

    Args:
      team_name_or_manager: a team name OR a manager's display name. Case-insensitive
        substring match. If multiple teams match, returns an `ambiguous` list.

    Output: team_name, manager, rank, wins/losses/ties, points_for/against,
            players (same shape as get_my_roster).

    Use this when the user asks about a specific opposing team — "who has SGA",
    "what's on Rob's team", "show me Nathan's roster".
    """
    user_id, league_id = get_context(config)
    needle = fold_ascii(team_name_or_manager)
    if not needle:
        return {"error": "empty search term"}

    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

        # Pull all teams (≤16 per league) and fuzzy-match — handles non-ASCII
        # team / manager names like 'איתמר's Swell Team' if user types 'itamar'.
        teams = (
            await db.execute(select(Team).where(Team.league_id == league_id))
        ).scalars().all()
        matches = [
            t
            for t in teams
            if needle in fold_ascii(t.name) or needle in fold_ascii(t.manager_name)
        ]

        if not matches:
            return {"error": f"no team or manager matched '{team_name_or_manager}'"}
        if len(matches) > 1:
            return {
                "ambiguous": [
                    {"team_name": t.name, "manager": t.manager_name, "rank": t.rank}
                    for t in matches
                ]
            }

        team = matches[0]
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
            "rank": team.rank,
            "wins": team.wins,
            "losses": team.losses,
            "ties": team.ties,
            "points_for": float(team.points_for) if team.points_for else None,
            "points_against": float(team.points_against) if team.points_against else None,
            "is_user_team": team.is_user_team,
            "players": [
                {**player_view(p), "selected_position": rp.selected_position}
                for rp, p in rows
            ],
        }
