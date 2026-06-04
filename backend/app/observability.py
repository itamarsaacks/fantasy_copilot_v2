"""Error tracking integration point.

Wired throughout the lifespan + middleware but NO-OP when `SENTRY_DSN`
is empty. This lets us:

  - Ship the integration point now (so it can't be forgotten at launch)
  - Skip the sentry-sdk dependency until we actually need it
  - Verify the wire-up never crashes when DSN is unset (tests, CI, dev)

When we're ready to enable in production:

  1. `pip install sentry-sdk[fastapi]` and add to backend/pyproject.toml
  2. Set SENTRY_DSN in the production env
  3. Uncomment the `import sentry_sdk` block below
  4. Smoke-test: `raise Exception("test")` from a debug endpoint and
     verify the event lands in Sentry

The frontend has its own Sentry integration (`@sentry/nextjs`) — see
frontend/sentry.client.config.ts (TODO: add at the same time).
"""

from __future__ import annotations

import logging

from app.config import get_settings

log = logging.getLogger(__name__)


def init_observability() -> None:
    """Initialize Sentry (or any future error tracker).

    Called from lifespan startup in main.py. Safe to call when DSN is
    unset — just logs a one-line debug message and returns.
    """
    settings = get_settings()
    if not settings.sentry_dsn:
        log.info("observability: no SENTRY_DSN configured, skipping init")
        return

    # When we go to production, uncomment + `pip install sentry-sdk[fastapi]`:
    #
    # import sentry_sdk
    # from sentry_sdk.integrations.asyncpg import AsyncPGIntegration
    # from sentry_sdk.integrations.fastapi import FastApiIntegration
    # from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    #
    # sentry_sdk.init(
    #     dsn=settings.sentry_dsn,
    #     environment=settings.sentry_environment,
    #     traces_sample_rate=settings.sentry_traces_sample_rate,
    #     integrations=[
    #         FastApiIntegration(),
    #         AsyncPGIntegration(),
    #         SqlalchemyIntegration(),
    #     ],
    #     # Don't capture stack-locals — many contain Yahoo OAuth tokens,
    #     # JWT secrets, or admin secrets. Default is True; we override.
    #     include_local_variables=False,
    #     # Strip request bodies. Same reasoning as above + chat messages
    #     # may contain PII (player names + manager info).
    #     send_default_pii=False,
    # )
    log.info(
        "observability: SENTRY_DSN set but SDK not installed yet. "
        "Install sentry-sdk[fastapi] and uncomment init in observability.py."
    )


def capture_exception(exc: BaseException) -> None:
    """Report an exception. NO-OP when DSN unset / SDK not installed.

    Use at integration boundaries where we catch-and-continue (Yahoo
    rate-limit 429, ESPN cookie expiry, etc.) but want operators to
    see the trail.
    """
    settings = get_settings()
    if not settings.sentry_dsn:
        return
    # Once sentry_sdk is installed:
    # import sentry_sdk
    # sentry_sdk.capture_exception(exc)
    log.warning("would report to Sentry (SDK not installed): %s", exc)
