"""Tiered per-day game-log sync for the active player set.

Per master plan §2.2:

  • Live tier (every 30 min, 6pm–2am ET on NBA game days): refresh today
  • Nightly 3am ET: refresh yesterday for active player set
  • Backfill mode (CLI): date range with resumable cursor

Reuses `app.services.player_history.fetch_and_cache_logs` so we have one
implementation of "fetch + parse + write" — this job just drives it across
the active player set and enqueues standings-cache invalidations after.

Active player set = currently rostered, ever-drafted, or appearing on any
FreeAgent row from the last 30 days. (Materialized view is the next-pass
optimization; the query is cheap enough at current scale.)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date as date_type, timedelta
from typing import Iterable

from sqlalchemy import distinct, select, union
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import SessionLocal
from app.db.models import (
    FreeAgent,
    Player,
    PlayerOwnershipEvent,
    RosterPlayer,
    StandingsCacheInvalidation,
    User,
)
from app.services.clock import resolve_today
from app.services.player_history import fetch_and_cache_logs
from app.services.projection_invalidation import invalidate_for_players

log = logging.getLogger("sync_game_logs")

_BATCH = 25  # Yahoo per-date allows up to 25 player_keys; we proxy via
# fetch_and_cache_logs which is per-player. Keep batch concept for
# scheduling/sleeping rhythm.
_SLEEP_BETWEEN_PLAYERS = 0.0  # the inner helper already semaphore-limits


async def get_active_player_set(db: AsyncSession) -> list[Player]:
    """Players we care about syncing logs for.

    Union of:
    - currently rostered (RosterPlayer.player_id)
    - ever-drafted or transacted (PlayerOwnershipEvent.player_id)
    - currently-listed FA (FreeAgent.player_id)
    """
    rostered = select(distinct(RosterPlayer.player_id))
    transacted = select(distinct(PlayerOwnershipEvent.player_id))
    fas = select(distinct(FreeAgent.player_id))
    ids_q = union(rostered, transacted, fas).subquery()
    q = select(Player).where(Player.id.in_(select(ids_q.c.player_id)))
    return (await db.execute(q)).scalars().all()


async def _pick_syncing_user(db: AsyncSession) -> User | None:
    """We need any user's access_token to hit Yahoo. Game-log data is
    NBA-global so it doesn't matter which user we borrow from."""
    q = (
        select(User)
        .where(User.auth_broken.is_(False))
        .where(User.deleted_at.is_(None))
        .order_by(User.last_seen_at.desc().nullslast())
        .limit(1)
    )
    return (await db.execute(q)).scalar_one_or_none()


async def sync_logs_for_date(
    on_date: date_type,
    *,
    source: str = "yahoo",
) -> dict[str, int]:
    """Sync game logs for `on_date` for every player in the active set.

    Returns a counts dict for observability.
    """
    counts = {"players_attempted": 0, "logs_written": 0, "errors": 0}

    async with SessionLocal() as db:
        user = await _pick_syncing_user(db)
        if user is None:
            log.warning("no usable user; skipping sync_game_logs for %s", on_date)
            return counts

        players = await get_active_player_set(db)
        counts["players_attempted"] = len(players)
        if not players:
            return counts

        affected_dates: set[date_type] = set()
        affected_player_ids: set[int] = set()

        # Drive fetch_and_cache_logs per-player; it already handles
        # caching + semaphore-based concurrency.
        for player in players:
            try:
                logs = await fetch_and_cache_logs(
                    db, user, player, start=on_date, end=on_date
                )
                if logs:
                    counts["logs_written"] += len(logs)
                    affected_dates.add(on_date)
                    affected_player_ids.add(player.id)
            except Exception as e:  # noqa: BLE001
                counts["errors"] += 1
                log.warning(
                    "fetch_and_cache_logs failed for %s on %s: %s",
                    player.full_name,
                    on_date,
                    e,
                )
            await asyncio.sleep(_SLEEP_BETWEEN_PLAYERS)

        # Mark projections stale for every player whose game logs changed.
        # Eventual consistency — projections may lag by ~10 min until the
        # next read recomputes (master plan §2.7).
        if affected_player_ids:
            await invalidate_for_players(db, list(affected_player_ids))

        # Mark source on any rows just written (best-effort — won't run for
        # rows the helper already wrote with source='yahoo' default).
        # NOTE: helper currently writes default source='yahoo'; the
        # `source` arg here is for explicit backfill-mode tagging via the
        # backfill CLI path which writes via this job directly.

        # Enqueue standings-cache invalidations for the affected date.
        # Sweeper will fan these out to per-league cache rows.
        for d in affected_dates:
            await db.execute(
                pg_insert(StandingsCacheInvalidation).values(
                    league_id=None, on_date=d
                )
            )
        await db.commit()

    return counts


async def sync_nightly() -> dict[str, int]:
    """Run yesterday's sync. Wire into APScheduler at 3am ET nightly."""
    yesterday = resolve_today() - timedelta(days=1)
    log.info("nightly sync_game_logs for %s", yesterday)
    return await sync_logs_for_date(yesterday)


async def sync_live_tick() -> dict[str, int]:
    """Run today's sync. Wire into APScheduler every 30 min during NBA
    evenings (6pm–2am ET) but ONLY on game days. Caller gates by checking
    `nba_schedule` for any non-final game on `resolve_today()`."""
    today = resolve_today()
    log.info("live-tier sync_game_logs for %s", today)
    return await sync_logs_for_date(today)


async def backfill(
    start: date_type, end: date_type, *, source: str = "backfill"
) -> dict[str, int]:
    """Sync every date in [start, end]. Resumable via `backfill_cursor`.

    Note: doesn't yet read/write backfill_cursor in v1 — the CLI is for
    operator-driven runs with explicit dates. Wire cursor up in v2 once
    we have a sense of failure modes.
    """
    if start > end:
        raise ValueError("start must be <= end")
    totals = {"players_attempted": 0, "logs_written": 0, "errors": 0}
    cursor = start
    while cursor <= end:
        log.info("backfill date %s", cursor)
        day_counts = await sync_logs_for_date(cursor, source=source)
        for k in totals:
            totals[k] += day_counts[k]
        cursor += timedelta(days=1)
    return totals


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_nightly = sub.add_parser("nightly", help="sync yesterday")
    p_live = sub.add_parser("live", help="sync today (live tier)")
    p_backfill = sub.add_parser("backfill", help="sync a date range")
    p_backfill.add_argument("--from", dest="frm", required=True, type=str)
    p_backfill.add_argument("--to", required=True, type=str)

    p_nightly.add_argument("--verbose", "-v", action="store_true")
    p_live.add_argument("--verbose", "-v", action="store_true")
    p_backfill.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    if args.cmd == "nightly":
        result = asyncio.run(sync_nightly())
    elif args.cmd == "live":
        result = asyncio.run(sync_live_tick())
    elif args.cmd == "backfill":
        s = date_type.fromisoformat(args.frm)
        e = date_type.fromisoformat(args.to)
        result = asyncio.run(backfill(s, e))
    else:
        parser.error("unknown command")
        return

    print(result)


if __name__ == "__main__":
    cli()
