"""Deterministic projection engine.

Inputs: player_stats rows (raw NBA stats per stat_id), league.settings_json
(stat_modifiers — the per-stat-id point weight in this league).

Output: rows in projection_cache. Each row is one projection for
(player, league, horizon).

Phase 6 scope: POINTS leagues only (`point` and `headpoint` scoring types).
For points leagues, projection = sum_{stat_id} (season_total * modifier).
This is the season-total fantasy points — exactly the metric GNZ-style
points leagues use to rank standings. Per-game projections (for headpoint
weekly value or next-7 windows) require games_played, which Yahoo does NOT
return on the league-scoped stats endpoint. Once we add the non-league-
scoped /players;.../stats fetch (which includes GP), we'll add a per_game
horizon and weekly projections.

Categories leagues (`head`, `roto`) need a different model — a vector of
per-category values, not one number. Deferred to a follow-up phase.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import SessionLocal
from app.db.models import (
    FreeAgent,
    League,
    Player,
    PlayerStats,
    ProjectionCache,
    RosterPlayer,
    Team,
)

log = logging.getLogger(__name__)

POINTS_LEAGUE_TYPES = {"point", "headpoint"}
DEFAULT_HORIZON = "season_total"


@dataclass
class ProjectionResult:
    league_key: str
    rows_written: int = 0
    rows_skipped_no_stats: int = 0
    errors: list[str] = field(default_factory=list)


async def compute_league_projections(league_id: int) -> ProjectionResult:
    """Compute and upsert projection_cache rows for one league."""
    async with SessionLocal() as session:
        league = await session.get(League, league_id)
        if not league:
            return ProjectionResult(league_key="?", errors=["league not found"])

        result = ProjectionResult(league_key=league.league_key)

        if league.scoring_type not in POINTS_LEAGUE_TYPES:
            result.errors.append(
                f"scoring_type '{league.scoring_type}' not yet supported by projection engine"
            )
            return result

        modifiers = _extract_stat_modifiers(league.settings_json)
        if not modifiers:
            result.errors.append("could not parse stat_modifiers from league settings")
            return result

        # Pull the latest season-scope stats for every player who matters in this
        # league (rostered + FA). We aggregate to one row per player_id.
        player_ids = await _league_player_ids(session, league_id)
        if not player_ids:
            return result

        latest_stats = await _latest_stats_for_players(
            session, player_ids, league.league_key
        )

        rows_to_upsert: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for player_id in player_ids:
            stats = latest_stats.get(player_id)
            if not stats:
                result.rows_skipped_no_stats += 1
                continue

            total_points = 0.0
            components: dict[str, float] = {}
            had_any = False
            for stat_id, value in stats.items():
                modifier = modifiers.get(stat_id)
                if modifier is None or value is None:
                    continue
                contribution = value * modifier
                total_points += contribution
                components[stat_id] = round(contribution, 2)
                had_any = True

            if not had_any:
                result.rows_skipped_no_stats += 1
                continue

            rows_to_upsert.append(
                {
                    "player_id": player_id,
                    "league_id": league_id,
                    "horizon": DEFAULT_HORIZON,
                    "projected_value": round(total_points, 2),
                    "components": components,
                    "stale": False,
                    "computed_at": now,
                }
            )

        if rows_to_upsert:
            stmt = (
                pg_insert(ProjectionCache)
                .values(rows_to_upsert)
                .on_conflict_do_update(
                    index_elements=["player_id", "league_id", "horizon"],
                    set_={
                        "projected_value": pg_insert(ProjectionCache).excluded.projected_value,
                        "components": pg_insert(ProjectionCache).excluded.components,
                        "stale": pg_insert(ProjectionCache).excluded.stale,
                        "computed_at": pg_insert(ProjectionCache).excluded.computed_at,
                    },
                )
            )
            await session.execute(stmt)
            await session.commit()

        result.rows_written = len(rows_to_upsert)
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_stat_modifiers(settings_json: dict[str, Any]) -> dict[str, float]:
    """Return {stat_id: modifier_value} from league settings JSON.

    Yahoo's settings shape: settings.stat_modifiers.stats == [{"stat": {"stat_id": "5", "value": "1"}}, ...]
    """
    out: dict[str, float] = {}
    if not isinstance(settings_json, dict):
        return out
    sm = settings_json.get("stat_modifiers") or {}
    stats = sm.get("stats") if isinstance(sm, dict) else None
    if not isinstance(stats, list):
        return out
    for wrapper in stats:
        if not isinstance(wrapper, dict):
            continue
        s = wrapper.get("stat")
        if not isinstance(s, dict):
            continue
        stat_id = str(s.get("stat_id")) if s.get("stat_id") is not None else None
        try:
            value = float(s.get("value")) if s.get("value") not in (None, "") else None
        except (TypeError, ValueError):
            value = None
        if stat_id and value is not None:
            out[stat_id] = value
    return out


async def _league_player_ids(session: AsyncSession, league_id: int) -> list[int]:
    rostered = (
        await session.execute(
            select(Player.id)
            .join(RosterPlayer, RosterPlayer.player_id == Player.id)
            .join(Team, Team.id == RosterPlayer.team_id)
            .where(Team.league_id == league_id)
        )
    ).scalars().all()
    fas = (
        await session.execute(
            select(Player.id)
            .join(FreeAgent, FreeAgent.player_id == Player.id)
            .where(FreeAgent.league_id == league_id)
        )
    ).scalars().all()
    return list({*rostered, *fas})


async def _latest_stats_for_players(
    session: AsyncSession, player_ids: list[int], league_key: str
) -> dict[int, dict[str, float]]:
    """Return {player_id: {stat_id: value}} from the most recent season-scope row."""
    rows = (
        await session.execute(
            select(PlayerStats)
            .where(
                PlayerStats.player_id.in_(player_ids),
                PlayerStats.league_key == league_key,
                PlayerStats.scope == "season",
            )
            .order_by(PlayerStats.as_of_date.desc(), PlayerStats.id.desc())
        )
    ).scalars().all()

    # Group by player_id. Within each player, take the latest as_of_date.
    by_player: dict[int, dict[str, float]] = {}
    seen_dates: dict[int, Any] = {}
    for row in rows:
        if row.player_id not in seen_dates:
            seen_dates[row.player_id] = row.as_of_date
            by_player[row.player_id] = {}
        if seen_dates[row.player_id] != row.as_of_date:
            continue
        by_player[row.player_id][row.stat_id] = float(row.value)
    return by_player
