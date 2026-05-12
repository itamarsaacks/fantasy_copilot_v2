#!/usr/bin/env python3
"""Capture a snapshot of the local fantasy_copilot Postgres DB.

A snapshot is a frozen point-in-time copy that the eval runner replays against.
See docs/EVAL_HARNESS.md §4 (Snapshot strategy) for the design.

What's captured:
  - All application tables (users, leagues, players, stats, projections, ...)
  - alembic_version (so schema matches when restored)

What's NOT captured:
  - checkpoint_* tables (conversation memory — runner starts fresh per case)

Output layout:
  backend/app/evals/snapshots/{snapshot_id}/
    ├── db.sql          pg_dump --data-only output for restore
    ├── metadata.yaml   capture context (date, as_of_date, table counts, note)

Usage:
  python scripts/eval_capture_snapshot.py \\
    --snapshot-id offseason_2026_05 \\
    --as-of-date 2026-05-11 \\
    --note "Off-season, all leagues synced"

  # Overwrite an existing snapshot
  python scripts/eval_capture_snapshot.py --snapshot-id ... --force
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


# Tables we explicitly DON'T include in snapshots.
# The runner starts each case with a fresh conversation thread, so checkpointer
# state from the live DB would only confuse things.
EXCLUDED_TABLES = (
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
)

CONTAINER_NAME = "fantasy_copilot_v2_db"
DB_USER = "fantasy"
DB_NAME = "fantasy_copilot"

SNAPSHOTS_ROOT = Path(__file__).resolve().parent.parent / "backend" / "app" / "evals" / "snapshots"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--snapshot-id", required=True, help="Stable identifier, e.g. 'offseason_2026_05'")
    p.add_argument(
        "--as-of-date",
        required=True,
        help="YYYY-MM-DD. The date the agent should believe it is when this snapshot is replayed.",
    )
    p.add_argument("--note", default="", help="Free-form description for the metadata file")
    p.add_argument("--force", action="store_true", help="Overwrite an existing snapshot dir")
    return p.parse_args()


def validate_snapshot_id(snapshot_id: str) -> None:
    """Keep IDs filesystem-safe and predictable."""
    if not snapshot_id.replace("_", "").replace("-", "").isalnum():
        raise SystemExit(f"Invalid --snapshot-id '{snapshot_id}': use letters, digits, _, -")


def validate_as_of_date(s: str) -> str:
    try:
        dt.date.fromisoformat(s)
    except ValueError as e:
        raise SystemExit(f"Invalid --as-of-date '{s}': must be YYYY-MM-DD ({e})") from e
    return s


def ensure_container_running() -> None:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise SystemExit(
            f"Postgres container '{CONTAINER_NAME}' is not running.\n"
            f"Start it with: docker compose up -d"
        )


def prepare_output_dir(snapshot_id: str, force: bool) -> Path:
    out_dir = SNAPSHOTS_ROOT / snapshot_id
    if out_dir.exists():
        if not force:
            raise SystemExit(
                f"Snapshot dir already exists: {out_dir}\n"
                f"Pass --force to overwrite, or pick a different --snapshot-id."
            )
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    return out_dir


def dump_data(out_path: Path) -> None:
    """Run pg_dump inside the container, write SQL to out_path on the host."""
    cmd = [
        "docker",
        "exec",
        CONTAINER_NAME,
        "pg_dump",
        "-U",
        DB_USER,
        "-d",
        DB_NAME,
        "--data-only",
        "--no-owner",
        "--no-privileges",
        # Quote target identifier-style — pg_dump's `-T` accepts patterns.
        *[arg for table in EXCLUDED_TABLES for arg in ("-T", table)],
    ]
    with out_path.open("wb") as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise SystemExit(f"pg_dump failed:\n{result.stderr.decode()}")


def dump_schema(out_path: Path) -> None:
    """Schema-only dump. Restored before data so the eval DB matches structure."""
    cmd = [
        "docker",
        "exec",
        CONTAINER_NAME,
        "pg_dump",
        "-U",
        DB_USER,
        "-d",
        DB_NAME,
        "--schema-only",
        "--no-owner",
        "--no-privileges",
    ]
    with out_path.open("wb") as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise SystemExit(f"pg_dump --schema-only failed:\n{result.stderr.decode()}")


def table_counts() -> dict[str, int]:
    """Quick sanity counts for metadata. Skips excluded tables."""
    cmd = [
        "docker",
        "exec",
        CONTAINER_NAME,
        "psql",
        "-U",
        DB_USER,
        "-d",
        DB_NAME,
        "-At",
        "-c",
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public' ORDER BY table_name;
        """,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"psql list-tables failed:\n{result.stderr}")
    tables = [t for t in result.stdout.strip().splitlines() if t and t not in EXCLUDED_TABLES]

    counts: dict[str, int] = {}
    for table in tables:
        c = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "psql",
                "-U",
                DB_USER,
                "-d",
                DB_NAME,
                "-At",
                "-c",
                f"SELECT count(*) FROM {table};",
            ],
            capture_output=True,
            text=True,
        )
        if c.returncode == 0:
            counts[table] = int(c.stdout.strip())
    return counts


def write_metadata(out_dir: Path, snapshot_id: str, as_of_date: str, note: str, counts: dict[str, int]) -> Path:
    meta_path = out_dir / "metadata.yaml"
    metadata = {
        "snapshot_id": snapshot_id,
        "captured_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
        "as_of_date": as_of_date,
        "note": note,
        "source": {
            "container": CONTAINER_NAME,
            "database": DB_NAME,
        },
        "excluded_tables": list(EXCLUDED_TABLES),
        "table_row_counts": counts,
        "total_rows": sum(counts.values()),
    }
    with meta_path.open("w") as f:
        yaml.safe_dump(metadata, f, sort_keys=False)
    return meta_path


def main() -> int:
    args = parse_args()
    validate_snapshot_id(args.snapshot_id)
    validate_as_of_date(args.as_of_date)
    ensure_container_running()

    out_dir = prepare_output_dir(args.snapshot_id, args.force)
    print(f"Capturing snapshot '{args.snapshot_id}' -> {out_dir}")

    schema_path = out_dir / "schema.sql"
    data_path = out_dir / "db.sql"

    print("  - dumping schema...")
    dump_schema(schema_path)
    print(f"    {schema_path} ({schema_path.stat().st_size:,} bytes)")

    print("  - dumping data...")
    dump_data(data_path)
    print(f"    {data_path} ({data_path.stat().st_size:,} bytes)")

    print("  - counting rows...")
    counts = table_counts()
    meta_path = write_metadata(out_dir, args.snapshot_id, args.as_of_date, args.note, counts)
    print(f"    {meta_path}")

    total = sum(counts.values())
    print(f"\nDone. {len(counts)} tables, {total:,} rows total.")
    print(f"\nTop-5 tables by row count:")
    for table, n in sorted(counts.items(), key=lambda kv: -kv[1])[:5]:
        print(f"  {table}: {n:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
