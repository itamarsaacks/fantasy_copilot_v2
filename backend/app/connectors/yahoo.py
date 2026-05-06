"""Yahoo Fantasy Sports API client — OAuth dance + league discovery.

Phase 2 scope: just the auth flow + fetching the user's NBA leagues. Roster /
free-agent / stats fetching lands in Phase 3.

Hard-won notes (do NOT lose):
- /players;player_keys=.../stats;type=X works. ;out=stats;type=X silently
  ignores the type filter. Use the first form when we add stat fetching.
- The Fantasy API returns deeply nested mixed list/dict structures. Helpers
  here flatten them.
- 2025-26 NBA game key = 466. We hard-code it; revisit each season.
"""

from __future__ import annotations

from base64 import b64encode
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings

NBA_GAME_KEY = "466"  # 2025-26 season

AUTHORIZE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
FANTASY_API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"


def build_authorize_url(state: str) -> str:
    """Step 1 of OAuth: where to send the user's browser."""
    settings = get_settings()
    params = {
        "client_id": settings.yahoo_client_id,
        "redirect_uri": settings.yahoo_redirect_uri,
        "response_type": "code",
        "state": state,
        "language": "en-us",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _basic_auth_header() -> dict[str, str]:
    settings = get_settings()
    creds = f"{settings.yahoo_client_id}:{settings.yahoo_client_secret}".encode()
    return {"Authorization": f"Basic {b64encode(creds).decode()}"}


async def exchange_code(code: str) -> dict[str, Any]:
    """Step 3 of OAuth: code -> tokens. Returns the raw token dict from Yahoo."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_URL,
            headers={
                **_basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "redirect_uri": settings.yahoo_redirect_uri,
                "code": code,
            },
        )
    resp.raise_for_status()
    return resp.json()


async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """Use a refresh token to get a fresh access token."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_URL,
            headers={
                **_basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "redirect_uri": settings.yahoo_redirect_uri,
                "refresh_token": refresh_token,
            },
        )
    resp.raise_for_status()
    return resp.json()


async def fetch_user_guid(access_token: str) -> str | None:
    """Fetch the logged-in user's Yahoo GUID via the Fantasy API.

    Yahoo no longer reliably returns `xoauth_yahoo_guid` in the token response,
    so we ask Fantasy directly. Returns None if the response shape is unexpected.
    """
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    url = f"{FANTASY_API_BASE}/users;use_login=1?format=json"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)
    resp.raise_for_status()
    payload = resp.json()
    try:
        user_list = payload["fantasy_content"]["users"]["0"]["user"]
        # user_list is a list; the first dict element holds {"guid": "..."}
        for item in user_list:
            if isinstance(item, dict) and "guid" in item:
                return item["guid"]
    except (KeyError, IndexError, TypeError):
        pass
    return None


async def fetch_nba_leagues(access_token: str) -> list[dict[str, Any]]:
    """Return all NBA leagues the user belongs to, with settings.

    Output: list of dicts with keys: league_key, name, scoring_type, num_teams,
    current_week, season, settings_raw (the full settings dict from Yahoo).
    """
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    url = (
        f"{FANTASY_API_BASE}/users;use_login=1/games;game_keys={NBA_GAME_KEY}/"
        f"leagues;out=settings?format=json"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)
    resp.raise_for_status()
    return _parse_leagues(resp.json())


def _parse_leagues(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten Yahoo's deeply nested league response into clean dicts.

    The payload looks roughly like:
      fantasy_content.users."0".user[1].games."0".game[1].leagues."0".league[<list>]
    Each league entry is itself a list whose first element holds metadata and
    later elements hold settings.
    """
    leagues_out: list[dict[str, Any]] = []
    try:
        users = payload["fantasy_content"]["users"]["0"]["user"]
        # users[0] is identity; users[1] holds the games dict
        games_block = next(item for item in users[1:] if isinstance(item, dict) and "games" in item)
        games = games_block["games"]
    except (KeyError, IndexError, StopIteration):
        return []

    # games count is at games["count"]; entries keyed by "0", "1", ...
    count = int(games.get("count", 0))
    for i in range(count):
        game_wrapper = games.get(str(i), {}).get("game")
        if not game_wrapper:
            continue
        # game_wrapper is a list; find the leagues block inside it
        leagues_block = next(
            (item for item in game_wrapper[1:] if isinstance(item, dict) and "leagues" in item),
            None,
        )
        if not leagues_block:
            continue
        leagues = leagues_block["leagues"]
        league_count = int(leagues.get("count", 0))
        for j in range(league_count):
            league_entry = leagues.get(str(j), {}).get("league")
            if not league_entry:
                continue
            parsed = _parse_one_league(league_entry)
            if parsed:
                leagues_out.append(parsed)
    return leagues_out


def _parse_one_league(league_entry: list[Any]) -> dict[str, Any] | None:
    """Each league entry is [metadata_dict, {'settings': [settings_dict]}, ...]."""
    if not league_entry:
        return None

    meta: dict[str, Any] = {}
    settings_raw: dict[str, Any] = {}

    for item in league_entry:
        if isinstance(item, list):
            for sub in item:
                if isinstance(sub, dict):
                    meta.update(sub)
        elif isinstance(item, dict):
            if "settings" in item:
                settings_list = item["settings"]
                if isinstance(settings_list, list) and settings_list:
                    settings_raw = settings_list[0] if isinstance(settings_list[0], dict) else {}
                elif isinstance(settings_list, dict):
                    settings_raw = settings_list
            else:
                meta.update(item)

    if not meta.get("league_key"):
        return None

    return {
        "league_key": meta["league_key"],
        "name": meta.get("name", "Unknown League"),
        "scoring_type": meta.get("scoring_type", "head2head_points"),
        "num_teams": int(meta.get("num_teams", 0)),
        "current_week": int(meta["current_week"]) if meta.get("current_week") else None,
        "season": str(meta.get("season", "")),
        "settings_raw": settings_raw,
    }
