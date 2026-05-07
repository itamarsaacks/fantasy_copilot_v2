#!/usr/bin/env bash
# End-to-end smoke test. MUST PASS before any commit.
#
# Catches integration-level breakage that isolation tests miss:
#  - did the backend boot?
#  - is the DB reachable?
#  - are all expected routes registered?
#  - does the chat agent still call a tool and produce a real answer?
#
# Run from the repo root: bash scripts/smoke.sh
# Exits non-zero on first failure. Prints the actual failure detail.

set -euo pipefail

cd "$(dirname "$0")/.."

API="${API:-http://localhost:8000}"
DB_CONTAINER="${DB_CONTAINER:-fantasy_copilot_v2_db}"
DB_USER="${DB_USER:-fantasy}"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
blue()  { printf '\033[34m%s\033[0m\n' "$*"; }

# 1. Backend health -----------------------------------------------------------
blue "[1/5] backend health"
if ! curl -sf "$API/health" >/tmp/smoke_health.json; then
  red "FAIL: $API/health did not respond. Is uvicorn running?"
  exit 1
fi
if ! grep -q '"status":"ok"' /tmp/smoke_health.json; then
  red "FAIL: /health returned unexpected body:"
  cat /tmp/smoke_health.json
  exit 1
fi
green "  ok ($(cat /tmp/smoke_health.json))"

# 2. Postgres reachable -------------------------------------------------------
blue "[2/5] postgres reachable"
if ! docker exec "$DB_CONTAINER" pg_isready -U "$DB_USER" >/dev/null 2>&1; then
  red "FAIL: postgres container '$DB_CONTAINER' not accepting connections."
  red "      Try: docker compose up -d"
  exit 1
fi
green "  ok"

# 3. Critical routes registered ----------------------------------------------
blue "[3/5] critical routes registered"
curl -sf "$API/openapi.json" >/tmp/smoke_openapi.json || {
  red "FAIL: could not fetch /openapi.json"
  exit 1
}
python3 - <<'PY' >/tmp/smoke_routes.out
import json, sys
paths = json.load(open("/tmp/smoke_openapi.json"))["paths"]
required = [
    "/health",
    "/auth/yahoo/login",
    "/auth/yahoo/callback",
    "/auth/me",
    "/auth/logout",
    "/api/chat",
    "/api/conversations",
    "/admin/sync-now",
    "/admin/sync-stats",
    "/admin/compute-projections",
]
missing = [p for p in required if p not in paths]
if missing:
    print("FAIL: missing routes:", missing)
    sys.exit(1)
print(f"  ok ({len(paths)} total routes, {len(required)} critical present)")
PY
green "$(cat /tmp/smoke_routes.out)"

# 4. JWT minting works (proves security module loads + .env reads JWT_SECRET) -
blue "[4/5] JWT minting"
JWT=$(
  cd backend && source .venv/bin/activate && \
  python3 -c "from app.security import create_access_token; print(create_access_token(1))" \
    2>/tmp/smoke_jwt.err
) || {
  red "FAIL: could not mint JWT — check backend env and imports"
  cat /tmp/smoke_jwt.err
  exit 1
}
if [ -z "$JWT" ]; then
  red "FAIL: JWT was empty"
  exit 1
fi
green "  ok"

# 5. Chat agent end-to-end -- real DB, real tool, real Claude call ------------
blue "[5/5] chat agent end-to-end (may take 30-90s)"
HTTP_CODE=$(
  curl -s -o /tmp/smoke_chat.json -w "%{http_code}" \
    -X POST "$API/api/chat" \
    -H "Content-Type: application/json" \
    -H "Cookie: fc_session=$JWT" \
    -d '{"message":"Tell me my team name in one sentence.","league_id":1}' \
    --max-time 120
)
if [ "$HTTP_CODE" != "200" ]; then
  red "FAIL: /chat returned HTTP $HTTP_CODE. Body was:"
  cat /tmp/smoke_chat.json 2>/dev/null || true
  exit 1
fi
python3 - <<'PY' >/tmp/smoke_chat.out
import json, sys
d = json.load(open("/tmp/smoke_chat.json"))
reply = d.get("reply", "") or ""
tool_calls = d.get("tool_calls", 0)
if not reply.strip():
    print("FAIL: agent reply was empty:", d)
    sys.exit(1)
if tool_calls < 1:
    print(f"FAIL: agent did not call any tool (tool_calls={tool_calls}). Reply: {reply[:200]}")
    sys.exit(1)
print(f"  ok (tool_calls={tool_calls})")
print(f"  reply: {reply[:140]}{'...' if len(reply) > 140 else ''}")
PY
green "$(cat /tmp/smoke_chat.out)"

echo
green "✓ smoke test passed"
