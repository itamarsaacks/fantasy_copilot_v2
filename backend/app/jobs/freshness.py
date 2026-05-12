"""Freshness controller — tiered, active-user-aware Yahoo sync scheduler.

Lifecycle: started in app.main lifespan, stopped on shutdown.

Per tick (every 60s):
  1. If APP_MODE=replay, return immediately. Tests rely on this.
  2. Find active users: last_seen_at within ACTIVE_WINDOW, not auth_broken,
     not soft-deleted. For each user x league, consult SYNC_TIERS:
       - "roster" tier (every 30 min): runs sync_yahoo.sync_league
       - "stats"  tier (every 6  h):   runs sync_stats then projection compute
  3. 999 detection -> 30-min backoff per user. Generic exceptions are logged
     and the loop continues; one bad user can never kill the worker.
  4. TTL purge of in-memory dicts to bound memory.

State is in-memory only — restart loses the schedule and everyone's first
post-restart tick will hit the roster tier. That's fine; it's safe to over-sync.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import get_settings
from app.db.engine import SessionLocal
from app.db.models import League, User
from app.engine.projection import compute_league_projections
from app.jobs.sync_schedule import sync_schedule
from app.jobs.sync_stats import sync_league_stats
from app.jobs.sync_yahoo import sync_league

log = logging.getLogger(__name__)

# Tunables
TICK_SECONDS = 60
ACTIVE_WINDOW = timedelta(minutes=10)
RATE_LIMIT_BACKOFF = timedelta(minutes=30)
TTL_INACTIVE = timedelta(hours=24)


# Tier definitions: add new tiers (news, transactions, scoreboard, ...) here.
async def _run_roster(user_id: int, league_id: int) -> list[str]:
    result = await sync_league(user_id=user_id, league_id=league_id)
    return list(result.errors)


async def _run_stats_and_projection(user_id: int, league_id: int) -> list[str]:
    stats_result = await sync_league_stats(
        user_id=user_id, league_id=league_id, coverage="season"
    )
    errors = list(stats_result.errors)
    proj_result = await compute_league_projections(league_id=league_id)
    errors.extend(proj_result.errors)
    return errors


SYNC_TIERS: dict[str, dict] = {
    "roster": {
        "interval": timedelta(minutes=30),
        "fn": _run_roster,
    },
    "stats": {
        "interval": timedelta(hours=6),
        "fn": _run_stats_and_projection,
    },
}


# Module-level state. Process-local; OK to lose on restart.
_scheduler: AsyncIOScheduler | None = None
# (user_id, league_id, tier) -> datetime of last successful run start.
_last_run: dict[tuple[int, int, str], datetime] = {}
# user_id -> datetime until which we skip this user (Yahoo 999).
_backoff_until: dict[int, datetime] = {}
# user_ids currently being synced (initial_sync guard).
_currently_syncing: set[int] = set()


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------


def start() -> None:
    """Start the scheduler. Idempotent."""
    global _scheduler
    if _scheduler is not None:
        return
    settings = get_settings()
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        tick_once,
        trigger=IntervalTrigger(seconds=TICK_SECONDS),
        id="freshness_tick",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # Global, league-agnostic. Once a day is enough — schedules only change
    # when games complete or get rescheduled. Cheap (~30 ESPN calls).
    _scheduler.add_job(
        sync_schedule,
        trigger=IntervalTrigger(hours=24),
        id="nba_schedule_sync",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    _scheduler.start()
    log.info(
        "freshness scheduler started (mode=%s, tick=%ss)",
        settings.app_mode,
        TICK_SECONDS,
    )


async def stop() -> None:
    """Stop the scheduler. Idempotent."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    log.info("freshness scheduler stopped")


async def tick_once() -> dict:
    """Run a single freshness pass. Exposed for the admin endpoint + tests.

    Returns a small summary dict for observability.
    """
    settings = get_settings()
    if settings.app_mode == "replay":
        log.debug("freshness tick skipped: replay mode")
        return {"skipped": "replay"}

    now = datetime.now(timezone.utc)
    cutoff = now - ACTIVE_WINDOW

    summary = {
        "n_active_users": 0,
        "n_synced": 0,
        "n_skipped_backoff": 0,
        "n_errors": 0,
    }

    async with SessionLocal() as session:
        active_q = await session.execute(
            select(User).where(
                User.last_seen_at.isnot(None),
                User.last_seen_at > cutoff,
                User.auth_broken.is_(False),
                User.deleted_at.is_(None),
            )
        )
        active_users = list(active_q.scalars().all())
        summary["n_active_users"] = len(active_users)

        for user in active_users:
            backoff_until = _backoff_until.get(user.id)
            if backoff_until and backoff_until > now:
                summary["n_skipped_backoff"] += 1
                continue

            leagues_q = await session.execute(
                select(League).where(League.user_id == user.id)
            )
            leagues = list(leagues_q.scalars().all())

            for league in leagues:
                for tier_name, tier in SYNC_TIERS.items():
                    last = _last_run.get((user.id, league.id, tier_name))
                    if last and (now - last) < tier["interval"]:
                        continue
                    try:
                        errors = await _run_tier(
                            tier["fn"], user.id, league.id, tier_name
                        )
                    except Exception:
                        log.exception(
                            "tier %s crashed for user=%s league=%s",
                            tier_name,
                            user.id,
                            league.id,
                        )
                        summary["n_errors"] += 1
                        continue

                    _last_run[(user.id, league.id, tier_name)] = now
                    if _is_yahoo_rate_limit(errors):
                        _backoff_until[user.id] = now + RATE_LIMIT_BACKOFF
                        log.warning(
                            "yahoo 999 detected; backing off user=%s for %s",
                            user.id,
                            RATE_LIMIT_BACKOFF,
                        )
                        # Stop touching this user this tick.
                        break
                    if errors:
                        log.warning(
                            "tier %s errors for user=%s league=%s: %s",
                            tier_name,
                            user.id,
                            league.id,
                            errors,
                        )
                    summary["n_synced"] += 1
                else:
                    continue
                break  # broke inner tier loop -> break league loop too

        # Auth-broken visibility — surfaced separately so we don't lose track.
        broken_q = await session.execute(
            select(User).where(
                User.auth_broken.is_(True),
                User.last_seen_at.isnot(None),
                User.last_seen_at > cutoff,
                User.deleted_at.is_(None),
            )
        )
        for u in broken_q.scalars().all():
            log.warning("auth_broken user is active: id=%s guid=%s", u.id, u.yahoo_guid)

    _purge_stale_state(active_user_ids={u.id for u in active_users}, now=now)
    log.info("freshness tick done: %s", summary)
    return summary


