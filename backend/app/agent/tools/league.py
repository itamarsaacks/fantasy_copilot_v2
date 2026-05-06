"""Tools that read league-level info."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlalchemy import select

from app.agent.tools._helpers import get_context
from app.db.engine import SessionLocal
from app.db.models import League, Team


@tool
async def get_league_summary(config: RunnableConfig) -> dict[str, Any]:
    """Return high-level info about the user's currently-selected league.

    Output: league_name, scoring_type (point/head/headpoint/roto), num_teams,
    current_week, season, and a `standings` array of every team with
    {rank, name, manager, wins, losses, ties, points_for, points_against,
    faab_balance, waiver_priority, clinched_playoffs, is_user_team}.

    Use this for: standings questions, league context, "where am I ranked",
    "who is in the lead", "did I make playoffs", waiver-priority questions.
    """
    user_id, league_id = get_context(config)
    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

        teams = (
            await db.execute(
                select(Team).where(Team.league_id == league_id).order_by(Team.rank)
            )
        ).scalars().all()

        return {
            "league_name": league.name,
            "scoring_type": league.scoring_type,
            "num_teams": league.num_teams,
            "current_week": league.current_week,
            "season": league.season,
            "standings": [
                {
                    "rank": t.rank,
                    "name": t.name,
                    "manager": t.manager_name,
                    "wins": t.wins,
                    "losses": t.losses,
                    "ties": t.ties,
                    "points_for": float(t.points_for) if t.points_for else None,
                    "points_against": float(t.points_against) if t.points_against else None,
                    "faab_balance": t.faab_balance,
                    "waiver_priority": t.waiver_priority,
                    "clinched_playoffs": t.clinched_playoffs,
                    "is_user_team": t.is_user_team,
                }
                for t in teams
            ],
        }
