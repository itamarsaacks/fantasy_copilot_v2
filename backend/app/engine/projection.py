"""Deterministic projection engine.

Inputs: player_stats rows (raw NBA stats per stat_id from Yahoo's global
/players endpoint), league.settings_json (stat_modifiers + stat_categories).

Output: projection_cache rows. Two horizons per player:
  - season_total — league-rule-aware total for the season.
  - per_game — per-game value, computed using GP (stat_id "0").

League-type handling — works for ALL Yahoo NBA league types:

  POINTS leagues (`point`, `headpoint`):
    Uses stat_modifiers (per-stat point weight). projected_value is total
    fantasy points. Components: per-stat fantasy point contribution.

  CATEGORY leagues (`head`, `roto`):
    Uses stat_categories (which stats are scored, position_type, value_type).
    projected_value is a composite score = sum of normalized per-game category
    values across scored cats. Components: per-stat per-game value (so the
    agent can analyze category-by-category, not just one number).
    NOTE: this is a sensible MVP composite. Real category league reasoning
    needs per-cat z-scores + opponent context — added later.

The LLM never estimates; this engine + the cached projection_cache rows
are the source of truth for every projected_value the agent quotes.
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

# Yahoo Fantasy Basketball league scoring types — all 5 supported formats:
#   point        — Season Points (all-season FPS total)
#   headpoint    — Head-to-Head Points (weekly FPS matchup)
#   seasonpoint  — Private "Season Points" variant — same math as `point`
#   head         — Head-to-Head Categories (9-cat)
#   roto         — Rotisserie (9-cat, rank-summed)
#   headone      — Head-to-Head One Win (9-cat, one W per matchup) — same
#                  per-player valuation as `head`; differs only in standings
#                  math (one win/loss instead of per-cat W/L). Projection
#                  engine doesn't care about that — treat as category.
POINTS_LEAGUE_TYPES = {"point", "headpoint", "seasonpoint"}
CATEGORY_LEAGUE_TYPES = {"head", "roto", "headone"}

HORIZON_SEASON_TOTAL = "season_total"
HORIZON_PER_GAME = "per_game"

STAT_ID_GAMES_PLAYED = "0"
# Stats that are inverse-scored in category leagues (lower is better) —
# e.g. turnovers. We sign-flip them in the composite.
INVERSE_STATS = {"19"}  # Yahoo NBA: 19 = TO


@dataclass
class ProjectionResult:
    league_key: str
    scoring_type: str
    horizons_written: dict[str, int] = field(default_factory=dict)
    rows_skipped_no_stats: int = 0
    errors: list[str] = field(default_factory=list)


async def compute_league_projections(league_id: int) -> ProjectionResult:
    """Compute and upsert projection_cache rows for one league, all horizons."""
    async with SessionLocal() as session:
        league = await session.get(League, league_id)
        if not league:
            return ProjectionResult(league_key="?", scoring_type="?", errors=["league not found"])

        result = ProjectionResult(
            league_key=league.league_key, scoring_type=league.scoring_type
        )

        if league.scoring_type in POINTS_LEAGUE_TYPES:
            valuator = _PointsValuator.from_settings(league.settings_json)
        elif league.scoring_type in CATEGORY_LEAGUE_TYPES:
            valuator = _CategoryValuator.from_settings(league.settings_json)
        else:
            # Unknown / future Yahoo type — graceful fallback: pick the
            # valuator that fits what Yahoo actually sent (stat_categories
            # ⇒ category league; stat_modifiers ⇒ points league). Logged
            # loudly so we add it to the allow-list above next session.
            log.warning(
                "unknown scoring_type '%s' for league %s — auto-detecting",
                league.scoring_type, league.league_key,
            )
            cat_valuator = _CategoryValuator.from_settings(league.settings_json)
            pts_valuator = _PointsValuator.from_settings(league.settings_json)
            valuator = cat_valuator or pts_valuator
            if valuator is None:
                result.errors.append(
                    f"unknown scoring_type '{league.scoring_type}' and no "
                    "stat_categories or stat_modifiers in settings"
                )
                return result

        if valuator is None:
            result.errors.append("could not parse league settings for projection")
            return result

        player_ids = await _league_player_ids(session, league_id)
        if not player_ids:
            return result
        latest_stats = await _latest_season_stats(session, player_ids)

        season_rows: list[dict[str, Any]] = []
        per_game_rows: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        for player_id in player_ids:
            stats = latest_stats.get(player_id)
            if not stats:
                result.rows_skipped_no_stats += 1
                continue

            season_value, season_components = valuator.season_total(stats)
            if season_value is None:
                result.rows_skipped_no_stats += 1
                continue
            season_rows.append(
                {
                    "player_id": player_id,
                    "league_id": league_id,
                    "horizon": HORIZON_SEASON_TOTAL,
                    "projected_value": round(season_value, 2),
                    "components": season_components,
                    "stale": False,
                    "computed_at": now,
                }
            )

            games_played = stats.get(STAT_ID_GAMES_PLAYED)
            if games_played and games_played >= 1:
                pg_value, pg_components = valuator.per_game(stats, games_played)
                if pg_value is not None:
                    per_game_rows.append(
                        {
                            "player_id": player_id,
                            "league_id": league_id,
                            "horizon": HORIZON_PER_GAME,
                            "projected_value": round(pg_value, 3),
                            "components": pg_components,
                            "stale": False,
                            "computed_at": now,
                        }
                    )

        for rows, key in ((season_rows, HORIZON_SEASON_TOTAL), (per_game_rows, HORIZON_PER_GAME)):
            if not rows:
                continue
            stmt = (
                pg_insert(ProjectionCache)
                .values(rows)
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
            result.horizons_written[key] = len(rows)
        await session.commit()

        return result


# ---------------------------------------------------------------------------
# Valuators — one per league family. Each computes (value, components).
# ---------------------------------------------------------------------------


class _PointsValuator:
    """For 'point' and 'headpoint' leagues. Uses stat_modifiers."""

    def __init__(self, modifiers: dict[str, float]):
        self.modifiers = modifiers

    @classmethod
    def from_settings(cls, settings_json: dict[str, Any]) -> "_PointsValuator | None":
        modifiers = _extract_stat_modifiers(settings_json)
        if not modifiers:
            return None
        return cls(modifiers)

    def season_total(self, stats: dict[str, float]) -> tuple[float | None, dict[str, float]]:
        total = 0.0
        components: dict[str, float] = {}
        had_any = False
        for stat_id, value in stats.items():
            modifier = self.modifiers.get(stat_id)
            if modifier is None or value is None:
                continue
            contribution = value * modifier
            total += contribution
            components[stat_id] = round(contribution, 2)
            had_any = True
        return (total if had_any else None), components

    def per_game(self, stats: dict[str, float], gp: float) -> tuple[float | None, dict[str, float]]:
        if gp < 1:
            return None, {}
        total = 0.0
        components: dict[str, float] = {}
        had_any = False
        for stat_id, value in stats.items():
            modifier = self.modifiers.get(stat_id)
            if modifier is None or value is None:
                continue
            per_game_value = value / gp
            contribution = per_game_value * modifier
            total += contribution
            components[stat_id] = round(contribution, 3)
            had_any = True
        return (total if had_any else None), components


class _CategoryValuator:
    """For 'head' (h2h categories) and 'roto' leagues. Uses stat_categories.

    Composite projected_value = sum of per-game per-category contributions
    (sign-flipped for inverse stats like turnovers). Components hold the
    per-game per-category value so the agent can read category-by-category.

    This is a deliberate MVP composite. Better category models — z-scores
    relative to league average, opponent-adjusted — go later.
    """

    def __init__(self, scored_stat_ids: set[str]):
        self.scored = scored_stat_ids

    @classmethod
    def from_settings(cls, settings_json: dict[str, Any]) -> "_CategoryValuator | None":
        scored = _extract_scored_stat_ids(settings_json)
        if not scored:
            return None
        return cls(scored)

    def season_total(self, stats: dict[str, float]) -> tuple[float | None, dict[str, float]]:
        # For category leagues, season totals are per-category accumulations.
        # We expose them via components; the composite scalar is just the sum
        # (sign-flipped on inverse stats) which is rough but ranks players.
        total = 0.0
        components: dict[str, float] = {}
        had_any = False
        for stat_id, value in stats.items():
            if stat_id not in self.scored or value is None:
                continue
            sign = -1.0 if stat_id in INVERSE_STATS else 1.0
            components[stat_id] = round(value, 2)
            total += sign * value
            had_any = True
        return (total if had_any else None), components

    def per_game(self, stats: dict[str, float], gp: float) -> tuple[float | None, dict[str, float]]:
        if gp < 1:
            return None, {}
        total = 0.0
        components: dict[str, float] = {}
        had_any = False
        for stat_id, value in stats.items():
            if stat_id not in self.scored or value is None:
                continue
            per_game_value = value / gp
            sign = -1.0 if stat_id in INVERSE_STATS else 1.0
            components[stat_id] = round(per_game_value, 3)
            total += sign * per_game_value
            had_any = True
        return (total if had_any else None), components


# ---------------------------------------------------------------------------
# Settings extractors
# ---------------------------------------------------------------------------


def _extract_stat_modifiers(settings_json: dict[str, Any]) -> dict[str, float]:
    """Return {stat_id: modifier_value} from league settings."""
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


def _extract_scored_stat_ids(settings_json: dict[str, Any]) -> set[str]:
    """Return {stat_id} for stats that count toward standings (is_only_display_stat=False)."""
    out: set[str] = set()
    if not isinstance(settings_json, dict):
        return out
    sc = settings_json.get("stat_categories") or {}
    stats = sc.get("stats") if isinstance(sc, dict) else None
    if not isinstance(stats, list):
        return out
    for wrapper in stats:
        if not isinstance(wrapper, dict):
            continue
        s = wrapper.get("stat")
        if not isinstance(s, dict):
            continue
        stat_id = str(s.get("stat_id")) if s.get("stat_id") is not None else None
        if not stat_id:
            continue
        # In category leagues, every stat in stat_categories counts unless
        # explicitly is_only_display_stat=1 (e.g. minutes might be display-only).
        if str(s.get("is_only_display_stat", "0")) == "1":
            continue
        out.add(stat_id)
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


async def _latest_season_stats(
    session: AsyncSession, player_ids: list[int]
) -> dict[int, dict[str, float]]:
    """Return {player_id: {stat_id: value}} from the most recent season-scope row.

    Stats are now stored league-independent (raw NBA), so we no longer filter
    by league_key — any league's sync produces equivalent rows.
    """
    rows = (
        await session.execute(
            select(PlayerStats)
            .where(
                PlayerStats.player_id.in_(player_ids),
                PlayerStats.scope == "season",
            )
            .order_by(PlayerStats.as_of_date.desc(), PlayerStats.id.desc())
        )
    ).scalars().all()

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
