# Test fixtures — recorded API responses

This directory holds anonymized, version-controlled API response samples
used by parser tests and the future ESPN/Sleeper connector contract
tests. They make connector development possible without authenticated
network access.

## Layout

```
fixtures/
├── yahoo/          Yahoo Fantasy API response JSON
│   ├── league_settings/    league rules, scoring, roster slots
│   ├── teams/              team list + standings
│   ├── rosters/            per-team roster snapshots
│   ├── transactions/       draft + add/drop/trade events
│   └── free_agents/        FA pool listings
├── espn/           ESPN Fantasy API response JSON (added with connector)
└── sleeper/        Sleeper API response JSON (added with connector)
```

Each platform mirrors the same response categories so the contract
tests can be parameterized across all three.

## Why fixtures live in git

- Tests pass offline, in CI, and against a frozen response shape
- Re-runs are deterministic — no rate limits, no expired tokens
- A platform's response-shape drift gets caught the moment we update
  the fixture to match

## Authoring rules

1. **Anonymize before committing.** Replace real player_keys, league_ids,
   manager names, and user GUIDs with synthetic values. Real player
   names ARE allowed (they're public information and improve test
   readability).
2. **One scenario per file.** Don't bundle multiple test cases into
   one fixture — keeps test failures pointing at one concrete shape.
3. **Pretty-print JSON** (`json.dump(..., indent=2, sort_keys=True)`)
   so diffs in PRs are reviewable.
4. **Name describes the scenario**, not the date.
   `roster_with_il_player.json` beats `2026-03-15_team_1.json`.

## How to capture new fixtures

For Yahoo (requires an active OAuth session):

```bash
cd backend && source .venv/bin/activate
python -m scripts.capture_fixture --kind league_settings --league-id 1
# writes backend/tests/fixtures/yahoo/league_settings/<scenario>.json
```

The capture script (TODO — to be added when the first real-shape
fixture is needed) anonymizes IDs and pretty-prints output.

For ESPN/Sleeper: see the per-connector docs once those land.

## How tests use fixtures

```python
from tests.fixtures import load_fixture

def test_parse_league_settings():
    payload = load_fixture("yahoo", "league_settings", "points_league.json")
    parsed = _parse_one_league(payload)
    assert parsed["scoring_type"] == "point"
```

The `load_fixture` helper (in `tests/fixtures/__init__.py`) does the
path resolution + JSON load with a clear error message if the file
is missing.
