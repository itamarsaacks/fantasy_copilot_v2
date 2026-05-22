"""Download ESPN player headshots to frontend/public/headshots/ as WebP.

Per master plan §2.1: zero runtime third-party dependency for headshots.
Reads staged URLs from `backfill_cursor` (job_name='backfill_espn_player_ids',
scope='staged_headshots') — populated by backfill_espn_player_ids.py — and
writes `<slug>.webp` files to frontend/public/headshots/, then updates
`players.headshot_path` to the slug.

Slug = `<first-last>-<espn_id>.webp` (e.g. `lebron-james-1966.webp`) —
includes ESPN ID so two players with the same name don't collide.

Two sizes are written: 192px and 384px (suffixed `@2x.webp` for retina).

Usage:
    python -m scripts.download_headshots
    python -m scripts.download_headshots --only-missing   # default, skip files that already exist
    python -m scripts.download_headshots --player-id 12345  # one player

Requires Pillow:  pip install Pillow
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import re
import unicodedata
from pathlib import Path

import httpx
from sqlalchemy import select

from app.db.engine import SessionLocal
from app.db.models import BackfillCursor, Player

logger = logging.getLogger("download_headshots")

# Defaults — adjustable via CLI later.
HEADSHOTS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "headshots"
)
USER_AGENT = "fantasy-copilot/1.0"
SLEEP_BETWEEN = 0.2  # seconds — be polite, ESPN CDN is fast but not unlimited
SIZE_SMALL = 192
SIZE_LARGE = 384
JOB_NAME = "backfill_espn_player_ids"
SCOPE = "staged_headshots"


def slugify(name: str) -> str:
    """LeBron James -> lebron-james; Luka Dončić -> luka-doncic."""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"\s+", "-", name).strip("-")
    return name


def _convert_to_webp(content: bytes, size: int) -> bytes:
    """Resize + WebP encode. Imported lazily so import-time is cheap."""
    try:
        from PIL import Image  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "Pillow is required: `pip install Pillow`"
        ) from e

    src = Image.open(io.BytesIO(content)).convert("RGBA")
    src.thumbnail((size, size), Image.LANCZOS)
    # Pad to square so the frontend can use fixed-size CSS without distortion.
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - src.width) // 2
    y = (size - src.height) // 2
    out.paste(src, (x, y), src)
    buf = io.BytesIO()
    out.save(buf, format="WEBP", quality=85, method=4)
    return buf.getvalue()


async def download_one(
    client: httpx.AsyncClient,
    player_id: int,
    full_name: str,
    espn_id: int,
    url: str,
    only_missing: bool,
) -> tuple[bool, str | None]:
    """Returns (success, headshot_path) — headshot_path is the slug if success."""
    slug = f"{slugify(full_name)}-{espn_id}"
    small_path = HEADSHOTS_DIR / f"{slug}.webp"
    large_path = HEADSHOTS_DIR / f"{slug}@2x.webp"

    if only_missing and small_path.exists() and large_path.exists():
        return True, f"{slug}.webp"

    try:
        resp = await client.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=20.0
        )
        if resp.status_code == 404:
            logger.warning("404 for %s (%s)", full_name, url)
            return False, None
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("fetch failed for %s: %s", full_name, e)
        return False, None

    HEADSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        small = _convert_to_webp(resp.content, SIZE_SMALL)
        large = _convert_to_webp(resp.content, SIZE_LARGE)
    except Exception as e:
        logger.warning("conversion failed for %s: %s", full_name, e)
        return False, None

    small_path.write_bytes(small)
    large_path.write_bytes(large)
    return True, f"{slug}.webp"


async def main(only_missing: bool = True, single_player_id: int | None = None) -> None:
    HEADSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Load staged headshot URLs from backfill_cursor
    async with SessionLocal() as db:
        cursor = (
            await db.execute(
                select(BackfillCursor).where(
                    BackfillCursor.job_name == JOB_NAME,
                    BackfillCursor.scope == SCOPE,
                )
            )
        ).scalar_one_or_none()

        if cursor is None:
            logger.error(
                "no staged headshots — run backfill_espn_player_ids.py first"
            )
            return

        staged: dict[str, str] = cursor.state.get("player_id_to_url", {})
        if not staged:
            logger.info("no staged URLs in cursor state — nothing to do")
            return

        # 2) Resolve player_id -> Player (need full_name + espn_player_id)
        player_ids = [int(k) for k in staged.keys()]
        if single_player_id is not None:
            player_ids = [single_player_id]
        players = (
            await db.execute(select(Player).where(Player.id.in_(player_ids)))
        ).scalars().all()
        players_by_id = {p.id: p for p in players}

        successes = 0
        failures = 0
        async with httpx.AsyncClient() as client:
            for pid_str, url in staged.items():
                pid = int(pid_str)
                if single_player_id is not None and pid != single_player_id:
                    continue
                player = players_by_id.get(pid)
                if player is None or player.espn_player_id is None:
                    failures += 1
                    continue
                ok, slug_path = await download_one(
                    client,
                    player.id,
                    player.full_name,
                    player.espn_player_id,
                    url,
                    only_missing,
                )
                if ok and slug_path:
                    player.headshot_path = slug_path
                    successes += 1
                else:
                    failures += 1
                await asyncio.sleep(SLEEP_BETWEEN)

        await db.commit()

    print("=" * 60)
    print(f"downloaded: {successes}")
    print(f"failed:     {failures}")
    print(f"output dir: {HEADSHOTS_DIR}")


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="re-download even if file already exists",
    )
    parser.add_argument(
        "--player-id",
        type=int,
        default=None,
        help="only process one player (debug)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="DEBUG logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    asyncio.run(main(only_missing=not args.all, single_player_id=args.player_id))


if __name__ == "__main__":
    cli()
