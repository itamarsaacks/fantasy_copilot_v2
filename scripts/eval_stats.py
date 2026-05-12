#!/usr/bin/env python3
"""Stats CLI for the eval harness.

Queries the `eval_runs` and `eval_case_results` tables and prints a
human-readable report. Read-only, safe to run any time. Built as the
foundation for the future dashboard — every slice here will eventually
become a chart.

Usage:
  python scripts/eval_stats.py              # recent runs + suite health
  python scripts/eval_stats.py --runs 20    # show last 20 runs in the trend
  python scripts/eval_stats.py --domain     # slice by intent_domain
  python scripts/eval_stats.py --question-type
  python scripts/eval_stats.py --complexity
  python scripts/eval_stats.py --slow       # 10 slowest phrasings ever
  python scripts/eval_stats.py --failures   # most-frequent failed assertions
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make `app.*` importable + reuse the project's settings/DSN.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402


def get_sync_dsn() -> str:
    """Convert SQLAlchemy async URL → plain Postgres DSN for psycopg2/psycopg."""
    url = get_settings().database_url
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


def open_conn():
    import psycopg

    return psycopg.connect(get_sync_dsn())


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _hr(title: str = "") -> None:
    if title:
        print(f"\n── {title} " + "─" * max(0, 65 - len(title)))
    else:
        print("─" * 70)


def _bar(pct: float, width: int = 20) -> str:
    """ASCII progress bar. pct in [0, 1]."""
    filled = int(round(pct * width))
    return "█" * filled + "░" * (width - filled)


def _fmt_pct(passed: int, total: int) -> str:
    if total == 0:
        return "—"
    return f"{passed / total * 100:5.1f}%"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def section_recent_runs(cur, limit: int) -> None:
    _hr(f"Recent runs (last {limit})")
    cur.execute(
        """
        SELECT
          id, started_at, total_phrasings, strict_passed, soft_passed,
          failed, errored, total_latency_ms, git_branch, notes
        FROM eval_runs
        ORDER BY started_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    rows = cur.fetchall()
    if not rows:
        print("  (no runs yet)")
        return
    print(
        f"  {'id':>3}  {'when':<19}  {'pass':>4}  {'soft':>4}  {'fail':>4}  "
        f"{'err':>3}  {'%':>6}  {'sec':>5}  branch / notes"
    )
    for r in rows:
        rid, started, total, p, s, f, e, lat_ms, branch, notes = r
        pct = _fmt_pct(p + s, total)
        sec = f"{lat_ms / 1000:5.0f}"
        ts = started.strftime("%Y-%m-%d %H:%M")
        suffix = f"{branch or '?':<14}"
        if notes:
            suffix += f"  — {notes[:40]}"
        print(
            f"  {rid:>3}  {ts}  {p:>4}  {s:>4}  {f:>4}  {e:>3}  "
            f"{pct:>6}  {sec}  {suffix}"
        )


def section_slice(cur, column: str, label: str) -> None:
    """Generic slicer: pass-rate by an intent_* column, all-time."""
    _hr(f"Pass rate by {label} (all-time)")
    cur.execute(
        f"""
        SELECT
          {column} AS bucket,
          count(*) AS total,
          sum(case when verdict in ('pass','soft_pass') and not errored then 1 else 0 end) AS passed,
          sum(case when verdict='fail' then 1 else 0 end) AS failed,
          avg(latency_ms)::int AS avg_lat_ms
        FROM eval_case_results
        GROUP BY {column}
        ORDER BY count(*) DESC
        """
    )
    rows = cur.fetchall()
    if not rows:
        print("  (no data)")
        return
    print(
        f"  {label:<22}  {'runs':>5}  {'pass%':>6}  bar              {'avg_ms':>6}  fail"
    )
    for bucket, total, passed, failed, avg_lat in rows:
        pct = passed / total if total else 0
        print(
            f"  {bucket:<22}  {total:>5}  {pct * 100:5.1f}%  {_bar(pct)}  "
            f"{avg_lat:>6}  {failed}"
        )


def section_slow(cur, limit: int = 10) -> None:
    _hr(f"Slowest {limit} phrasings (all-time)")
    cur.execute(
        """
        SELECT case_id, phrasing, latency_ms, verdict, run_id
        FROM eval_case_results
        WHERE not errored
        ORDER BY latency_ms DESC
        LIMIT %s
        """,
        (limit,),
    )
    rows = cur.fetchall()
    print(
        f"  {'run':>3}  {'ms':>6}  {'verdict':<9}  case_id / phrasing"
    )
    for case_id, phrasing, lat, verdict, run_id in rows:
        p = phrasing if len(phrasing) <= 50 else phrasing[:47] + "..."
        print(f"  {run_id:>3}  {lat:>6}  {verdict:<9}  {case_id}  ·  \"{p}\"")


def section_failure_clusters(cur, limit: int = 10) -> None:
    _hr(f"Top {limit} failure modes (assertion that failed, all-time)")
    cur.execute(
        """
        SELECT
          f->>'assertion' AS assertion,
          f->>'severity' AS severity,
          count(*) AS occurrences
        FROM eval_case_results
        CROSS JOIN LATERAL jsonb_array_elements(failure_reasons) f
        GROUP BY 1, 2
        ORDER BY occurrences DESC
        LIMIT %s
        """,
        (limit,),
    )
    rows = cur.fetchall()
    if not rows:
        print("  (no failures recorded — every case has passed every time)")
        return
    print(f"  {'occurrences':>11}  {'severity':<10}  assertion")
    for assertion, severity, n in rows:
        print(f"  {n:>11}  {severity or '?':<10}  {assertion}")


def section_health(cur) -> None:
    _hr("Suite health (last run)")
    cur.execute(
        """
        SELECT total_phrasings, strict_passed, soft_passed, failed, errored
        FROM eval_runs ORDER BY started_at DESC LIMIT 1
        """
    )
    row = cur.fetchone()
    if not row:
        print("  (no runs yet)")
        return
    total, strict, soft, failed, errored = row
    passed = strict + soft
    pct = passed / total if total else 0
    print(f"  Pass rate: {pct * 100:.1f}%  {_bar(pct, 40)}")
    print(f"  🟢 {strict}    🟡 {soft}    🔴 {failed}    💥 {errored}    (of {total})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", type=int, default=10, help="Recent-runs window")
    p.add_argument("--domain", action="store_true", help="Slice by intent_domain")
    p.add_argument("--question-type", action="store_true", help="Slice by intent_question_type")
    p.add_argument("--complexity", action="store_true", help="Slice by intent_complexity")
    p.add_argument("--slow", action="store_true", help="Show slowest phrasings")
    p.add_argument("--failures", action="store_true", help="Top failed assertions")
    p.add_argument("--all", action="store_true", help="Show every section")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    any_slice = (
        args.domain or args.question_type or args.complexity
        or args.slow or args.failures
    )
    show_all = args.all or not any_slice

    try:
        with open_conn() as conn:
            with conn.cursor() as cur:
                section_health(cur)
                section_recent_runs(cur, args.runs)
                if show_all or args.domain:
                    section_slice(cur, "intent_domain", "domain")
                if show_all or args.question_type:
                    section_slice(cur, "intent_question_type", "question_type")
                if show_all or args.complexity:
                    section_slice(cur, "intent_complexity", "complexity")
                if show_all or args.slow:
                    section_slow(cur)
                if show_all or args.failures:
                    section_failure_clusters(cur)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
