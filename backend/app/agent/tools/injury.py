"""Bulk injury-status lookup.

Returns Yahoo-sourced status + description + note for many players at once.
Designed to replace web search for "is X playing", "what's the latest on Y",
and FA-screening flows where the agent would otherwise fire a Tavily query
per injured player. ~$0.10 saved per news call, and the data is structured.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlalchemy import select

from app.agent.tools._helpers import fold_ascii, get_context
from app.db.engine import SessionLocal
from app.db.models import League, Player


@tool
async def get_injury_status(
    names: list[str], config: RunnableConfig
) -> dict[str, Any]:
    """Bulk-lookup injury status for one or more NBA players.

    Returns Yahoo-sourced status data: the short flag (INJ/GTD/OUT/DTD/IL/
    active), the longer description ("Day-To-Day", "Out", "Doubtful"), and
    any free-text injury note (cause, expected return).

    PREFER THIS TOOL over search_recent_news whenever the user is asking
    about availability / injury / "is X playing" — Yahoo updates within
    minutes of news breaking and the data is structured. Only fall back
    to web search if a player's status is missing, stale, or the user
    explicitly asks for news beyond the status.

    Args:
      names: one or more player names. Case + diacritic insensitive,
        substring match. Pass multiple names to screen a whole list at
        once (e.g. top-10 FAs).

    Output:
      {players: [{name, nba_team, status, status_full, injury_note,
                  playing_likely: bool}, ...],
       unresolved: [name, ...]}
      `playing_likely` is True for active/DTD/GTD; False for OUT/IL.
    """
    user_id, league_id = get_context(config)
    if not names:
        return {"error": "no names provided"}

    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

        all_players = (await db.execute(select(Player))).scalars().all()
        results: list[dict[str, Any]] = []
        unresolved: list[str] = []

        for raw in names:
            needle = fold_ascii(raw)
            if not needle:
                continue
            matches = [p for p in all_players if needle in fold_ascii(p.full_name)]
            if not matches:
                unresolved.append(raw)
                continue
            # If ambiguous, take the most-owned one (best heuristic when the
            # user says "Smith" and there are three Smiths).
            if len(matches) > 1:
                matches.sort(
                    key=lambda p: float(p.percent_owned or 0), reverse=True
                )
            p = matches[0]
            results.append(_format(p))

        return {"players": results, "unresolved": unresolved}


# OUT-like statuses where the player won't play. Yahoo's short flag.
_OUT_STATUSES = {"OUT", "O", "IL", "IL-LT", "NA", "SUSP"}


def _format(p: Player) -> dict[str, Any]:
    status = (p.status or "").upper()
    playing_likely = status not in _OUT_STATUSES
    return {
        "name": p.full_name,
        "nba_team": p.nba_team_abbr,
        "status": p.status or "active",
        "status_full": p.status_full,
        "injury_note": p.injury_note,
        "playing_likely": playing_likely,
    }