async def trigger_initial_sync(user_id: int) -> None:
    """On-login hook. Run roster sync inline, then schedule stats+projection
    as a follow-up task so the user perceives the fastest possible response.

    No-op in replay mode and when a sync is already in flight for this user.
    """
    settings = get_settings()
    if settings.app_mode == "replay":
        log.info("initial sync skipped: replay mode (user=%s)", user_id)
        return

    if user_id in _currently_syncing:
        log.info("initial sync already in flight for user=%s", user_id)
        return

    _currently_syncing.add(user_id)
    now = datetime.now(timezone.utc)
    try:
        async with SessionLocal() as session:
            leagues_q = await session.execute(
                select(League).where(League.user_id == user_id)
            )
            league_ids = [lg.id for lg in leagues_q.scalars().all()]

        if not league_ids:
            log.info("initial sync: user=%s has no leagues", user_id)
            return

        # Phase A: roster, inline.
        for league_id in league_ids:
            try:
                errors = await _run_tier(
                    SYNC_TIERS["roster"]["fn"], user_id, league_id, "roster"
                )
            except Exception:
                log.exception("initial roster sync crashed for league=%s", league_id)
                continue
            _last_run[(user_id, league_id, "roster")] = now
            if _is_yahoo_rate_limit(errors):
                _backoff_until[user_id] = now + RATE_LIMIT_BACKOFF
                log.warning("initial sync: 999 from yahoo, aborting follow-up")
                return

        # Phase B: stats + projections, queued as separate task.
        asyncio.create_task(_initial_stats_followup(user_id, league_ids))
    finally:
        _currently_syncing.discard(user_id)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _run_tier(
    fn: Callable[[int, int], Awaitable[list[str]]],
    user_id: int,
    league_id: int,
    tier_name: str,
) -> list[str]:
    log.info("freshness running tier=%s user=%s league=%s", tier_name, user_id, league_id)
    return await fn(user_id, league_id)


async def _initial_stats_followup(user_id: int, league_ids: list[int]) -> None:
    now = datetime.now(timezone.utc)
    for league_id in league_ids:
        if user_id in _backoff_until and _backoff_until[user_id] > datetime.now(timezone.utc):
            return
        try:
            errors = await _run_tier(
                SYNC_TIERS["stats"]["fn"], user_id, league_id, "stats"
            )
        except Exception:
            log.exception(
                "initial stats follow-up crashed user=%s league=%s", user_id, league_id
            )
            continue
        _last_run[(user_id, league_id, "stats")] = now
        if _is_yahoo_rate_limit(errors):
            _backoff_until[user_id] = now + RATE_LIMIT_BACKOFF
            log.warning("initial follow-up: 999 from yahoo, stopping")
            return


def _is_yahoo_rate_limit(errors: list[str]) -> bool:
    """SyncResult.errors are stringified exceptions. Yahoo's rate-limit
    response is HTTP 999, so any error containing '999' is treated as one.
    """
    for err in errors:
        if "999" in err:
            return True
    return False


def _purge_stale_state(active_user_ids: set[int], now: datetime) -> None:
    """Drop entries for users who haven't been active in TTL_INACTIVE.

    Called at end of each tick. Keeps in-memory dicts bounded.
    """
    # _backoff_until: drop expired entries entirely.
    for uid in list(_backoff_until.keys()):
        if _backoff_until[uid] <= now:
            _backoff_until.pop(uid, None)

    # _last_run: drop entries for users not in the active set, and only if
    # their oldest run is older than TTL_INACTIVE. Cheap heuristic.
    cutoff = now - TTL_INACTIVE
    for key in list(_last_run.keys()):
        uid, _league_id, _tier = key
        if uid in active_user_ids:
            continue
        if _last_run[key] < cutoff:
            _last_run.pop(key, None)
