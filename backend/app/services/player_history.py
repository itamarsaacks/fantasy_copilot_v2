"""Fetch + cache per-date stats for individual players.

Why this exists: the per-date Yahoo stats endpoint is the only way to
reconstruct game-by-game performance for arbitrary date ranges. We cache
every result into `nba_game_logs` so we only hit Yahoo once per
(player, date). Subsequent reads are pure DB.

This is deliberately not an agent tool — pure functions, deterministic
math, no LLM in the loop. The Player detail drawer + Compare flows
call this directly.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import yahoo as yahoo_client
from app.db.models import NbaGameLog, NbaSchedule, Player, User

log = logging.getLogger(__name__)

# Yahoo "missing value" sentinel — they return '-' for stat lines on
# days when the player didn't play. We treat those as no-row.
_YAHOO_DASH = "-"

# Maximum parallel per-date fetches we'll launch. Yahoo's per-date
# endpoint takes one date at a time per request, so for a long range we
# need to issue N requests. Don't fan out unbounded — be neighborly.
_MAX_CONCURRENT_FETCHES = 6


def _is_valid_stat_value(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str) and v.strip() in {"", _YAHOO_DASH}:
        return False
    return True


def _stats_to_box(stat_rows: list[dict[str, Any]]) -> dict[str, float] | None:
    """Turn Yahoo's [{stat_id, value}, ...] into {stat_id_str: float}.

    Returns None when no row had a real value — Yahoo's signal for "no
    game" or "DNP at the game-feed level."

    Skips inf / nan values entirely — Yahoo emits "Infinity" for some
    rate stats (FT% on 0/0 attempts) and Postgres' JSONB rejects those.
    """
    import math

    box: dict[str, float] = {}
    for row in stat_rows:
        sid = row.get("stat_id")
        v = row.get("value")
        if sid is None or not _is_valid_stat_value(v):
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isnan(f) or math.isinf(f):
            continue
        box[str(sid)] = f
    if not box:
        return None
    # Need at least GP=1 to count this as a played game. Yahoo emits
    # stat_id "0" = games played.
    if box.get("0", 0) == 0:
        return None
    return box


async def _games_in_range(
    db: AsyncSession,
    player: Player,
    start: date_type,
    end: date_type,
) -> list[NbaSchedule]:
    """The player's team's schedule for [start, end]."""
    if not player.nba_team_abbr:
        return []
    rows = (
        await db.execute(
            select(NbaSchedule)
            .where(
                NbaSchedule.game_date >= start,
                NbaSchedule.game_date <= end,
                or_(
                    NbaSchedule.home_team_abbr == player.nba_team_abbr,
                    NbaSchedule.away_team_abbr == player.nba_team_abbr,
                ),
            )
            .order_by(NbaSchedule.game_date)
        )
    ).scalars().all()
    return list(rows)


async def _existing_logs(
    db: AsyncSession, player_id: int, dates: list[date_type]
) -> dict[date_type, NbaGameLog]:
    if not dates:
        return {}
    rows = (
        await db.execute(
            select(NbaGameLog).where(
                NbaGameLog.player_id == player_id,
                NbaGameLog.game_date.in_(dates),
            )
        )
    ).scalars().all()
    return {r.game_date: r for r in rows}


async def fetch_and_cache_logs(
    db: AsyncSession,
    *,
    access_token: str,
    player: Player,
    start: date_type,
    end: date_type,
    today: date_type | None = None,
) -> list[NbaGameLog]:
    """Fetch every actual-game log for this player in [start, end] and
    return them as NbaGameLog rows.

    Two strategies depending on whether we have schedule rows:

    1. **Schedule-driven** (forward-looking dates, which we sync daily):
       walk the player's team's schedule for the range and fetch only
       those dates.

    2. **Walk-every-date** fallback: when no schedule rows exist (true
       for past regular-season dates today since we only sync forward),
       request every date in [start, end] up to `today`. Yahoo returns
       a no-game row for off-days, which we filter; that's wasteful at
       30-day scale but acceptable for on-demand player-detail loads.

    Logs are cached by `game_id` when known, by a synthetic `yahoo-date-{date}`
    key when we don't have a schedule row. Future loads of the same date
    hit the cache and skip the Yahoo call.

    Future games are never written as logs — projections handle those.
    """
    today = today or datetime.now(timezone.utc).date()
    if start > end:
        return []
    range_end_effective = min(end, today)
    if range_end_effective < start:
        return []  # entire range is in the future

    sched = await _games_in_range(db, player, start, range_end_effective)
    have_schedule = bool(sched)

    if have_schedule:
        candidate_dates = [g.game_date for g in sched]
        sched_by_date = {g.game_date: g for g in sched}
    else:
        # Walk every date in range. Cheap server-side; Yahoo returns
        # empty stat lines for off-days so we filter post-fetch.
        candidate_dates = []
        cursor = start
        while cursor <= range_end_effective:
            candidate_dates.append(cursor)
            cursor += timedelta(days=1)
        sched_by_date = {}

    cached = await _existing_logs(db, player.id, candidate_dates)
    missing_dates = [d for d in candidate_dates if d not in cached]

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)

    async def _fetch_one(d: date_type) -> tuple[date_type, dict[str, float] | None]:
        async with semaphore:
            try:
                resp = await yahoo_client.fetch_player_stats(
                    access_token,
                    [player.yahoo_player_key],
                    coverage="date",
                    date=d.isoformat(),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Yahoo per-date fetch failed for player=%s date=%s: %s",
                    player.yahoo_player_key,
                    d,
                    exc,
                )
                return d, None
            rows = resp.get(player.yahoo_player_key) or []
            return d, _stats_to_box(rows)

    fetched = await asyncio.gather(*[_fetch_one(d) for d in missing_dates])

    rows_to_write: list[dict[str, Any]] = []
    for d, box in fetched:
        sched_row = sched_by_date.get(d)
        if sched_row is not None:
            game_id = sched_row.game_id
            is_home = sched_row.home_team_abbr == player.nba_team_abbr
            opp = sched_row.away_team_abbr if is_home else sched_row.home_team_abbr
        else:
            game_id = f"yh-{player.yahoo_player_key}-{d.isoformat()}"
            is_home = None
            opp = None
        # Distinguish "didn't play" (box is None) from a real game-day
        # row. Off-day placeholder = box {"_no_game": 1} with minutes=NULL.
        # Caching off-days too keeps subsequent loads zero round-trips.
        if box is None:
            rows_to_write.append(
                {
                    "player_id": player.id,
                    "game_id": game_id,
                    "game_date": d,
                    "opponent_abbr": opp,
                    "is_home": is_home,
                    "minutes": None,
                    "box": {"_no_game": 1},
                }
            )
            continue
        # Yahoo NBA stat_id 2 = MIN. (8 is FT%, easy to confuse.)
        try:
            minutes = float(box.get("2", 0)) or None
        except (TypeError, ValueError):
            minutes = None
        rows_to_write.append(
            {
                "player_id": player.id,
                "game_id": game_id,
                "game_date": d,
                "opponent_abbr": opp,
                "is_home": is_home,
                "minutes": minutes,
                "box": box,
            }
        )

    if rows_to_write:
        stmt = (
            pg_insert(NbaGameLog)
            .values(rows_to_write)
            .on_conflict_do_update(
                index_elements=["player_id", "game_id"],
                set_={
                    "opponent_abbr": pg_insert(NbaGameLog).excluded.opponent_abbr,
                    "is_home": pg_insert(NbaGameLog).excluded.is_home,
                    "minutes": pg_insert(NbaGameLog).excluded.minutes,
                    "box": pg_insert(NbaGameLog).excluded.box,
                },
            )
        )
        await db.execute(stmt)
        await db.commit()
        cached = await _existing_logs(db, player.id, candidate_dates)

    return [cached[d] for d in candidate_dates if d in cached]
