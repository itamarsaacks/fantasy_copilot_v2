"""Production auto-backfill — startup hook + per-league hook.

The one-shot CLIs in `backend/scripts/` are fine for an operator running a
fresh deploy. But for a real multi-user product, missing data shouldn't
require SSH access. This module wires the same code into two automatic
triggers:

1. **Startup hook** (`maybe_backfill_on_startup`):
   - Called from `main.py` lifespan AFTER the freshness scheduler starts.
   - Checks DB coverage. If ESPN player IDs or headshots are below
     threshold, kicks off the corresponding backfill in a background task.
   - Idempotent — re-running on a hot deploy is a no-op.
   - Never blocks startup; failures log + move on.

2. **Per-new-league hook** (`schedule_initial_game_logs_backfill`):
   - Called from `sync_yahoo.sync_league` after a brand-new league's
     first full sync.
   - Queues a current-season game-log backfill for that league's active
     players so a new signup's drawer/standings work within minutes.
   - Uses the existing parallel `sync_game_logs.backfill()` helper.

Both run as `asyncio.create_task(...)` — the calling request returns
immediately, the work happens in the background.

Per master plan §2.A: NEVER calls forbidden hostnames. Both backfills
hit only Yahoo + ESPN (allow-list) via the existing scripts.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date as date_type, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import SessionLocal
from app.db.models import Player

log = logging.getLogger(__name__)

# How many missing players triggers an auto-backfill. A few rookies trickling
# in (< this) ride the nightly reconcile; a deploy-time gap kicks the script.
_ESPN_ID_THRESHOLD = 20
_HEADSHOT_THRESHOLD = 20

# Track running tasks so we don't fire them twice from the same process.
_running: set[str] = set()


async def _count_missing(db: AsyncSession) -> tuple[int, int]:
    """Returns (players_without_espn_id, players_without_headshot_path)."""
    missing_id = (
        await db.execute(
            select(func.count(Player.id)).where(Player.espn_player_id.is_(None))
        )
    ).scalar() or 0
    missing_headshot = (
        await db.execute(
            select(func.count(Player.id))
            .where(Player.espn_player_id.isnot(None))
            .where(Player.headshot_path.is_(None))
        )
    ).scalar() or 0
    return int(missing_id), int(missing_headshot)


async def _run_espn_backfill() -> None:
    """Wraps scripts.backfill_espn_player_ids.main() — fire-and-forget."""
    if "espn_ids" in _running:
        log.info("auto-backfill: espn_ids already running, skipping")
        return
    _running.add("espn_ids")
    try:
        from scripts.backfill_espn_player_ids import main as run

        log.info("auto-backfill: starting ESPN player IDs backfill")
        await run(dry_run=False, only_missing=True)
        log.info("auto-backfill: ESPN player IDs backfill complete")
    except Exception as e:  # noqa: BLE001
        log.warning("auto-backfill: ESPN backfill failed: %s", e)
    finally:
        _running.discard("espn_ids")


async def _run_headshot_download() -> None:
    """Wraps scripts.download_headshots.main() — fire-and-forget."""
    if "headshots" in _running:
        log.info("auto-backfill: headshots already running, skipping")
        return
    _running.add("headshots")
    try:
        from scripts.download_headshots import main as run

        log.info("auto-backfill: starting headshot download")
        await run(only_missing=True)
        log.info("auto-backfill: headshot download complete")
    except Exception as e:  # noqa: BLE001
        log.warning("auto-backfill: headshot download failed: %s", e)
    finally:
        _running.discard("headshots")


async def maybe_backfill_on_startup() -> None:
    """Called from main.py lifespan. Checks coverage + kicks off backfills.

    Non-blocking — always schedules as background tasks. Safe to call
    every startup; threshold + idempotent script guards prevent thrash.
    """
    async with SessionLocal() as db:
        missing_id, missing_headshot = await _count_missing(db)

    if missing_id >= _ESPN_ID_THRESHOLD:
        log.info(
            "auto-backfill: %d players missing espn_player_id "
            "(threshold %d) — scheduling backfill",
            missing_id,
            _ESPN_ID_THRESHOLD,
        )
        asyncio.create_task(_run_espn_backfill())
    else:
        log.info(
            "auto-backfill: ESPN id coverage healthy (only %d missing)",
            missing_id,
        )

    if missing_headshot >= _HEADSHOT_THRESHOLD:
        log.info(
            "auto-backfill: %d players missing headshot_path "
            "(threshold %d) — scheduling download",
            missing_headshot,
            _HEADSHOT_THRESHOLD,
        )
        # Wait a beat so ESPN backfill (if also queued) gets ahead of us —
        # headshots need espn_player_id populated.
        async def _delayed():
            await asyncio.sleep(60)
            await _run_headshot_download()

        asyncio.create_task(_delayed())
    else:
        log.info(
            "auto-backfill: headshot coverage healthy (only %d missing)",
            missing_headshot,
        )


async def schedule_initial_game_logs_backfill(
    league_id: int,
    days_back: int = 30,
    coverage_threshold: int = 100,
) -> None:
    """Called after a league's sync — populate recent game logs if missing.

    Pulls the last `days_back` calendar days of game logs for the active
    player set. By default 30 days = enough for the Players-tab timeline
    + Last-7 / Last-14 / Last-30 windows to work immediately.

    Self-gating: checks if the league already has substantial recent
    coverage (more than `coverage_threshold` rows for its rostered
    players in the last 7 days). If yes, skips — the nightly sync is
    keeping the league fresh. If no, queues a full backfill.

    Idempotent: `sync_game_logs.backfill()` upserts by (player_id, game_date)
    so even when this DOES queue, re-running is safe.

    Fire-and-forget — does NOT block the calling request. New signups
    see data populate within ~1-3 min after first login.
    """
    from app.jobs.sync_game_logs import backfill
    from app.services.clock import resolve_today
    from app.db.models import NbaGameLog, RosterPlayer, Team
    from sqlalchemy import and_

    # Coverage check: how many recent game logs exist for this league's roster?
    async with SessionLocal() as db:
        today = resolve_today()
        cutoff = today - timedelta(days=7)
        # Players currently on any team in this league
        rostered_q = (
            select(func.count(NbaGameLog.id))
            .join(RosterPlayer, RosterPlayer.player_id == NbaGameLog.player_id)
            .join(Team, Team.id == RosterPlayer.team_id)
            .where(
                and_(
                    Team.league_id == league_id,
                    NbaGameLog.game_date >= cutoff,
                )
            )
        )
        recent_count = (await db.execute(rostered_q)).scalar() or 0

    if recent_count >= coverage_threshold:
        log.info(
            "auto-backfill: league %s has %d recent game-log rows "
            "(threshold %d) — coverage healthy, skipping",
            league_id,
            recent_count,
            coverage_threshold,
        )
        return

    key = f"initial_game_logs:{league_id}"
    if key in _running:
        log.info("auto-backfill: initial game logs for league %s already running", league_id)
        return
    _running.add(key)

    async def _go():
        try:
            end = resolve_today()
            start = end - timedelta(days=days_back)
            log.info(
                "auto-backfill: scheduling initial game-log backfill for league %s, "
                "range %s..%s",
                league_id,
                start,
                end,
            )
            result = await backfill(start, end, source="auto_initial")
            log.info(
                "auto-backfill: initial game logs for league %s done: %s",
                league_id,
                result,
            )
        except Exception as e:  # noqa: BLE001
            log.warning(
                "auto-backfill: initial game logs for league %s failed: %s",
                league_id,
                e,
            )
        finally:
            _running.discard(key)

    asyncio.create_task(_go())
