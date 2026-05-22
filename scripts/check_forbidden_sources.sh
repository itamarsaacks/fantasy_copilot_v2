#!/usr/bin/env bash
# CI guard for the master plan §2.A allow-list + §2.4 resolve_today() chokepoint.
#
# Fails the build if any of these patterns appear in backend/app/ outside of
# the sanctioned places:
#
# 1. Calendar-today calls: `date.today()` / `datetime.today()` /
#    `datetime.now(...).date()` — must route through services/clock.py
#    (resolve_today). Wall-clock `datetime.now(timezone.utc)` without
#    `.date()` is allowed — it's for audit timestamps.
#
# 2. Forbidden hostnames at runtime: stats.nba.com / cdn.nba.com (CDN
#    headshot endpoint is allowed in one-shot scripts/, not at runtime).
#    basketball-reference.com scraping anywhere.
#
# 3. Yahoo at request time: yahoo connector calls inside api/routes/ are
#    forbidden — Yahoo lives in jobs/ only.
#
# Run via pre-commit, CI, or `bash scripts/check_forbidden_sources.sh`.
# Exit 0 = clean. Exit 1 = violations.

set -u
cd "$(dirname "$0")/.."

EXIT=0

# ---------------------------------------------------------------------------
# 1. resolve_today() chokepoint
# ---------------------------------------------------------------------------
# Allowed: backend/app/services/clock.py (the implementation itself)
# Allowed: backend/app/evals/ (eval harness uses real wall-clock)
# Allowed: backend/app/security.py, auth.py — JWT exp, OAuth exp
#         (these use datetime.now(timezone.utc), no .date() — fine)
# Forbidden everywhere else: date.today(), datetime.today(),
#                            datetime.now(...).date()

violations=$(grep -rn -E "(date\.today\(\)|datetime\.today\(\)|datetime\.now\([^)]*\)\.date\(\))" \
    backend/app/ \
    --include="*.py" \
    --exclude-dir=__pycache__ \
    --exclude-dir=evals \
    | grep -v "backend/app/services/clock.py" \
    || true)

if [ -n "$violations" ]; then
    echo "❌ Calendar-today violations — use app.services.clock.resolve_today() instead:"
    echo "$violations"
    echo
    EXIT=1
fi

# ---------------------------------------------------------------------------
# 2. Forbidden hostnames at runtime
# ---------------------------------------------------------------------------
# stats.nba.com is forbidden everywhere — too aggressive at throttling.
# cdn.nba.com is allowed ONLY in scripts/ (one-shot headshot download).
# basketball-reference.com forbidden everywhere.

hostname_violations=$(grep -rn -E "(stats\.nba\.com|basketball-reference\.com)" \
    backend/app/ \
    --include="*.py" \
    --exclude-dir=__pycache__ \
    || true)

if [ -n "$hostname_violations" ]; then
    echo "❌ Forbidden hostname references at runtime (see master plan §2.A):"
    echo "$hostname_violations"
    echo
    EXIT=1
fi

# cdn.nba.com — runtime forbidden, scripts/ allowed
cdn_violations=$(grep -rn "cdn\.nba\.com" backend/app/ \
    --include="*.py" \
    --exclude-dir=__pycache__ \
    || true)

if [ -n "$cdn_violations" ]; then
    echo "❌ cdn.nba.com referenced at runtime (one-shot scripts/ only — see §2.A):"
    echo "$cdn_violations"
    echo
    EXIT=1
fi

# ---------------------------------------------------------------------------
# 3. Yahoo at request time
# ---------------------------------------------------------------------------
# `app.connectors.yahoo` imports in api/routes/ are forbidden.
# Yahoo lives in jobs/ and services/ only (background ingestion).
#
# Known exception during transition: players.py and team.py still call
# Yahoo at request time for past-date game logs. They are listed in §2.3
# of the master plan as "remove live Yahoo from request path" and will
# be fixed in Step 5. Until then this check WARNS but doesn't fail.

yahoo_in_routes=$(grep -rn "from app.connectors import yahoo\|import.*yahoo_client\|fetch_and_cache_logs" \
    backend/app/api/routes/ \
    --include="*.py" \
    --exclude-dir=__pycache__ \
    || true)

if [ -n "$yahoo_in_routes" ]; then
    echo "⚠️  Yahoo references in api/routes/ (warns now, errors after Step 5):"
    echo "$yahoo_in_routes"
    echo
fi

# ---------------------------------------------------------------------------

if [ "$EXIT" -eq 0 ]; then
    echo "✅ Forbidden-sources check clean."
fi

exit "$EXIT"
