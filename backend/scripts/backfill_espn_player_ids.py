"""Backfill `players.espn_player_id` + `headshot_path` from ESPN's roster API.

Per master plan §2.1: we map Yahoo → ESPN by (normalized_name, nba_team_abbr).
ESPN's `/sports/basketball/nba/teams/{id}/roster` endpoint is the same
family we already use for schedule (tolerant, public, no auth) — we never
touch stats.nba.com (§2.A).

Usage:
    python -m scripts.backfill_espn_player_ids
    python -m scripts.backfill_espn_player_ids --dry-run
    python -m scripts.backfill_espn_player_ids --only-missing  # default

Idempotent: re-running is safe. Unmatched players are logged but don't
abort the run; the nightly reconcile in `sync_yahoo` retries them.

Run characteristics:
- ~30 HTTP requests (one per NBA team), 1s sleep between, User-Agent set
- ~10 minutes for a fresh backfill, near-instant on re-run with --only-missing
- Writes to `players.espn_player_id`, `players.espn_player_id_confidence`,
  and stages `headshot.href` in a temp dict for `download_headshots.py`
  to consume next (kept in `state` JSONB of `backfill_cursor`).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import unicodedata
from collections import defaultdict
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.engine import SessionLocal
from app.db.models import BackfillCursor, Player

logger = logging.getLogger("backfill_espn_player_ids")

ESPN_TEAMS_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
)
ESPN_ROSTER_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
)
USER_AGENT = "fantasy-copilot/1.0"
SLEEP_BETWEEN_TEAMS = 1.0  # seconds — be polite to ESPN
JOB_NAME = "backfill_espn_player_ids"


# Yahoo nba_team_abbr is mostly Yahoo's; ESPN uses slightly different forms
# for some teams. Normalize Yahoo -> ESPN's `abbreviation` field.
YAHOO_TO_ESPN_TEAM_ABBR = {
    "NOP": "NO",
    "SAS": "SA",
    "GSW": "GS",
    "NYK": "NY",
    "WAS": "WSH",
}


def normalize_name(name: str) -> str:
    """Strip diacritics, lowercase, remove suffix/punctuation, collapse whitespace."""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower()
    # Strip common suffixes: Jr., Sr., III, II, IV
    name = re.sub(r"\b(jr|sr|iii|ii|iv)\b\.?", "", name)
    # Strip punctuation
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def yahoo_to_espn_abbr(abbr: str | None) -> str | None:
    if abbr is None:
        return None
    return YAHOO_TO_ESPN_TEAM_ABBR.get(abbr, abbr)


async def fetch_espn_teams(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Return list of dicts: {team_id: int, abbreviation: str, name: str}."""
    resp = await client.get(
        ESPN_TEAMS_URL, headers={"User-Agent": USER_AGENT}, timeout=30.0
    )
    resp.raise_for_status()
    data = resp.json()
    teams = []
    for sport in data.get("sports", []):
        for league in sport.get("leagues", []):
            for entry in league.get("teams", []):
                t = entry.get("team", {})
                teams.append(
                    {
                        "team_id": int(t["id"]),
                        "abbreviation": t.get("abbreviation"),
                        "name": t.get("displayName"),
                    }
                )
    return teams


async def fetch_espn_roster(
    client: httpx.AsyncClient, team_id: int
) -> list[dict[str, Any]]:
    """Return list of athlete dicts from ESPN's roster endpoint."""
    url = ESPN_ROSTER_URL.format(team_id=team_id)
    resp = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    athletes = []
    for athlete in data.get("athletes", []):
        if isinstance(athlete, dict) and "items" in athlete:
            # Some responses nest athletes inside position buckets
            for a in athlete["items"]:
                athletes.append(a)
        elif isinstance(athlete, dict):
            athletes.append(athlete)
    return athletes


