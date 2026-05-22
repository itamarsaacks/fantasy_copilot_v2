"""Date-aware fantasy standings.

Per master plan §2.6:

  standings_at(db, league_id, on_date) -> [TeamStanding]

is the single source of truth for "what was each manager's FPS on
date X." Backed by:
  1) `roster_at_for_league` — point-in-time owned-players per team
  2) `game_logs.get_logs_for_players_on_date` — actuals for that date
  3) `engine.projection._PointsValuator` / `_CategoryValuator` — league scoring

Results are lazy-cached in `standings_daily_cache`. Invalidation lives
in `sweeper` below — runs every 5 min, drains `standings_cache_invalidations`,
deletes affected cache rows. Next read repopulates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as date_type

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    League,
    StandingsCacheInvalidation,
    StandingsDailyCache,
    Team,
)
from app.engine.projection import (
    _CategoryValuator,
    _PointsValuator,
    CATEGORY_LEAGUE_TYPES,
    POINTS_LEAGUE_TYPES,
)
from app.services.game_logs import get_logs_for_players_on_date
from app.services.roster_history import roster_at_for_league

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TeamStanding:
    team_id: int
    team_name: str
    manager_name: str | None
    fps_on_date: float | None
    rank_on_date: int


def _make_valuator(league: League):  # noqa: ANN201
    """Pick the right valuator for this league's scoring type."""
    settings = league.settings_json or {}
    if league.scoring_type in POINTS_LEAGUE_TYPES:
        return _PointsValuator.from_settings(settings)
    if league.scoring_type in CATEGORY_LEAGUE_TYPES:
        return _CategoryValuator.from_settings(settings)
    return None


async def standings_at(
    db: AsyncSession,
    league_id: int,
    on_date: date_type,
    *,
    use_cache: bool = True,
) -> list[TeamStanding]:
    """Compute fantasy standings for a league on a specific date.

    Lazy cache: first call computes + writes `standings_daily_cache` rows,
    subsequent calls read from cache until the sweeper invalidates them
    (after a relevant `nba_game_logs` upsert).
    """
    # Try cache first
    if use_cache:
        cached = (
            (
                await db.execute(
                    select(StandingsDailyCache).where(
                        StandingsDailyCache.league_id == league_id,
                        StandingsDailyCache.on_date == on_date,
                    )
                )
            )
            .scalars()
            .all()
        )
        if cached:
            teams = {t.id: t for t in (await db.execute(
                select(Team).where(Team.league_id == league_id)
            )).scalars().all()}
            rows = sorted(
                cached, key=lambda r: -float(r.fps_total)
            )
            return [
                TeamStanding(
                    team_id=r.team_id,
                    team_name=teams[r.team_id].name if r.team_id in teams else "?",
                    manager_name=(
                        teams[r.team_id].manager_name if r.team_id in teams else None
                    ),
                    fps_on_date=float(r.fps_total),
                    rank_on_date=idx + 1,
                )
                for idx, r in enumerate(rows)
            ]

    # Compute fresh
    league = (
        await db.execute(select(League).where(League.id == league_id))
    ).scalar_one_or_none()
    if league is None:
        return []
    valuator = _make_valuator(league)
    rosters = await roster_at_for_league(db, league_id, on_date)
    teams_by_id = {
        t.id: t
        for t in (
            await db.execute(select(Team).where(Team.league_id == league_id))
        )
        .scalars()
        .all()
    }

    fps_by_team: dict[int, float] = {tid: 0.0 for tid in teams_by_id}

    if valuator is not None:
        # Gather all player ids across all teams in one query
        all_player_ids = list({s.player_id for slots in rosters.values() for s in slots})
        logs = await get_logs_for_players_on_date(db, all_player_ids, on_date)

        for team_id, slots in rosters.items():
            team_total = 0.0
            for slot in slots:
                row = logs.get(slot.player_id)
                if row is None or row.did_not_play:
                    continue
                box_floats = {
                    k: float(v) for k, v in (row.box or {}).items()
                    if isinstance(v, (int, float))
                }
                if not box_floats:
                    continue
                fps_one, _components = valuator.season_total(box_floats)
                if fps_one is not None:
                    team_total += float(fps_one)
            fps_by_team[team_id] = team_total

    # Write cache + return
    for team_id, fps in fps_by_team.items():
        stmt = pg_insert(StandingsDailyCache).values(
            league_id=league_id,
            team_id=team_id,
            on_date=on_date,
            fps_total=fps,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["league_id", "team_id", "on_date"],
            set_={"fps_total": stmt.excluded.fps_total, "computed_at": stmt.excluded.computed_at},
        )
        await db.execute(stmt)
    await db.commit()

    ranked = sorted(fps_by_team.items(), key=lambda kv: -kv[1])
    return [
        TeamStanding(
            team_id=tid,
            team_name=teams_by_id[tid].name if tid in teams_by_id else "?",
            manager_name=teams_by_id[tid].manager_name if tid in teams_by_id else None,
            fps_on_date=fps,
            rank_on_date=idx + 1,
        )
        for idx, (tid, fps) in enumerate(ranked)
    ]


# ---------------------------------------------------------------------------
# Sweeper — drains invalidations every 5 min via APScheduler.
# ---------------------------------------------------------------------------


async def sweep_standings_invalidations(db: AsyncSession) -> int:
    """Delete cached rows for every (league_id|*, on_date) invalidation,
    then delete the invalidation rows themselves.

    Returns count of cache rows deleted. Idempotent. Safe to run on a
    timer regardless of whether there's anything to sweep.
    """
    pending = (
        (await db.execute(select(StandingsCacheInvalidation))).scalars().all()
    )
    if not pending:
        return 0

    cache_deleted = 0
    for inv in pending:
        if inv.league_id is None:
            # Wildcard invalidation: drop all leagues for this date.
            res = await db.execute(
                delete(StandingsDailyCache).where(
                    StandingsDailyCache.on_date == inv.on_date
                )
            )
        else:
            res = await db.execute(
                delete(StandingsDailyCache).where(
                    StandingsDailyCache.league_id == inv.league_id,
                    StandingsDailyCache.on_date == inv.on_date,
                )
            )
        cache_deleted += res.rowcount or 0

    # Clear the invalidation queue
    await db.execute(delete(StandingsCacheInvalidation))
    await db.commit()
    log.info(
        "swept %d invalidations, deleted %d cache rows",
        len(pending),
        cache_deleted,
    )
    return cache_deleted
