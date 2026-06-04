"""Feature flags — gate incomplete work behind env-driven booleans.

Flags let us merge half-done features to `main` (so the rest of the
team / future-me sees the work-in-progress) without exposing them to
users. Each flag is OFF by default; flip via `FEATURE_<NAME>=true` in
backend/.env or the deployment env.

Usage:

    from app.features import Feature, is_enabled

    if is_enabled(Feature.ESPN_CONNECTOR):
        app.include_router(espn_routes.router)

The enum is the source of truth: adding a flag means adding a member
here AND a field to `app.config.Settings.feature_<lowercase>`. The
test suite enforces both sides exist via `test_features.py`.

Why an enum instead of magic strings: typo'd flag names silently
return False (the env var doesn't exist, the default is off). The enum
makes typos fail at import.
"""

from __future__ import annotations

from enum import Enum

from app.config import get_settings


class Feature(str, Enum):
    """Known feature flags.

    String values match the suffix of the corresponding Settings field:
        Feature.ESPN_CONNECTOR -> settings.feature_espn_connector
    """

    ESPN_CONNECTOR = "espn_connector"
    SLEEPER_CONNECTOR = "sleeper_connector"
    CATEGORY_LEAGUE_UX = "category_league_ux"
    BILLING = "billing"


def is_enabled(feature: Feature) -> bool:
    """Return True iff the feature flag is on for this process.

    Reads from the cached settings — flipping a flag requires a process
    restart, which is what we want (no in-flight requests with mixed
    flag values).
    """
    settings = get_settings()
    return bool(getattr(settings, f"feature_{feature.value}", False))


def enabled_features() -> set[Feature]:
    """All currently-enabled flags. Useful for `/health` debugging."""
    return {f for f in Feature if is_enabled(f)}
