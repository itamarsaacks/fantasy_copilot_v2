# Eval snapshots — local, not committed

This directory holds frozen DB snapshots used by `mode: snapshot` eval cases.

> **The actual snapshot data is gitignored.** It contains real user data
> (player names, scores, league info) and doesn't belong in a public repo.
> Each developer captures their own when needed.

## Capturing a snapshot

```bash
python scripts/eval_capture_snapshot.py \
  --snapshot-id offseason_2026_05 \
  --as-of-date 2026-05-11 \
  --note "Off-season baseline"
```

Produces:

```
snapshots/{snapshot_id}/
  ├── schema.sql       DB schema (CREATE TABLE ...)
  ├── db.sql           Row data (INSERT INTO ...)
  └── metadata.yaml    Capture context: id, dates, table counts, note
```

## When to capture

Per `docs/EVAL_HARNESS.md` §4, you only need a snapshot when at least one
eval case needs frozen state (regression tests, numerical accuracy, or
date-sensitive logic). Most cases run `mode: live` against the actual DB —
no snapshot required.

So: don't capture speculatively. Capture when you're writing a case that
references a specific snapshot_id.

## What's in this directory

Other than this README, everything is gitignored. Run the capture script
to populate.
