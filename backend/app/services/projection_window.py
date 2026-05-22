"""Per-date and per-window projection helpers.

Per master plan §2.6b: we don't store per-date projections — we derive
them at query time as `per_game × games_on_date`. This module is the
single place that math lives.

Two public helpers:
    project_fps_on_date(db, player_id, league_id, on_date) -> float | None
    project_fps_for_window(db, player_id, league_id, dates) -> float

The window helper sums per-date and returns 0 if the player has no games
on any of the dates. Used by Waiver Planner sub-tab + My Team what-if.
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NbaSchedule, Player, ProjectionCache


async def _per_game(
    db: AsyncSession, player_id: int, league_id: int
) -> Decimal | None:
    """Look up the cached `per_game` projection for a player in a league."""
    cache_row = (
        await db.execute(
            select(ProjectionCache).where(
                ProjectionCache.player_id == player_id,
                ProjectionCache.league_id == league_id,
                ProjectionCache.horizon == "per_game",
            )
        )
    ).scalar_one_or_none()
    if cache_row is None or cache_row.projected_value is None:
        return None
    return Decimal(str(cache_row.projected_value))


async def _games_for_player_on(
    db: AsyncSession, player_id: int, on_date: date_type
) -> int:
    """Count NBA games the player's NBA team plays on `on_date`."""
    player = (
        await db.execute(select(Player).where(Player.id == player_id))
    ).scalar_one_or_none()
    if player is None or not player.nba_team_abbr:
        return 0
    team_abbr = player.nba_team_abbr
    q = select(NbaSchedule).where(
        NbaSchedule.game_date == on_date,
        or_(
            NbaSchedule.home_team_abbr == team_abbr,
            NbaSchedule.away_team_abbr == team_abbr,
        ),
    )
    return len((await db.execute(q)).scalars().all())


async def project_fps_on_date(
    db: AsyncSession,
    player_id: int,
    league_id: int,
    on_date: date_type,
) -> Decimal | None:
    """Projected FPS for one player on one date.

    Returns None when:
      - no projection cached (model never ran for this player+league)
      - player's NBA team has no game on this date (UI renders '-')
    """
    pg = await _per_game(db, player_id, league_id)
    if pg is None:
        return None
    games = await _games_for_player_on(db, player_id, on_date)
    if games == 0:
        return None
    return pg * games  # back-to-back = 2× per_game on that calendar date


async def project_fps_for_window(
    db: AsyncSession,
    player_id: int,
    league_id: int,
    dates: list[date_type],
) -> Decimal:
    """Sum projected FPS across multiple dates.

    Returns Decimal(0) if no games on any date. Used by Waiver Planner
    (user selects N specific dates) and My-Team what-if windows.
    """
    if not dates:
        return Decimal(0)
    pg = await _per_game(db, player_id, league_id)
    if pg is None:
        return Decimal(0)

    # Bulk-fetch schedule for the date range in one query, then count
    # in-Python — cheaper than N round-trips for N dates.
    player = (
        await db.execute(select(Player).where(Player.id == player_id))
    ).scalar_one_or_none()
    if player is None or not player.nba_team_abbr:
        return Decimal(0)
    team_abbr = player.nba_team_abbr

    rows = (
        (
            await db.execute(
                select(NbaSchedule.game_date)
                .where(NbaSchedule.game_date.in_(dates))
                .where(
                    or_(
                        NbaSchedule.home_team_abbr == team_abbr,
                        NbaSchedule.away_team_abbr == team_abbr,
                    )
                )
            )
        )
        .all()
    )
    games_total = len(rows)
    return pg * games_total
