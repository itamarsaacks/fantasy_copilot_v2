"""Admin endpoints. Header-secret protected. Will move behind a proper admin
flag in Phase 10. Until then, treat as dev-only.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from app.config import get_settings
from app.engine.projection import compute_league_projections
from app.jobs import freshness
from app.jobs.sync_stats import sync_league_stats
from app.jobs.sync_yahoo import sync_league

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(x_admin_secret: str | None) -> None:
    secret = get_settings().admin_secret
    if not secret:
        raise HTTPException(status_code=503, detail="admin disabled (no ADMIN_SECRET)")
    if x_admin_secret != secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bad admin secret")


@router.post("/sync-now")
async def sync_now(
    user_id: int,
    league_id: int,
    x_admin_secret: str | None = Header(default=None),
):
    """Manually trigger a sync of (user_id, league_id). Returns SyncResult.

    Example:
        curl -X POST 'http://localhost:8000/admin/sync-now?user_id=1&league_id=2' \\
             -H "X-Admin-Secret: dev-admin-secret"
    """
    _require_admin(x_admin_secret)
    result = await sync_league(user_id=user_id, league_id=league_id)
    return {
        "league_key": result.league_key,
        "teams_synced": result.teams_synced,
        "rosters_synced": result.rosters_synced,
        "roster_players_total": result.roster_players_total,
        "free_agents_synced": result.free_agents_synced,
        "errors": result.errors,
    }


@router.post("/sync-stats")
async def sync_stats(
    user_id: int,
    league_id: int,
    coverage: str = "season",
    x_admin_secret: str | None = Header(default=None),
):
    """Fetch per-player stats for all rostered + FA players in a league."""
    _require_admin(x_admin_secret)
    result = await sync_league_stats(
        user_id=user_id, league_id=league_id, coverage=coverage
    )
    return {
        "league_key": result.league_key,
        "coverage": result.coverage,
        "players_attempted": result.players_attempted,
        "players_with_stats": result.players_with_stats,
        "stat_rows_written": result.stat_rows_written,
        "errors": result.errors,
    }


@router.post("/freshness-tick")
async def freshness_tick(x_admin_secret: str | None = Header(default=None)):
    """Run one freshness tick synchronously. Useful for tests + manual debug.

    In replay mode this returns `{"skipped": "replay"}` without touching Yahoo.
    """
    _require_admin(x_admin_secret)
    return await freshness.tick_once()


@router.post("/compute-projections")
async def compute_projections(
    league_id: int,
    x_admin_secret: str | None = Header(default=None),
):
    """Compute projection_cache for one league (points-leagues only for now)."""
    _require_admin(x_admin_secret)
    result = await compute_league_projections(league_id=league_id)
    return {
        "league_key": result.league_key,
        "scoring_type": result.scoring_type,
        "horizons_written": result.horizons_written,
        "rows_skipped_no_stats": result.rows_skipped_no_stats,
        "errors": result.errors,
    }
