"""Main entry point — discovers cases, runs them, prints results.

Phase E1: live mode only. Snapshot mode raises NotImplementedError.

Usage (via the wrapper script):
  python scripts/run_evals.py                 # all live-mode cases
  python scripts/run_evals.py --case waiver_days_offseason
  python scripts/run_evals.py --domain rules
  python scripts/run_evals.py --dry-run       # validate cases only, don't invoke agent
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from pathlib import Path

from app.evals.loader import discover_cases
from app.evals.runner.assertions import check_all
from app.evals.runner.result import (
    CaseResult,
    PhrasingRun,
    RunSummary,
    Verdict,
    compute_verdict,
)
from app.evals.schema import EvalCase, Mode

CASES_ROOT = Path(__file__).resolve().parent.parent / "cases"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--case", help="Run only the case with this id")
    p.add_argument("--domain", help="Run only cases with intent.domain matching")
    p.add_argument("--mode", choices=["live", "snapshot"], help="Filter by run mode")
    p.add_argument("--dry-run", action="store_true", help="Load cases + validate but don't invoke agent")
    return p.parse_args()


def filter_cases(cases: list[EvalCase], args: argparse.Namespace) -> list[EvalCase]:
    out = cases
    if args.case:
        out = [c for c in out if c.id == args.case]
        if not out:
            print(f"ERROR: no case matches id='{args.case}'", file=sys.stderr)
            sys.exit(2)
    if args.domain:
        out = [c for c in out if c.intent.domain.value == args.domain]
    if args.mode:
        out = [c for c in out if c.mode.value == args.mode]
    return out


async def discover_test_user_league() -> tuple[int, int, str]:
    """Pick a (user_id, league_id, scoring_type) to act as for live-mode runs.

    Strategy: first user that has at least one league. First league of that
    user. Future: snapshot metadata.yaml can override this per snapshot.
    """
    from sqlalchemy import select
    from app.db.engine import SessionLocal
    from app.db.models import League, User

    async with SessionLocal() as db:
        result = await db.execute(
            select(User.id, League.id, League.scoring_type)
            .join(League, League.user_id == User.id)
            .order_by(User.id.asc(), League.id.asc())
            .limit(1)
        )
        row = result.first()
    if row is None:
        raise SystemExit(
            "No (user, league) pair found in the live DB. "
            "Sync a Yahoo league first, then re-run."
        )
    return row[0], row[1], row[2]


async def run_case(
    case: EvalCase,
    user_id: int,
    league_id: int,
    scoring_type: str,
) -> CaseResult:
    """Execute every phrasing × repeat for one case. Returns a CaseResult."""

    from app.evals.runner.agent_invoker import invoke

    cr = CaseResult(
        case_id=case.id,
        mode=case.mode.value,
        snapshot_id=case.snapshot_id,
    )

    messages = case.all_messages()
    total = len(messages) * case.repeat
    print(f"  [{case.id}] mode={case.mode.value} runs={total}")

    for phrasing_idx, phrasing in enumerate(messages):
        for repeat_idx in range(case.repeat):
            pr: PhrasingRun = await invoke(
                user_message=phrasing,
                user_id=user_id,
                league_id=league_id,
                scoring_type=scoring_type,
                case_id=case.id,
                phrasing_index=phrasing_idx,
                repeat_index=repeat_idx,
            )
            if not pr.errored:
                failures = check_all(
                    case.expected,
                    tool_calls=pr.tool_calls,
                    final_response=pr.final_response,
                    latency_ms=pr.latency_ms,
                    severity_overrides=case.severity_overrides,
                )
                pr.failures = failures
                pr.verdict = compute_verdict(failures)

            tool_summary = ",".join(tc.name for tc in pr.tool_calls) or "(none)"
            if pr.errored:
                icon = "💥"
                detail = f"ERROR: {pr.error_message}"
            elif pr.verdict == Verdict.PASS:
                icon = "🟢"
                detail = f"{pr.latency_ms}ms · tools=[{tool_summary}]"
            elif pr.verdict == Verdict.SOFT_PASS:
                icon = "🟡"
                detail = (
                    f"{pr.latency_ms}ms · tools=[{tool_summary}] · "
                    f"{len(pr.warning_failures)} warning(s)"
                )
            else:  # FAIL
                icon = "🔴"
                detail = (
                    f"{pr.latency_ms}ms · tools=[{tool_summary}] · "
                    f"{len(pr.critical_failures)} critical, "
                    f"{len(pr.warning_failures)} warning"
                )
            preview = f' · "{phrasing[:60]}"' if len(messages) > 1 else ""
            print(f"    {icon} {detail}{preview}")
            if pr.failures:
                for f in pr.failures:
                    sev_label = "CRIT" if f.severity.value == "critical" else "warn"
                    print(f"      - [{sev_label}] {f.assertion}: {f.detail}")

            cr.runs.append(pr)
    return cr


def print_summary(summary: RunSummary) -> None:
    total = summary.total_phrasings
    pct = (summary.passed / total * 100) if total else 0.0
    duration = (
        (summary.finished_at - summary.started_at).total_seconds()
        if summary.finished_at else 0
    )
    print("\n" + "=" * 70)
    print(f"  Verdict breakdown across {total} phrasing run(s):")
    print(f"    🟢 PASS       {summary.strict_passed}")
    print(f"    🟡 SOFT_PASS  {summary.soft_passed}  (critical-clean, warning drift)")
    print(f"    🔴 FAIL       {summary.failed}")
    print(f"    💥 ERROR      {summary.errored}")
    print(
        f"\n  Overall: {summary.passed}/{total} pass ({pct:.0f}%) "
        f"· {summary.failed} fail · {summary.errored} error · "
        f"{duration:.1f}s wall time"
    )
    if summary.failed or summary.errored:
        print("\n  Cases that need attention:")
        for cr in summary.results:
            if cr.failed or cr.errored:
                print(
                    f"    - {cr.case_id}: {cr.strict_passed} pass · "
                    f"{cr.soft_passed} soft · {cr.failed} fail · {cr.errored} err"
                )
    print("=" * 70)


async def amain() -> int:
    args = parse_args()
    cases, errors = discover_cases(CASES_ROOT)
    if errors:
        print(f"WARNING: {len(errors)} case(s) failed to load:", file=sys.stderr)
        for e in errors:
            print(f"  - {e.path}: {e.original}", file=sys.stderr)

    cases = filter_cases(cases, args)
    if not cases:
        print("No cases match the filters. Nothing to run.")
        return 0

    # E1 is live-mode only. Surface any snapshot cases explicitly.
    snapshot_cases = [c for c in cases if c.mode == Mode.SNAPSHOT]
    live_cases = [c for c in cases if c.mode == Mode.LIVE]
    if snapshot_cases:
        print(
            f"NOTE: {len(snapshot_cases)} snapshot-mode case(s) skipped — "
            f"snapshot runner not implemented yet (Phase E4)."
        )
        for c in snapshot_cases:
            print(f"  - {c.id} (snapshot={c.snapshot_id})")

    if args.dry_run:
        print(f"\nDry run: loaded {len(cases)} case(s) successfully.")
        for c in cases:
            print(f"  - {c.id} mode={c.mode.value} runs={c.total_run_count()}")
        return 0

    if not live_cases:
        print("No live-mode cases to run.")
        return 0

    print(f"Discovering test user/league from live DB...")
    user_id, league_id, scoring_type = await discover_test_user_league()
    print(f"  user_id={user_id} league_id={league_id} scoring_type={scoring_type}")

    # Start LangGraph checkpointer (live DB) — the agent needs it for memory.
    from app.agent import checkpointer
    await checkpointer.start()

    summary = RunSummary(started_at=dt.datetime.now(dt.timezone.utc))
    try:
        for case in live_cases:
            cr = await run_case(case, user_id, league_id, scoring_type)
            summary.results.append(cr)
    finally:
        await checkpointer.stop()

    summary.finished_at = dt.datetime.now(dt.timezone.utc)
    print_summary(summary)

    # Exit non-zero if anything failed/errored
    return 1 if (summary.failed or summary.errored) else 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())
