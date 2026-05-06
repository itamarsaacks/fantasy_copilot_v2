"""Yahoo Fantasy Sports API client — OAuth + league/team/roster/FA fetch.

Hard-won notes (do NOT lose):
- /players;player_keys=.../stats;type=X works. ;out=stats;type=X silently
  ignores the type filter. Use the first form when we add stat fetching.
- The Fantasy API returns deeply nested mixed list/dict structures. Helpers
  here flatten them.
- 2025-26 NBA game key = 466. We hard-code it; revisit each season.
- Yahoo no longer reliably returns xoauth_yahoo_guid in the token response.
  Use fetch_user_guid via /users;use_login=1 instead.
- FA fetching is paginated; default count=25, max=25. Use start= to page.
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


async def fetch_teams(access_token: str, league_key: str) -> list[dict[str, Any]]:
    """Return all teams in a league with metadata.

    Output: list of dicts with team_key, team_id_in_league, name, manager_name,
    is_user_team, wins, losses, ties, rank.
    """
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    url = f"{FANTASY_API_BASE}/league/{league_key}/teams;out=standings?format=json"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)
    resp.raise_for_status()
    return _parse_teams(resp.json())


def _parse_teams(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        teams = payload["fantasy_content"]["league"][1]["teams"]
    except (KeyError, IndexError, TypeError):
        return []
    count = int(teams.get("count", 0))
    for i in range(count):
        team_entry = teams.get(str(i), {}).get("team")
        if not team_entry:
            continue
        parsed = _parse_one_team(team_entry)
        if parsed:
            out.append(parsed)
    return out


def _parse_one_team(team_entry: list[Any]) -> dict[str, Any] | None:
    """Each team entry shape: [[meta_dicts...], {"team_standings": {...}}, ...].

    Yahoo packs a LOT into the metadata dicts on the first element:
      team_key, team_id, name, url, team_logos, waiver_priority, faab_balance,
      division_id, number_of_moves, number_of_trades, roster_adds,
      league_scoring_type, has_draft_grade, draft_grade, draft_recap_url,
      managers, clinched_playoffs, is_owned_by_current_login.
    """
    meta: dict[str, Any] = {}
    standings: dict[str, Any] = {}
    is_user = False
    manager_name: str | None = None
    manager_id: str | None = None
    logo_url: str | None = None

    if not team_entry:
        return None

    first = team_entry[0]
    if isinstance(first, list):
        for sub in first:
            if not isinstance(sub, dict):
                continue
            if "is_owned_by_current_login" in sub:
                is_user = bool(int(sub["is_owned_by_current_login"]))
            if "managers" in sub:
                managers = sub["managers"]
                if isinstance(managers, list) and managers:
                    mgr = managers[0].get("manager", {}) if isinstance(managers[0], dict) else {}
                    manager_name = mgr.get("nickname")
                    manager_id = mgr.get("manager_id")
            if "team_logos" in sub:
                logos = sub["team_logos"]
                if isinstance(logos, list) and logos:
                    logo_block = logos[0].get("team_logo", {}) if isinstance(logos[0], dict) else {}
                    logo_url = logo_block.get("url") if isinstance(logo_block, dict) else None
            meta.update({k: v for k, v in sub.items() if not isinstance(v, (list, dict))})

    for item in team_entry[1:]:
        if isinstance(item, dict) and "team_standings" in item:
            standings = item["team_standings"]

    if not meta.get("team_key"):
        return None

    outcome_totals = (standings or {}).get("outcome_totals") or {}

    return {
        "team_key": meta["team_key"],
        "team_id_in_league": int(meta.get("team_id", 0)),
        "name": meta.get("name", "Unknown Team"),
        "manager_name": manager_name,
        "manager_id": manager_id,
        "logo_url": logo_url,
        "is_user_team": is_user,
        "wins": _safe_int(outcome_totals.get("wins")),
        "losses": _safe_int(outcome_totals.get("losses")),
        "ties": _safe_int(outcome_totals.get("ties")),
        "rank": _safe_int(standings.get("rank") if standings else None),
        "points_for": _safe_float((standings or {}).get("points_for")),
        "points_against": _safe_float((standings or {}).get("points_against")),
        "faab_balance": _safe_int(meta.get("faab_balance")),
        "waiver_priority": _safe_int(meta.get("waiver_priority")),
        "clinched_playoffs": bool(int(meta["clinched_playoffs"]))
        if meta.get("clinched_playoffs") not in (None, "")
        else None,
        "division_id": str(meta["division_id"]) if meta.get("division_id") not in (None, "") else None,
        "number_of_moves": _safe_int(meta.get("number_of_moves")),
        "number_of_trades": _safe_int(meta.get("number_of_trades")),
        "draft_grade": meta.get("draft_grade") or None,
    }


async def fetch_team_roster(access_token: str, team_key: str) -> list[dict[str, Any]]:
    """Return all players currently on a team's roster, with rich player metadata.

    Uses /team/{key}/roster/players;out=... to get percent_owned, ranks,
    draft_analysis inline rather than making a second call per player.
    """
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    url = (
        f"{FANTASY_API_BASE}/team/{team_key}/roster/players;"
        f"out=percent_owned,percent_started,ranks,draft_analysis?format=json"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)
    resp.raise_for_status()
    return _parse_roster(resp.json())


def _parse_roster(payload: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        roster_block = payload["fantasy_content"]["team"][1]["roster"]
        players = roster_block["0"]["players"]
    except (KeyError, IndexError, TypeError):
        return []
    return _parse_players_block(players)


async def fetch_league_free_agents(
    access_token: str, league_key: str, page_size: int = 25
) -> list[dict[str, Any]]:
    """Paginated FA fetch. Returns all players with status=A in the league."""
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    out: list[dict[str, Any]] = []
    start = 0
    while True:
        url = (
            f"{FANTASY_API_BASE}/league/{league_key}/players;"
            f"status=A;sort=AR;count={page_size};start={start};"
            f"out=percent_owned,percent_started,ranks,draft_analysis?format=json"
        )
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        try:
            players = resp.json()["fantasy_content"]["league"][1]["players"]
        except (KeyError, IndexError, TypeError):
            break
        page = _parse_players_block(players)
        if not page:
            break
        out.extend(page)
        if len(page) < page_size:
            break
        start += page_size
        if start > 2000:  # safety: NBA has ~600 players, never more than 2000 FAs
            break
    return out


def _parse_players_block(players: dict[str, Any]) -> list[dict[str, Any]]:
    """Players blocks always look like {"count": N, "0": {"player": [...]}, "1": ...}."""
    out: list[dict[str, Any]] = []
    if not isinstance(players, dict):
        return out
    count = int(players.get("count", 0))
    for i in range(count):
        wrapper = players.get(str(i), {}).get("player")
        if not wrapper:
            continue
        parsed = _parse_one_player(wrapper)
        if parsed:
            out.append(parsed)
    return out


def _parse_one_player(player_entry: list[Any]) -> dict[str, Any] | None:
    """A player entry is [meta_list, {selected_position?}, {percent_owned?}, ...].

    With ;out=percent_owned,percent_started,ranks,draft_analysis the entry
    additionally has dicts for each of those sub-resources.
    """
    meta: dict[str, Any] = {}
    selected_position: str | None = None
    percent_owned: float | None = None
    percent_owned_delta: float | None = None
    percent_started: float | None = None
    waiver_status: str | None = None
    draft_avg_pick: float | None = None
    draft_avg_round: float | None = None
    draft_avg_cost: float | None = None
    draft_percent_drafted: float | None = None

    first = player_entry[0] if player_entry else None
    if isinstance(first, list):
        for sub in first:
            if not isinstance(sub, dict):
                continue
            if "name" in sub and isinstance(sub["name"], dict):
                meta["full_name"] = sub["name"].get("full")
                meta["first_name"] = sub["name"].get("first")
                meta["last_name"] = sub["name"].get("last")
            elif "eligible_positions" in sub:
                positions = sub["eligible_positions"]
                if isinstance(positions, list):
                    meta["eligible_positions"] = [
                        p.get("position") for p in positions if isinstance(p, dict) and "position" in p
                    ]
            else:
                for k, v in sub.items():
                    if not isinstance(v, (list, dict)):
                        meta[k] = v

    for item in player_entry[1:] if len(player_entry) > 1 else []:
        if not isinstance(item, dict):
            continue
        if "selected_position" in item:
            sp = item["selected_position"]
            if isinstance(sp, list):
                for s in sp:
                    if isinstance(s, dict) and "position" in s:
                        selected_position = s["position"]
                        break
        if "ownership" in item:
            own = item["ownership"]
            if isinstance(own, dict):
                waiver_status = own.get("ownership_type")
        if "percent_owned" in item:
            po = _flatten_yahoo_block(item["percent_owned"])
            percent_owned = _safe_float(po.get("value"))
            percent_owned_delta = _safe_float(po.get("delta"))
        if "percent_started" in item:
            ps = _flatten_yahoo_block(item["percent_started"])
            percent_started = _safe_float(ps.get("value"))
        if "draft_analysis" in item:
            da = _flatten_yahoo_block(item["draft_analysis"])
            draft_avg_pick = _safe_float(da.get("average_pick"))
            draft_avg_round = _safe_float(da.get("average_round"))
            draft_avg_cost = _safe_float(da.get("average_cost"))
            draft_percent_drafted = _safe_float(da.get("percent_drafted"))

    if not meta.get("player_key"):
        return None

    eligible_positions = meta.get("eligible_positions") or []
    primary_position = meta.get("display_position") or meta.get("primary_position")
    if not primary_position and eligible_positions:
        primary_position = eligible_positions[0]

    return {
        # Player identity
        "yahoo_player_key": meta["player_key"],
        "yahoo_player_id": _safe_int(meta.get("player_id")) or 0,
        "full_name": meta.get("full_name") or "Unknown",
        "first_name": meta.get("first_name"),
        "last_name": meta.get("last_name"),
        "eligible_positions": eligible_positions,
        "primary_position": primary_position,
        "nba_team_abbr": meta.get("editorial_team_abbr"),
        "status": meta.get("status") or None,
        "image_url": meta.get("image_url"),
        "uniform_number": meta.get("uniform_number"),
        # Yahoo-global ownership data (set when ;out=percent_owned was used)
        "percent_owned": percent_owned,
        "percent_owned_delta": percent_owned_delta,
        "percent_started": percent_started,
        # Draft analysis (set when ;out=draft_analysis was used)
        "draft_avg_pick": draft_avg_pick,
        "draft_avg_round": draft_avg_round,
        "draft_avg_cost": draft_avg_cost,
        "draft_percent_drafted": draft_percent_drafted,
        # Roster-context fields (only set on roster fetches):
        "selected_position": selected_position,
        # FA-context fields (only set on FA fetches):
        "waiver_status": waiver_status,
    }


def _flatten_yahoo_block(block: Any) -> dict[str, Any]:
    """Yahoo represents many sub-resources as either a list of single-key dicts
    or a flat dict. Normalize to a flat dict.
    """
    if isinstance(block, dict):
        return block
    if isinstance(block, list):
        merged: dict[str, Any] = {}
        for item in block:
            if isinstance(item, dict):
                merged.update(item)
        return merged
    return {}


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
