"""NBA schedule sync from ESPN's public scoreboard endpoint.

Why ESPN? Free, no API key, no rate-limit handshake. The Yahoo Fantasy
API doesn't expose game schedules, and the official NBA stats API
blocks aggressive callers. ESPN's site API is what their own website
uses — it's stable and unauthed.

Cadence: once per day. The data only changes when games complete (for
scores) or when the NBA reschedules a game. A daily sync covers both.

Endpoint: http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.engine import SessionLocal
from app.db.models import NbaSchedule

log = logging.getLogger(__name__)

ESPN_SCOREBOARD = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
# How far ahead to look. Two weeks covers "this week + next week" questions.
LOOKAHEAD_DAYS = 14


# ESPN uses a few different abbreviations than Yahoo. Normalize to Yahoo's
# convention so player.nba_team_abbr joins cleanly to nba_schedule.
# Yahoo uses BKN, GSW, NOP, NYK, OKC, PHX, SAS, UTA, WAS.
# ESPN agrees on most but uses NO instead of NOP, SA instead of SAS,
# UTAH instead of UTA, WSH instead of WAS, GS instead of GSW.
_ESPN_TO_YAHOO_TEAM = {
    "NO": "NOP",
    "SA": "SAS",
    "UTAH": "UTA",
    "WSH": "WAS",
    "GS": "GSW",
}


def _normalize_team(abbr: str) -> str:
    return _ESPN_TO_YAHOO_TEAM.get(abbr.upper(), abbr.upper())


async def fetch_day(client: httpx.AsyncClient, day: date) -> list[dict[str, Any]]:
    """Pull one day of NBA games from ESPN. Returns normalized rows
    ready for upsert into nba_schedule."""
    url = f"{ESPN_SCOREBOARD}?dates={day.strftime('%Y%m%d')}"
    resp = await client.get(url, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    events = data.get("events") or []

    rows: list[dict[str, Any]] = []
    for event in events:
        game_id = str(event.get("id") or "").strip()
        if not game_id:
            continue
        comp = (event.get("competitions") or [{}])[0]
        competitors = comp.get("competitors") or []
        if len(competitors) != 2:
            continue
        home = next(
            (c for c in competitors if c.get("homeAway") == "home"), None
        )
        away = next(
            (c for c in competitors if c.get("homeAway") == "away"), None
        )
        if not home or not away:
            continue
        home_abbr = _normalize_team((home.get("team") or {}).get("abbreviation") or "")
        away_abbr = _normalize_team((away.get("team") or {}).get("abbreviation") or "")
        if not home_abbr or not away_abbr:
            continue

        # ESPN status: STATUS_SCHEDULED / STATUS_IN_PROGRESS / STATUS_FINAL
        status_raw = ((event.get("status") or {}).get("type") or {}).get("name") or ""
        status = {
            "STATUS_SCHEDULED": "scheduled",
            "STATUS_IN_PROGRESS": "live",
            "STATUS_FINAL": "final",
            "STATUS_HALFTIME": "live",
            "STATUS_END_PERIOD": "live",
            "STATUS_POSTPONED": "postponed",
        }.get(status_raw, "scheduled")

        rows.append(
            {
                "game_id": game_id,
                "game_date": day,
                "home_team_abbr": home_abbr,
                "away_team_abbr": away_abbr,
                "status": status,
                "home_score": _safe_int(home.get("score")),
                "away_score": _safe_int(away.get("score")),
            }
        )
    return rows


def _safe_int(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


async def sync_schedule(lookahead_days: int = LOOKAHEAD_DAYS) -> dict[str, int]:
    """Pull `lookahead_days` of NBA games from ESPN and upsert.

    Returns counts for observability. Idempotent — runs anytime, only
    inserts new game_ids and refreshes scheduled/live games.
    """
    today = datetime.now(timezone.utc).date()
    days = [today + timedelta(days=i) for i in range(lookahead_days)]

    fetched = 0
    upserted = 0
    async with httpx.AsyncClient() as client:
        async with SessionLocal() as db:
            for d in days:
                try:
                    rows = await fetch_day(client, d)
                except Exception as exc:  # noqa: BLE001
                    log.warning("ESPN fetch failed for %s: %s", d, exc)
                    continue
                fetched += len(rows)
                for row in rows:
                    stmt = (
                        pg_insert(NbaSchedule)
                        .values(**row)
                        .on_conflict_do_update(
                            index_elements=["game_id"],
                            set_={
                                "status": row["status"],
                                "home_score": row["home_score"],
                                "away_score": row["away_score"],
                                "updated_at": datetime.now(timezone.utc),
                            },
                        )
                    )
                    await db.execute(stmt)
                    upserted += 1
            await db.commit()

    log.info("schedule sync done: fetched=%d upserted=%d", fetched, upserted)
    return {"fetched": fetched, "upserted": upserted}
