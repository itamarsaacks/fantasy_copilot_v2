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

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.connectors import yahoo as yahoo_client
from app.db.engine import get_session
from app.db.models import League, User
from app.jobs import freshness
from app.security import COOKIE_NAME, create_access_token, get_current_user

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
        raise HTTPException(status_code=400, detail=f"yahoo returned error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="missing code")
    if not state or not fc_oauth_state or not secrets.compare_digest(state, fc_oauth_state):
        # CSRF defense: state from query must match the state cookie we set.
        raise HTTPException(status_code=400, detail="invalid or missing state")

    # Step 3: exchange code for tokens
    token_payload = await yahoo_client.exchange_code(code)
    access_token = token_payload["access_token"]
    refresh_token = token_payload["refresh_token"]
    expires_in = int(token_payload.get("expires_in", 3600))
    # Yahoo no longer reliably returns xoauth_yahoo_guid in the token response.
    # Try it first, then fall back to a Fantasy API call.
    yahoo_guid = token_payload.get("xoauth_yahoo_guid")
    if not yahoo_guid:
        yahoo_guid = await yahoo_client.fetch_user_guid(access_token)
    if not yahoo_guid:
        raise HTTPException(status_code=502, detail="could not determine yahoo user guid")
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
    league_fetch_error: str | None = None
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
    except Exception as exc:
        league_fetch_error = str(exc)

    await db.commit()

    # Phase 7: kick off an immediate background sync so the user's data is
    # fresh by the time they reach the app. No-op in replay mode.
    background_tasks.add_task(freshness.trigger_initial_sync, user.id)

    # Set JWT cookie + return JSON for now. (Frontend redirect added in Phase 8.)
    jwt_value = create_access_token(user.id)
    response = JSONResponse(
        {
            "ok": True,
            "user_id": user.id,
            "yahoo_guid": user.yahoo_guid,
            "leagues_synced": leagues_synced,
            "league_fetch_error": league_fetch_error,
        }
    )
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


@router.get("/me")
async def me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    leagues_q = await db.execute(select(League).where(League.user_id == user.id))
    leagues = leagues_q.scalars().all()
    return {
        "user": {
            "id": user.id,
            "yahoo_guid": user.yahoo_guid,
            "auth_broken": user.auth_broken,
            "token_expires_at": user.token_expires_at.isoformat(),
        },
        "leagues": [
            {
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
