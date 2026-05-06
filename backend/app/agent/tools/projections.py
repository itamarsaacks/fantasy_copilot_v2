"""Projection-reading tools. Read from projection_cache populated by the
projection engine (app.engine.projection).
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlalchemy import desc, select

from app.agent.tools._helpers import fold_ascii, get_context, player_view
from app.db.engine import SessionLocal
from app.db.models import (
    FreeAgent,
    League,
    Player,
    ProjectionCache,
    RosterPlayer,
    Team,
)


@tool
async def get_player_projection(name: str, config: RunnableConfig) -> dict[str, Any]:
    """Return the league-rule-aware fantasy point value for a player.

    Args:
      name: player name. Case + diacritic insensitive.

    Output (when found):
      {name, nba_team, primary_position, status,
       horizon, projected_value (float fantasy points), components (dict
       {stat_id: contribution}), stale (bool), computed_at,
       ownership: {kind, team?, manager?}}

    horizon meaning:
      - "season_total" — the league-rule-weighted sum of season-to-date stats.
        For a "point" league this IS what determines standings. For "headpoint"
        it is the season-long total fantasy points scored.
      Use this output for ANY player-value question: comparing two players,
      trade evaluation, waiver decisions, "who scored more this season",
      "who is projected to score more rest-of-season."

    Components keys are Yahoo NBA stat_ids: 12=PTS, 15=REB, 16=AST, 17=STL,
    18=BLK, 19=TO. Each component is the post-modifier contribution (e.g.
    components["15"]=1003.2 means rebounds contributed 1003.2 fantasy points).

    Returns {"error": ...} if no projection exists yet.
    """
    user_id, league_id = get_context(config)
    needle = fold_ascii(name)
    if not needle:
        return {"error": "empty player name"}

    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

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
        player = matches[0]

        proj_q = await db.execute(
            select(ProjectionCache).where(
                ProjectionCache.player_id == player.id,
                ProjectionCache.league_id == league_id,
            )
        )
        proj = proj_q.scalar_one_or_none()
        if proj is None:
            return {
                "error": (
                    f"no projection for {player.full_name} yet — "
                    "stats sync or projection compute may not have run for this league"
                )
            }

        out = player_view(player, include_draft=False)
        out.update(
            {
                "horizon": proj.horizon,
                "projected_value": float(proj.projected_value)
                if proj.projected_value is not None
                else None,
                "components": proj.components,
                "stale": proj.stale,
                "computed_at": proj.computed_at.isoformat()
                if proj.computed_at
                else None,
            }
        )

        # Ownership
        roster_q = await db.execute(
            select(RosterPlayer, Team)
            .join(Team, Team.id == RosterPlayer.team_id)
            .where(
                RosterPlayer.player_id == player.id, Team.league_id == league_id
            )
        )
        roster_row = roster_q.first()
        if roster_row:
            _rp, team = roster_row
            out["ownership"] = {
                "kind": "rostered",
                "team": team.name,
                "manager": team.manager_name,
                "is_user_team": team.is_user_team,
            }
        else:
            fa = (
                await db.execute(
                    select(FreeAgent).where(
                        FreeAgent.player_id == player.id,
                        FreeAgent.league_id == league_id,
                    )
                )
            ).scalar_one_or_none()
            out["ownership"] = {"kind": "free_agent" if fa else "unknown"}
        return out


@tool
async def top_projected_free_agents(
    config: RunnableConfig,
    position: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Return the top free agents in this league ranked by projected per-game
    fantasy points (league-rule-aware).

    Args:
      position: optional eligibility filter (PG, SG, SF, PF, C, G, F, FC).
      limit: max rows (default 10, hard cap 50).

    Output: {count, players: [{name, nba_team, primary_position, status,
                               percent_owned, projected_value}, ...]}.

    Use this for waiver advice. If the agent gets {"error": "no projections"},
    tell the user that projections need to be computed first.
    """
    user_id, league_id = get_context(config)
    limit = max(1, min(int(limit), 50))
    pos_filter = position.upper().strip() if position else None

    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

        rows = (
            await db.execute(
                select(Player, ProjectionCache)
                .join(FreeAgent, FreeAgent.player_id == Player.id)
                .join(
                    ProjectionCache,
                    (ProjectionCache.player_id == Player.id)
                    & (ProjectionCache.league_id == league_id),
                )
                .where(FreeAgent.league_id == league_id)
                .order_by(desc(ProjectionCache.projected_value).nullslast())
            )
        ).all()

        out: list[dict[str, Any]] = []
        for player, proj in rows:
            if pos_filter:
                eligible = [p.upper() for p in (player.eligible_positions or [])]
                if pos_filter not in eligible:
                    continue
            view = player_view(player, include_draft=False)
            view["projected_value"] = (
                float(proj.projected_value) if proj.projected_value is not None else None
            )
            out.append(view)
            if len(out) >= limit:
                break

        if not out:
            return {
                "count": 0,
                "players": [],
                "note": (
                    "no projections found — run /admin/compute-projections "
                    "after syncing stats with /admin/sync-stats"
                ),
            }
        return {"count": len(out), "players": out}
