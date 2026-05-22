"""Single chokepoint for resolving "today's calendar date".

Every place in the app that needs to know "what day is it for the user"
calls `resolve_today()`. NEVER `date.today()` or `datetime.now(...).date()`
directly — those bypass replay mode and break off-season testing.

Replay mode (configured via APP_MODE=replay + AS_OF_DATE=YYYY-MM-DD in
backend/.env) is how we test the app outside the NBA regular season.
Without this chokepoint, every page calling `.today()` would see the
real-world today (off-season, no games, empty data) instead of the
seeded replay date.

What this DOES respect:
- Calendar-day questions: "what's today's schedule," "give me yesterday's
  game logs," "how many days until end of week," etc.

What this DOES NOT touch:
- Wall-clock timestamps used for audit (created_at, updated_at, JWT exp,
  OAuth token expiry, APScheduler internals). Those use real time even
  in replay mode. Keep `datetime.now(timezone.utc)` for those — do NOT
  route through this module.

CI guard (`scripts/check_forbidden_sources.sh`) fails the build if
`date.today()`, `datetime.today()`, or `datetime.now(...).date()` is added
anywhere in `backend/app/` outside this file.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.config import get_settings


def resolve_today() -> date:
    """Return today's calendar date, respecting APP_MODE=replay.

    In live mode: today's date in UTC (we don't expose a timezone arg yet —
    the app treats UTC and local-NY as approximately interchangeable for
    fantasy purposes; the NBA day boundary is ~3am ET ≈ 8am UTC, and we
    don't fence-post-precise around it).

    In replay mode: returns the AS_OF_DATE setting. If APP_MODE=replay
    but AS_OF_DATE is unset, raises — that's a misconfiguration, not a
    silent fallback to real today (which would defeat the purpose of
    replay mode entirely).
    """
    settings = get_settings()
    if settings.app_mode == "replay":
        if settings.as_of_date is None:
            raise RuntimeError(
                "APP_MODE=replay requires AS_OF_DATE to be set in backend/.env. "
                "Pick a date during the NBA regular season, e.g. AS_OF_DATE=2026-03-15."
            )
        return settings.as_of_date
    return datetime.now(timezone.utc).date()


def is_replay_mode() -> bool:
    """Convenience predicate; cheaper than importing settings everywhere."""
    return get_settings().app_mode == "replay"
