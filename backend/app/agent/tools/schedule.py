"""Game-schedule lookup for fantasy players.

Joins players.nba_team_abbr → nba_schedule (synced daily from ESPN).
Returns games-this-week, opponents, B2B flags. Critical context for
start/sit, lineup, and FA decisions.

Bulk by design — accepts a list of names so a single call covers a
full roster or a top-N FA list without burning 13 round trips.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlalchemy import select

from app.agent.tools._helpers import fold_ascii, get_context
from app.db.engine import SessionLocal
from app.db.models import League, NbaSchedule, Player
from app.services.clock import resolve_today


@tool
async def get_player_schedule(
    names: list[str], config: RunnableConfig, days_ahead: int = 7
) -> dict[str, Any]:
    """Return upcoming NBA game schedules for one or many players.

    Use for ANY schedule / matchup / lineup question:
      - "how many games does Embiid have this week"  → pass ["Embiid"]
      - "any back-to-backs on my roster"             → pass full roster
      - "who has the most games this week"           → pass any list

    BULK BY DESIGN: pass a LIST of names. For roster-wide questions
    (B2B load, start/sit) call ONCE with all players, not N times.

    Args:
      names: one or more player names. Case + diacritic insensitive,
        substring match.
      days_ahead: how many days to look forward (default 7 = this fantasy
        week; pass 14 for "next week" queries; max 30).

    Output:
      {players: [{name, nba_team, games_count, back_to_back_count,
                  games: [{date, opponent, home, status, is_back_to_back}, ...]
                 }, ...],
       unresolved: [name, ...]}
    """
    user_id, league_id = get_context(config)
    if not names:
        return {"error": "no names provided"}

    days_ahead = max(1, min(int(days_ahead), 30))

    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

        all_players = (await db.execute(select(Player))).scalars().all()

        today = resolve_today()
        until = today + timedelta(days=days_ahead)

        # Pull every game in window once; bucket by team to share across players.
        games_q = await db.execute(
            select(NbaSchedule)
            .where(
                NbaSchedule.game_date >= today,
                NbaSchedule.game_date < until,
            )
            .order_by(NbaSchedule.game_date)
        )
        all_games = games_q.scalars().all()

        by_team: dict[str, list[NbaSchedule]] = {}
        for g in all_games:
            by_team.setdefault(g.home_team_abbr, []).append(g)
            by_team.setdefault(g.away_team_abbr, []).append(g)

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
            if len(matches) > 1:
                matches.sort(
                    key=lambda p: float(p.percent_owned or 0), reverse=True
                )
            player = matches[0]
            team = player.nba_team_abbr
            if not team:
                results.append(
                    {
                        "name": player.full_name,
                        "nba_team": None,
                        "games_count": 0,
                        "back_to_back_count": 0,
                        "games": [],
                        "note": "player has no NBA team assigned",
                    }
                )
                continue

            team_games = by_team.get(team, [])
            formatted: list[dict[str, Any]] = []
            b2b_count = 0
            prev_date: date | None = None
            for g in team_games:
                is_home = g.home_team_abbr == team
                opponent = g.away_team_abbr if is_home else g.home_team_abbr
                b2b = prev_date is not None and (g.game_date - prev_date).days == 1
                if b2b:
                    b2b_count += 1
                formatted.append(
                    {
                        "date": g.game_date.isoformat(),
                        "opponent": opponent,
                        "home": is_home,
                        "status": g.status,
                        "is_back_to_back": b2b,
                    }
                )
                prev_date = g.game_date

            results.append(
                {
                    "name": player.full_name,
                    "nba_team": team,
                    "games_count": len(formatted),
                    "back_to_back_count": b2b_count,
                    "games": formatted,
                }
            )

        return {"players": results, "unresolved": unresolved}
