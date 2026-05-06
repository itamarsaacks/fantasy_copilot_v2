"""Token-refresh orchestration. Sits above connectors.yahoo (HTTP) and below
sync jobs / API routes (which need a guaranteed-fresh access token).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import yahoo
from app.db.models import User

# Refresh if the access token expires within this window. Yahoo tokens are
# typically 1 hour; we refresh ~5 min early to absorb clock skew + latency.
REFRESH_BUFFER = timedelta(minutes=5)


class YahooAuthBroken(Exception):
    """Raised when the refresh token itself is rejected (60-day inactivity, revoked, etc).

    The user's row will have auth_broken=True and they must reconnect.
    """


async def get_fresh_access_token(db: AsyncSession, user: User) -> str:
    """Return a guaranteed-fresh access token for `user`.

    Refreshes via Yahoo if the stored token is within REFRESH_BUFFER of expiry.
    Persists the new tokens. Raises YahooAuthBroken on permanent refresh failure.
    """
    if user.auth_broken:
        raise YahooAuthBroken("user must reconnect Yahoo")

    now = datetime.now(timezone.utc)
    if user.token_expires_at and user.token_expires_at - now > REFRESH_BUFFER:
        return user.access_token

    try:
        token_payload = await yahoo.refresh_access_token(user.refresh_token)
    except httpx.HTTPStatusError as exc:
        # Yahoo refused the refresh token. Mark broken and force reconnect.
        if exc.response.status_code in (400, 401, 403):
            user.auth_broken = True
            await db.commit()
            raise YahooAuthBroken(
                f"yahoo rejected refresh token ({exc.response.status_code})"
            ) from exc
        # Transient Yahoo error — re-raise without flipping auth_broken.
        raise

    user.access_token = token_payload["access_token"]
    # Yahoo issues a new refresh token on every refresh; rotate it.
    if token_payload.get("refresh_token"):
        user.refresh_token = token_payload["refresh_token"]
    expires_in = int(token_payload.get("expires_in", 3600))
    user.token_expires_at = now + timedelta(seconds=expires_in)
    user.auth_broken = False
    await db.commit()
    return user.access_token
