"""Tools for finding any individual player."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlalchemy import select

from app.agent.tools._helpers import fold_ascii, get_context, player_view
from app.db.engine import SessionLocal
from app.db.models import FreeAgent, League, Player, RosterPlayer, Team


@tool
async def find_player(name: str, config: RunnableConfig) -> dict[str, Any]:
    """Look up an NBA player by name and return identity + their ownership in the
    user's league (rostered, free agent, or unknown to this league).

    Args:
      name: player name; case-insensitive substring match. Returns ambiguous
        list if more than one player matches.

    Output: when one player matches:
      {name, nba_team, primary_position, eligible_positions, status,
       percent_owned, draft_avg_pick, draft_percent_drafted,
       ownership: {kind: "rostered"|"free_agent"|"unknown",
                   team_name?, manager?, selected_position?}}

    Use this for: "tell me about Player X", "who has Player X", "is X on waivers".
    """
    user_id, league_id = get_context(config)
    needle = fold_ascii(name)
    if not needle:
        return {"error": "empty player name"}

    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

        # Pull all players and fuzzy-match in Python (~720 rows, trivial cost,
        # handles diacritics like Nikola Jokić correctly).
        all_players = (await db.execute(select(Player))).scalars().all()
        matches = [p for p in all_players if needle in fold_ascii(p.full_name)]

        if not matches:
            return {"error": f"no player matched '{name}'"}
        if len(matches) > 1:
            return {
                "ambiguous": [
                    {"name": p.full_name, "nba_team": p.nba_team_abbr}
                    for p in matches[:10]
                ]
            }

        p = matches[0]
        out = player_view(p, include_draft=True)

        # Determine ownership in this league
        roster_q = await db.execute(
            select(RosterPlayer, Team)
            .join(Team, Team.id == RosterPlayer.team_id)
            .where(RosterPlayer.player_id == p.id, Team.league_id == league_id)
        )
        roster_row = roster_q.first()
        if roster_row:
            rp, team = roster_row
            out["ownership"] = {
                "kind": "rostered",
                "team_name": team.name,
                "manager": team.manager_name,
                "selected_position": rp.selected_position,
                "is_user_team": team.is_user_team,
            }
        else:
            fa_q = await db.execute(
                select(FreeAgent).where(
                    FreeAgent.player_id == p.id, FreeAgent.league_id == league_id
                )
            )
            if fa_q.scalar_one_or_none():
                out["ownership"] = {"kind": "free_agent"}
            else:
                out["ownership"] = {"kind": "unknown"}
        return out
