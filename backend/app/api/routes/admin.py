"""Admin endpoints. Header-secret protected. Will move behind a proper admin
flag in Phase 10. Until then, treat as dev-only.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from app.config import get_settings
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
