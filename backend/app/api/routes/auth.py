"""Yahoo OAuth endpoints + the `/auth/me` introspection route.

Flow:
  1. GET /auth/yahoo/login    -> redirect user to Yahoo's authorize URL
  2. (user logs in at Yahoo + approves)
  3. GET /auth/yahoo/callback -> Yahoo redirects here with `code` and `state`
                                 we exchange code for tokens, fetch leagues,
                                 store user+leagues, set JWT cookie
  4. GET /auth/me             -> returns the current authenticated user
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.connectors import yahoo as yahoo_client
from app.db.engine import get_session
from app.db.models import League, User
from app.jobs import freshness
from app.security import COOKIE_NAME, create_access_token, get_current_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

STATE_COOKIE = "fc_oauth_state"
STATE_TTL_SECONDS = 600  # 10 minutes


@router.get("/yahoo/login")
async def yahoo_login() -> RedirectResponse:
    """Generate CSRF state, set it as a cookie, redirect browser to Yahoo."""
    state = secrets.token_urlsafe(32)
    url = yahoo_client.build_authorize_url(state)
    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        key=STATE_COOKIE,
        value=state,
        max_age=STATE_TTL_SECONDS,
        httponly=True,
        secure=False,  # localhost dev — flip to True in production
        samesite="lax",
    )
    return response


@router.get("/yahoo/callback")
async def yahoo_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    fc_oauth_state: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_session),
):
    if error:
        log.warning("oauth callback: yahoo returned error=%r", error)
        return RedirectResponse(url="/login?error=oauth", status_code=302)
    if not code:
        log.warning("oauth callback: no code in callback URL")
        return RedirectResponse(url="/login?error=oauth", status_code=302)
    if not state or not fc_oauth_state or not secrets.compare_digest(state, fc_oauth_state):
        # CSRF defense: state from query must match the state cookie we set.
        log.warning("oauth callback: state mismatch or missing state cookie")
        return RedirectResponse(url="/login?error=oauth", status_code=302)

    try:
        token_payload = await yahoo_client.exchange_code(code)
    except Exception as exc:  # noqa: BLE001
        body = getattr(getattr(exc, "response", None), "text", "")
        log.error("oauth exchange_code failed: %s | body=%s", exc, body[:500])
        return RedirectResponse(url="/login?error=oauth_exchange_failed", status_code=302)

    access_token = token_payload["access_token"]
    refresh_token = token_payload["refresh_token"]
    expires_in = int(token_payload.get("expires_in", 3600))

    # GUID: token response field -> id_token `sub` -> Fantasy API (last resort;
    # 403s unless Yahoo has approved the app for Fantasy access).
    yahoo_guid = token_payload.get("xoauth_yahoo_guid") or yahoo_client.guid_from_id_token(
        token_payload.get("id_token")
    )
    if not yahoo_guid:
        try:
            yahoo_guid = await yahoo_client.fetch_user_guid(access_token)
        except Exception as exc:  # noqa: BLE001
            log.error("oauth fetch_user_guid failed: %s", exc)
            return RedirectResponse(url="/login?error=oauth_guid_failed", status_code=302)
    if not yahoo_guid:
        return RedirectResponse(url="/login?error=oauth_no_guid", status_code=302)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # Upsert user
    result = await db.execute(select(User).where(User.yahoo_guid == yahoo_guid))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(yahoo_guid=yahoo_guid)
        db.add(user)
    user.access_token = access_token
    user.refresh_token = refresh_token
    user.token_expires_at = expires_at
    user.auth_broken = False
    user.deleted_at = None
    await db.flush()  # populate user.id

    # Fetch + upsert leagues. Wrapped separately so a Yahoo league fetch failure
    # still leaves the user record + tokens intact.
    leagues_synced = 0
    league_fetch_error: str | None = None  # short code, surfaced as ?warn=
    try:
        leagues = await yahoo_client.fetch_nba_leagues(access_token)
        for league_data in leagues:
            existing = await db.execute(
                select(League).where(
                    League.user_id == user.id,
                    League.league_key == league_data["league_key"],
                )
            )
            league = existing.scalar_one_or_none()
            if league is None:
                league = League(user_id=user.id, league_key=league_data["league_key"])
                db.add(league)
            league.name = league_data["name"]
            league.scoring_type = league_data["scoring_type"]
            league.num_teams = league_data["num_teams"]
            league.current_week = league_data["current_week"]
            league.season = league_data["season"]
            league.settings_json = league_data["settings_raw"]
            leagues_synced += 1
    except Exception as exc:  # noqa: BLE001
        log.error("oauth league fetch failed: %s", exc)
        league_fetch_error = (
            "yahoo_not_approved" if yahoo_client.is_not_authorized(exc) else "league_fetch_failed"
        )

    await db.commit()

    # Phase 7: kick off an immediate background sync so the user's data is
    # fresh by the time they reach the app. No-op in replay mode.
    background_tasks.add_task(freshness.trigger_initial_sync, user.id)

    # Set JWT cookie + redirect the browser to /chat on the same origin.
    # In dev with ngrok->frontend setup, this is the ngrok URL; in production
    # it's whatever domain serves both backend and frontend.
    jwt_value = create_access_token(user.id)

    # The user lands in /chat regardless; a league fetch failure rides along
    # as a short code the frontend turns into a banner.
    redirect_target = f"/chat?warn={league_fetch_error}" if league_fetch_error else "/chat"

    response = RedirectResponse(url=redirect_target, status_code=302)
    settings = get_settings()
    response.set_cookie(
        key=COOKIE_NAME,
        value=jwt_value,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=int(timedelta(days=30).total_seconds()),
    )
    response.delete_cookie(STATE_COOKIE)
    return response


@router.get("/demo")
async def demo_login(
    db: AsyncSession = Depends(get_session),
):
    """One-click demo sign-in as the seeded user.

    Enabled when `DEMO_USER_ID` is set to a positive integer in backend/.env.
    Mints a JWT for that user and redirects to /chat — no OAuth involved.
    Read-only from the app's perspective (no writes to Yahoo).

    Meant for portfolio / CV visits so recruiters can try the app without
    connecting a Yahoo account. Set DEMO_USER_ID=0 (default) to disable.
    """
    settings = get_settings()
    if not settings.demo_user_id or settings.demo_user_id <= 0:
        return RedirectResponse(url="/login?error=demo_disabled", status_code=302)

    user = await db.get(User, settings.demo_user_id)
    if user is None:
        return RedirectResponse(url="/login?error=demo_user_missing", status_code=302)

    jwt_value = create_access_token(user.id)
    response = RedirectResponse(url="/chat?demo=1", status_code=302)
    response.set_cookie(
        key=COOKIE_NAME,
        value=jwt_value,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=int(timedelta(days=30).total_seconds()),
    )
    return response


@router.get("/me")
async def me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    leagues_q = await db.execute(select(League).where(League.user_id == user.id))
    leagues = leagues_q.scalars().all()
    settings = get_settings()
    return {
        "user": {
            "id": user.id,
            "yahoo_guid": user.yahoo_guid,
            "auth_broken": user.auth_broken,
            "token_expires_at": user.token_expires_at.isoformat(),
            "is_admin": user.id in settings.admin_user_id_set,
        },
        "leagues": [
            {
                "id": lg.id,
                "league_key": lg.league_key,
                "name": lg.name,
                "scoring_type": lg.scoring_type,
                "num_teams": lg.num_teams,
                "current_week": lg.current_week,
                "season": lg.season,
            }
            for lg in leagues
        ],
    }


@router.post("/logout")
async def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME)
    return response
