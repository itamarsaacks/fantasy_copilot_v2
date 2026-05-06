# Replay-mode fixtures

This folder holds recorded responses from Yahoo + NBA + news sources, captured during the regular season. In `APP_MODE=replay`, the connector layer reads from here instead of hitting live APIs. The `AS_OF_DATE` environment variable controls the simulated "today."

Fixtures are populated in a later phase (Phase 0.5) by running `scripts/capture_fixtures.py` against live APIs.

## Layout

```
fixtures/
├── yahoo/          recorded Yahoo Fantasy API responses
├── nba/            recorded NBA stats + schedule
└── news/           recorded news items
```

Filenames encode the date + endpoint, e.g. `yahoo/2026-03-15/league_466.l.162434_settings.json`.

## Why fixtures live in git

Reproducible tests. Every developer + CI run sees the same data. Size is small (JSON, gzipped).
