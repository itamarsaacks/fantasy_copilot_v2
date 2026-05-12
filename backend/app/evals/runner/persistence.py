"""Persist runner results to Postgres.

Writes one `EvalRun` row plus N `EvalCaseResult` rows (N = total phrasings).
Called by run.py after the in-memory RunSummary is finalized. If anything
here fails, the runner still prints the console summary — persistence is
best-effort, not load-bearing for the user feedback loop.

See docs/EVAL_HARNESS.md §7 for the schema.
"""

from __future__ import annotations

import subprocess
from typing import Iterable

from app.db.engine import SessionLocal
from app.db.models import EvalCaseResult, EvalRun
from app.evals.runner.result import CaseResult, PhrasingRun, RunSummary
from app.evals.schema import EvalCase


def _git(*args: str) -> str | None:
    """Run a git command. Return stripped stdout or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False, timeout=5
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _git_sha() -> str | None:
    return _git("rev-parse", "HEAD")


def _git_branch() -> str | None:
    return _git("rev-parse", "--abbrev-ref", "HEAD")


def _phrasing_row(
    run_id: int,
    case: EvalCase,
    pr: PhrasingRun,
) -> EvalCaseResult:
    """Map an in-memory PhrasingRun + its case context into a DB row."""
    return EvalCaseResult(
        run_id=run_id,
        case_id=case.id,
        phrasing=pr.phrasing,
        repeat_index=pr.repeat_index,
        verdict=pr.verdict.value,
        errored=pr.errored,
        error_message=pr.error_message or None,
        tool_calls=[tc.model_dump() for tc in pr.tool_calls],
        final_response=pr.final_response,
        failure_reasons=[f.model_dump(mode="json") for f in pr.failures],
        latency_ms=pr.latency_ms,
        tokens_in=None,  # not yet captured — Phase E2.1+
        tokens_out=None,
        cost_usd=None,
        langsmith_trace_id=pr.langsmith_trace_id,
        langsmith_trace_url=pr.langsmith_trace_url,
        langsmith_thread_id=pr.langsmith_thread_id,
        agent_thread_id=pr.agent_thread_id,
        intent_question_type=case.intent.question_type.value,
        intent_complexity=case.intent.complexity.value,
        intent_domain=case.intent.domain.value,
        intent_answer_shape=case.intent.answer_shape.value,
        tags=list(case.tags),
    )


def _iter_cases_by_id(cases: Iterable[EvalCase]) -> dict[str, EvalCase]:
    return {c.id: c for c in cases}


async def persist_run(
    summary: RunSummary,
    cases: list[EvalCase],
    *,
    model: str | None,
    triggered_by: str = "manual",
    notes: str | None = None,
) -> int | None:
    """Insert one EvalRun + N EvalCaseResult rows. Returns the run_id.

    Returns None and logs to stderr if persistence fails — never raises into
    the runner so a DB hiccup doesn't kill the visible output.
    """
    import sys

    case_lookup = _iter_cases_by_id(cases)
    total_latency = sum(pr.latency_ms for cr in summary.results for pr in cr.runs)

    run = EvalRun(
        started_at=summary.started_at,
        finished_at=summary.finished_at,
        git_sha=_git_sha(),
        git_branch=_git_branch(),
        triggered_by=triggered_by,
        model=model,
        total_cases=len(summary.results),
        total_phrasings=summary.total_phrasings,
        strict_passed=summary.strict_passed,
        soft_passed=summary.soft_passed,
        failed=summary.failed,
        errored=summary.errored,
        total_latency_ms=total_latency,
        total_cost_usd=None,
        notes=notes,
    )

    try:
        async with SessionLocal() as db:
            db.add(run)
            await db.flush()  # get run.id without committing yet

            for cr in summary.results:
                case = case_lookup.get(cr.case_id)
                if case is None:
                    continue
                for pr in cr.runs:
                    db.add(_phrasing_row(run.id, case, pr))

            await db.commit()
            return run.id
    except Exception as e:  # noqa: BLE001
        print(f"WARN: failed to persist eval run: {e}", file=sys.stderr)
        return None
