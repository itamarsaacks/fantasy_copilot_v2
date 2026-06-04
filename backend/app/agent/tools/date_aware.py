"""Date-aware agent tools introduced by the data foundation reformation.

Per master plan §2.9 — six new tools that let the agent answer date-pivoted
questions ("what did my team score on March 12?", "which FAs play next
Tuesday + Thursday?", "if I swap X for Y, how does my projection change?").

All tools:
  - Receive (user_id, league_id, thread_id) via RunnableConfig.configurable
  - Read Postgres only (never Yahoo / never ESPN at request time)
  - Return Pydantic-shaped dicts the LLM can read out loud

Tool list (registered in `ALL_TOOLS`):
  get_games_on_date
  get_standings_on_date
  get_team_roster_on_date
  get_player_box_on_date
  simulate_lineup
  find_fas_playing_on_dates
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlalchemy import or_, select

from app.agent.tools._helpers import get_context
from app.db.engine import SessionLocal
from app.db.models import (
    FreeAgent,
    League,
    NbaSchedule,
    Player,
    Team,
)
from app.engine.projection import (
    CATEGORY_LEAGUE_TYPES,
    POINTS_LEAGUE_TYPES,
    _CategoryValuator,
    _PointsValuator,
)
from app.services.clock import resolve_today
from app.services.game_logs import (
    get_logs_for_player,
)
from app.services.projection_window import (
    project_fps_for_window,
)
from app.services.roster_history import roster_at
from app.services.standings import standings_at


def _parse_date(s: str | None) -> date_type:
    if not s:
        return resolve_today()
    return date_type.fromisoformat(s)


def _make_valuator(league: League):  # noqa: ANN201
    settings = league.settings_json or {}
    if league.scoring_type in POINTS_LEAGUE_TYPES:
        return _PointsValuator.from_settings(settings)
    if league.scoring_type in CATEGORY_LEAGUE_TYPES:
        return _CategoryValuator.from_settings(settings)
    return None


@tool
async def get_games_on_date(
    date: str | None, config: RunnableConfig
) -> dict[str, Any]:
    """NBA games on a specific date with scores + status.

    Use for "what's the schedule today/yesterday", "did the Lakers play",
    or any question that benefits from knowing which teams played.

    Args:
      date: YYYY-MM-DD. None = today (replay-aware).
    """
    target = _parse_date(date)
    async with SessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(NbaSchedule)
                    .where(NbaSchedule.game_date == target)
                    .order_by(NbaSchedule.tipoff_at.asc().nulls_last())
                )
            )
            .scalars()
            .all()
        )
    return {
        "date": target.isoformat(),
        "count": len(rows),
        "games": [
            {
                "game_id": g.game_id,
                "home_team": g.home_team_abbr,
                "away_team": g.away_team_abbr,
                "home_score": g.home_score,
                "away_score": g.away_score,
                "status": g.status,
                "tipoff_at": g.tipoff_at.isoformat() if g.tipoff_at else None,
            }
            for g in rows
        ],
    }


@tool
async def get_standings_on_date(
    date: str | None, config: RunnableConfig
) -> dict[str, Any]:
    """Fantasy standings as of a specific date — each manager's FPS that day.

    Args:
      date: YYYY-MM-DD. None = today.
    """
    user_id, league_id = get_context(config)
    target = _parse_date(date)
    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}
        rows = await standings_at(db, league_id, target)
    return {
        "league_id": league_id,
        "date": target.isoformat(),
        "standings": [
            {
                "rank": r.rank_on_date,
                "team_id": r.team_id,
                "team_name": r.team_name,
                "manager": r.manager_name,
                "fps_on_date": r.fps_on_date,
            }
            for r in rows
        ],
    }


@tool
async def get_team_roster_on_date(
    team_id: int, date: str | None, config: RunnableConfig
) -> dict[str, Any]:
    """Reconstruct a team's roster on a specific date (replay from draft + transactions).

    Args:
      team_id: The Team.id (NOT the user-visible team number — use
        get_league_summary to map manager name → team_id first if you
        need to).
      date: YYYY-MM-DD. None = today.

    Note: positional slots (PG/BN/IL) are NOT reconstructed historically —
    Yahoo doesn't expose that cleanly. Return is "players owned on the
    date," not "starting lineup on the date."
    """
    user_id, league_id = get_context(config)
    target = _parse_date(date)
    async with SessionLocal() as db:
        team = await db.get(Team, team_id)
        if not team:
            return {"error": f"team {team_id} not found"}
        league = await db.get(League, team.league_id)
        if not league or league.user_id != user_id or league.id != league_id:
            return {"error": "team not in your league"}
        slots = await roster_at(db, team_id, target)
        if not slots:
            return {
                "team_id": team_id,
                "team_name": team.name,
                "date": target.isoformat(),
                "players": [],
                "note": "no roster data — transactions not synced for this date",
            }
        player_ids = [s.player_id for s in slots]
        players = (
            (await db.execute(select(Player).where(Player.id.in_(player_ids))))
            .scalars()
            .all()
        )
        by_id = {p.id: p for p in players}
    return {
        "team_id": team_id,
        "team_name": team.name,
        "date": target.isoformat(),
        "players": [
            {
                "player_id": p.id,
                "name": p.full_name,
                "nba_team": p.nba_team_abbr,
                "position": p.primary_position,
            }
            for p in (by_id[s.player_id] for s in slots if s.player_id in by_id)
        ],
    }


@tool
async def get_player_box_on_date(
    player_name: str, date: str, config: RunnableConfig
) -> dict[str, Any]:
    """One player's actual game line on a specific past date.

    Args:
      player_name: Free-text name (Embiid, Joel Embiid, etc.).
      date: YYYY-MM-DD (must be past — future dates return projection-shaped).
    """
    user_id, league_id = get_context(config)
    target = _parse_date(date)
    from app.agent.tools._helpers import fold_ascii  # local to avoid cycle

    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}
        # Lookup player by fuzzy name
        needle = fold_ascii(player_name.strip().lower())
        candidates = (
            (
                await db.execute(
                    select(Player).where(
                        or_(
                            Player.full_name.ilike(f"%{player_name}%"),
                            Player.last_name.ilike(f"%{player_name}%"),
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        if not candidates:
            return {"error": f"no player matching '{player_name}'"}
        # Prefer exact name match
        exact = [p for p in candidates if fold_ascii(p.full_name.lower()) == needle]
        player = exact[0] if exact else candidates[0]

        logs = await get_logs_for_player(db, player.id, target, target)
        if not logs:
            return {
                "player": player.full_name,
                "date": target.isoformat(),
                "did_not_play": True,
                "note": "no game log row — player did not play or game not synced",
            }
        log = logs[0]
        # Compute FPS for the caller's league
        valuator = _make_valuator(league)
        fps = None
        if valuator is not None and not log.did_not_play and log.box:
            box_floats = {
                k: float(v) for k, v in log.box.items() if isinstance(v, (int, float))
            }
            if box_floats:
                fps_raw, _ = valuator.season_total(box_floats)
                if fps_raw is not None:
                    fps = round(float(fps_raw), 2)

    return {
        "player": player.full_name,
        "date": target.isoformat(),
        "opponent": log.opponent_abbr,
        "is_home": log.is_home,
        "minutes": log.minutes,
        "stats": log.box,
        "fantasy_points": fps,
        "did_not_play": log.did_not_play,
    }


@tool
async def simulate_lineup(
    out_player_names: list[str],
    in_player_names: list[str],
    dates: list[str],
    config: RunnableConfig,
) -> dict[str, Any]:
    """What-if: swap players in/out of the user's roster and project FPS over `dates`.

    Lists must be same length — pairs out[i] -> in[i]. Empty out[] means
    "additions only." For roster-positional swaps the agent should usually
    drop someone the user has flagged + add the FA being considered.

    Args:
      out_player_names: Free-text names being dropped (can be empty).
      in_player_names: Free-text names being added.
      dates: YYYY-MM-DD list of dates the user cares about (waiver window).
    """
    user_id, league_id = get_context(config)
    if not in_player_names:
        return {"error": "in_player_names must include at least one player"}
    if out_player_names and len(out_player_names) != len(in_player_names):
        return {"error": "out_player_names and in_player_names must be same length"}
    if not dates:
        return {"error": "dates required"}

    parsed_dates = [date_type.fromisoformat(d) for d in dates]

    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}

        async def resolve(name: str) -> Player | None:
            q = await db.execute(
                select(Player).where(Player.full_name.ilike(f"%{name}%")).limit(1)
            )
            return q.scalar_one_or_none()

        outs = [await resolve(n) for n in out_player_names]
        ins = [await resolve(n) for n in in_player_names]
        if any(p is None for p in ins):
            return {"error": "could not resolve one or more in_player_names"}

        # Current user roster (sum projections over dates)
        my_team = (
            await db.execute(
                select(Team).where(
                    Team.league_id == league_id, Team.is_user_team.is_(True)
                )
            )
        ).scalar_one_or_none()
        if my_team is None:
            return {"error": "no user team"}

        roster_ids = [
            pid
            for (pid,) in (
                await db.execute(
                    select(Team.id)  # placeholder to satisfy linter
                )
            ).all()
        ] if False else None
        # ^ unused branch; using direct query below for clarity
        from app.db.models import RosterPlayer
        roster_ids = [
            pid
            for (pid,) in (
                await db.execute(
                    select(RosterPlayer.player_id).where(
                        RosterPlayer.team_id == my_team.id
                    )
                )
            ).all()
        ]

        async def total(ids: list[int]) -> float:
            t = 0.0
            for pid in ids:
                t += float(
                    await project_fps_for_window(db, pid, league_id, parsed_dates)
                )
            return t

        baseline = await total(roster_ids)
        sim = list(roster_ids)
        for out_p, in_p in zip(outs, ins):
            if out_p is not None and out_p.id in sim:
                sim.remove(out_p.id)
            sim.append(in_p.id)  # type: ignore[union-attr]
        simulated = await total(sim)

    return {
        "league_id": league_id,
        "dates": dates,
        "baseline_projected_fps": round(baseline, 2),
        "simulated_projected_fps": round(simulated, 2),
        "delta": round(simulated - baseline, 2),
        "swap_pairs": [
            {
                "out": out_player_names[i] if i < len(out_player_names) else None,
                "in": in_player_names[i],
            }
            for i in range(len(in_player_names))
        ],
    }


@tool
async def find_fas_playing_on_dates(
    dates: list[str], config: RunnableConfig, top_n: int = 20
) -> dict[str, Any]:
    """Rank free agents by projected FPS across the selected calendar dates.

    Backs the Waiver Planner sub-tab. Players whose teams play zero games
    on the selected dates are excluded.

    Args:
      dates: YYYY-MM-DD list. The user picks specific calendar days; we
        rank FAs by total projected FPS across that exact window.
      top_n: How many candidates to return (max 50).
    """
    user_id, league_id = get_context(config)
    if not dates:
        return {"error": "dates required"}
    parsed = [date_type.fromisoformat(d) for d in dates]
    top_n = min(50, max(1, top_n))

    async with SessionLocal() as db:
        league = await db.get(League, league_id)
        if not league or league.user_id != user_id:
            return {"error": "league not found"}
        fa_rows = (
            (
                await db.execute(
                    select(FreeAgent, Player)
                    .join(Player, FreeAgent.player_id == Player.id)
                    .where(FreeAgent.league_id == league_id)
                )
            )
            .all()
        )
        cands: list[dict[str, Any]] = []
        for fa, player in fa_rows:
            if not player.nba_team_abbr:
                continue
            games = (
                await db.execute(
                    select(NbaSchedule.game_date)
                    .where(NbaSchedule.game_date.in_(parsed))
                    .where(
                        or_(
                            NbaSchedule.home_team_abbr == player.nba_team_abbr,
                            NbaSchedule.away_team_abbr == player.nba_team_abbr,
                        )
                    )
                )
            ).all()
            if not games:
                continue
            proj = float(
                await project_fps_for_window(db, player.id, league_id, parsed)
            )
            cands.append(
                {
                    "player_id": player.id,
                    "name": player.full_name,
                    "nba_team": player.nba_team_abbr,
                    "position": player.primary_position,
                    "games_on_selected_dates": len(games),
                    "projected_fps_window": round(proj, 2),
                }
            )
    cands.sort(key=lambda c: -c["projected_fps_window"])
    return {
        "league_id": league_id,
        "dates": dates,
        "candidates": cands[:top_n],
    }
