"""Tools that read the league's free-agent pool."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlalchemy import desc, select

from app.agent.tools._helpers import get_context, player_view
from app.db.engine import SessionLocal
from app.db.models import FreeAgent, League, Player


@tool
async def get_free_agents(
    config: RunnableConfig,
    position: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Return free agents in the user's league, ranked by Yahoo-global percent_owned.

    Args:
      position: optional position filter — PG, SG, SF, PF, C, G, F, FC. The filter
        matches against eligible_positions, so passing "G" finds anyone with G
        eligibility (PG/SG/G).
      limit: max rows to return (default 25, hard cap 100).

    Output:
      - count: number of FAs returned
      - total: total FAs in the league (regardless of filter)
      - players: list of {name, nba_team, primary_position, eligible_positions,
                          status, percent_owned, draft_avg_pick, draft_percent_drafted}

    Use this for waiver-pickup, "who's available", "best center on waivers".
    """
    user_id, league_id = get_context(config)
    limit = max(1, min(int(limit), 100))
    pos_filter = position.upper().strip() if position else None

    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

        total = (
            await db.execute(
                select(FreeAgent).where(FreeAgent.league_id == league_id)
            )
        ).scalars().all()
        total_count = len(total)

        # Pull a wide slice ordered by percent_owned, filter in Python (the
        # eligible_positions column is JSONB; a SQL contains-any would be
        # possible but this is clearer for a few hundred rows).
        rows = (
            await db.execute(
                select(FreeAgent, Player)
                .join(Player, Player.id == FreeAgent.player_id)
                .where(FreeAgent.league_id == league_id)
                .order_by(desc(Player.percent_owned).nullslast())
            )
        ).all()

        out: list[dict[str, Any]] = []
        for _fa, p in rows:
            if pos_filter:
                eligible = [pos.upper() for pos in (p.eligible_positions or [])]
                if pos_filter not in eligible:
                    continue
            out.append(player_view(p, include_draft=True))
            if len(out) >= limit:
                break

        return {"count": len(out), "total": total_count, "players": out}
