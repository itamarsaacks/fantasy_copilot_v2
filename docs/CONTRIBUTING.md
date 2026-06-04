# Contributing — branch hygiene + the daily ritual

> Solo project for now. This doc exists so future-me (and anyone helping)
> behaves the same way every session. It's the workflow contract.

## Branch model

`main` is shippable at all times. CI gates every push.

For feature work that touches >1 file or spans >1 day, branch off:

```
git switch -c feature/<area>-<short-name>
# e.g. feature/espn-connector, feature/category-league-ux, feature/billing
```

Branch names are `feature/<area>-<short-name>` (kebab). One feature
per branch. Merge to `main` via fast-forward once CI is green and
the feature flag (if any) is wired.

Single-commit fixes that affect only `main` are fine to commit
directly — no need for a branch.

Don't push directly to `main` if you're working on something behind a
feature flag without a flag wired yet — keep it local until the flag
exists.

## Feature flags (load-bearing for parallel work)

Anything in-flight ships behind a flag so incomplete work can land on
`main` without exposing users.

```python
# backend/app/features.py — the enum is the source of truth
class Feature(str, Enum):
    ESPN_CONNECTOR = "espn_connector"
    SLEEPER_CONNECTOR = "sleeper_connector"
    CATEGORY_LEAGUE_UX = "category_league_ux"
    BILLING = "billing"
```

To add a new flag:
1. Add a member to `Feature`
2. Add `feature_<lower>: bool = False` to `Settings` in `app/config.py`
3. `tests/test_features.py` enforces both sides exist — your PR
   will fail CI if you forget one

To gate code on a flag:
```python
from app.features import Feature, is_enabled

if is_enabled(Feature.ESPN_CONNECTOR):
    app.include_router(espn_routes.router)
```

Enable locally via `backend/.env`:
```
FEATURE_ESPN_CONNECTOR=true
```

The `/health` endpoint reports `features: [...]` so you can confirm
what's on in any environment.

## Daily ritual

At the start of every session:

1. `git status -sb` — am I on the right branch? any stragglers?
2. `bash scripts/smoke.sh` — does the app currently boot + chat work?
3. Read the top entry of `SESSION_NOTES.md` (left by `/wrap-session`)

At the end of every session:

1. Run the full local sweep (see "Local gates" below) — must be green
2. `/wrap-session` (updates `SESSION_NOTES.md` + `PROJECT_STATE.md`)
3. Commit on the feature branch; push to remote; verify CI green
4. Don't merge to main unless you ran the smoke against the merged code

## Local gates (must pass before push)

```bash
# backend
cd backend && source .venv/bin/activate
ruff check app tests          # lint
pytest -q -m "not db"          # pure-unit
pytest -q -m "db"              # DB-integration (needs docker postgres)

# frontend
cd frontend
npx tsc --noEmit               # typecheck
npx eslint --quiet             # lint (errors only)

# guards
bash scripts/check_forbidden_sources.sh
```

CI runs the same gates on every push. If a gate goes red on `main`,
**fix-forward is the policy** — never revert. A revert hides intent
from git history; a forward-fix with a one-line commit makes the
intent obvious.

## Commit style

- Imperative present ("add ESPN connector", not "added" or "adds")
- First line ≤72 chars
- Blank line, then the explanation (why > what)
- Co-author trailer for AI assistance — see existing commits

For commits the user explicitly asks for, that's it. Don't proactively
amend or rewrite history — create new commits instead.

## Branch hygiene

- One feature per branch
- Rebase onto `main` before pushing for review (keeps history linear)
- Delete branches after merge: `git branch -d feature/foo`
- Never `--force-push` to `main`; force-pushing a feature branch is
  fine as long as nobody else has it checked out

## What goes in `docs/plans/`

Per-tab / per-feature plans (one file per logical chunk of work).
Each plan covers: scope, what exists today, what's missing,
ordered steps, acceptance criteria. See `docs/plans/league-formats.md`
as the template.

## What goes in `SESSION_NOTES.md`

The 5 most recent session entries. Each entry says: what was done,
what was verified, what's in flight, what to pick up next. Older
entries get pruned (git log is the durable record).