async def main(dry_run: bool = False, only_missing: bool = True) -> None:
    """Walk all 30 ESPN rosters and match Yahoo players by (name, team).

    Counts written to stdout. Unmatched names logged at WARNING.
    """
    matched_exact = 0
    matched_fuzzy = 0
    unmatched_yahoo: list[str] = []
    headshots_staged: dict[int, str] = {}  # player_id -> headshot_url

    async with httpx.AsyncClient() as client:
        teams = await fetch_espn_teams(client)
        logger.info("fetched %d ESPN teams", len(teams))

        # Build ESPN-side index keyed by (espn_team_abbr, normalized_name)
        espn_index: dict[tuple[str, str], dict[str, Any]] = {}
        # And a name-only fuzzy index for fallback
        espn_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for team in teams:
            await asyncio.sleep(SLEEP_BETWEEN_TEAMS)
            try:
                athletes = await fetch_espn_roster(client, team["team_id"])
            except httpx.HTTPError as e:
                logger.warning(
                    "team %s roster fetch failed: %s", team["abbreviation"], e
                )
                continue
            logger.info(
                "team %s: %d athletes", team["abbreviation"], len(athletes)
            )
            for athlete in athletes:
                espn_id_raw = athlete.get("id")
                if espn_id_raw is None:
                    continue
                try:
                    espn_id = int(espn_id_raw)
                except (TypeError, ValueError):
                    continue
                full_name = athlete.get("fullName") or athlete.get("displayName")
                if not full_name:
                    continue
                norm = normalize_name(full_name)
                entry = {
                    "espn_id": espn_id,
                    "abbr": team["abbreviation"],
                    "name": full_name,
                    "headshot": (athlete.get("headshot") or {}).get("href"),
                }
                espn_index[(team["abbreviation"], norm)] = entry
                espn_by_name[norm].append(entry)

        # Walk Yahoo players and match
        async with SessionLocal() as db:
            query = select(Player)
            if only_missing:
                query = query.where(Player.espn_player_id.is_(None))
            yahoo_players = (await db.execute(query)).scalars().all()
            logger.info("found %d Yahoo players to match", len(yahoo_players))

            for player in yahoo_players:
                norm = normalize_name(player.full_name)
                espn_abbr = yahoo_to_espn_abbr(player.nba_team_abbr)
                hit: dict[str, Any] | None = None
                confidence: str | None = None

                if espn_abbr and (espn_abbr, norm) in espn_index:
                    hit = espn_index[(espn_abbr, norm)]
                    confidence = "exact"
                    matched_exact += 1
                else:
                    candidates = espn_by_name.get(norm, [])
                    if len(candidates) == 1:
                        hit = candidates[0]
                        confidence = "fuzzy"
                        matched_fuzzy += 1

                if hit is None:
                    unmatched_yahoo.append(
                        f"{player.full_name} ({player.nba_team_abbr or '?'})"
                    )
                    continue

                if not dry_run:
                    player.espn_player_id = hit["espn_id"]
                    player.espn_player_id_confidence = confidence
                    if hit.get("headshot"):
                        headshots_staged[player.id] = hit["headshot"]

            # Stash staged headshots in the backfill cursor's state so
            # download_headshots.py can pick them up.
            if not dry_run and headshots_staged:
                stmt = pg_insert(BackfillCursor).values(
                    job_name=JOB_NAME,
                    scope="staged_headshots",
                    state={"player_id_to_url": headshots_staged},
                )
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_backfill_cursor_job_scope",
                    set_={"state": stmt.excluded.state},
                )
                await db.execute(stmt)
                await db.commit()
            elif not dry_run:
                await db.commit()

    print("=" * 60)
    print(f"matched exact: {matched_exact}")
    print(f"matched fuzzy: {matched_fuzzy}")
    print(f"unmatched:     {len(unmatched_yahoo)}")
    print(f"headshots queued for download: {len(headshots_staged)}")
    if unmatched_yahoo:
        print()
        print("first 20 unmatched (run with --verbose for full list):")
        for name in unmatched_yahoo[:20]:
            print(f"  - {name}")
    if dry_run:
        print()
        print("DRY RUN — nothing written.")


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="don't write to DB, just report match counts",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="re-match every player even if espn_player_id is already set",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="DEBUG logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    asyncio.run(main(dry_run=args.dry_run, only_missing=not args.all))


if __name__ == "__main__":
    cli()
