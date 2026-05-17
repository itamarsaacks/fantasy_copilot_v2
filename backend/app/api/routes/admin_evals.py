"""Admin-only eval dashboard endpoints.

Gated by `require_admin` (cookie auth + ADMIN_USER_IDS env). Surfaces
the eval harness data — runs, cases, results — so we can review traces,
catch regressions, and validate case coverage without dropping into psql.

Endpoints:
  GET /api/admin/evals/summary           dashboard homepage stats
  GET /api/admin/evals/runs              list runs newest-first
  GET /api/admin/evals/runs/{run_id}     run detail + every case result
  GET /api/admin/evals/cases             case library (YAML on disk) + latest verdict
  GET /api/admin/evals/cases/{case_id}   case detail across recent runs
  GET /api/admin/evals/regressions       cases whose latest verdict regressed vs the prior run
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import EvalCaseResult, EvalRun, User
from app.evals.loader import discover_cases
from app.evals.schema import EvalCase
from app.security import require_admin

router = APIRouter(prefix="/api/admin/evals", tags=["admin-evals"])

# Where the on-disk case library lives.
_CASES_ROOT = Path(__file__).resolve().parents[3] / "app" / "evals" / "cases"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RunSummary(BaseModel):
    id: int
    started_at: str
    finished_at: str | None
    git_sha: str | None
    git_branch: str | None
    triggered_by: str
    model: str | None
    total_cases: int
    total_phrasings: int
    strict_passed: int
    soft_passed: int
    failed: int
    errored: int
    total_latency_ms: int
    total_cost_usd: float | None
    pass_rate: float | None  # (strict + soft) / total_phrasings — None when nothing ran


class CaseResultSummary(BaseModel):
    id: int
    case_id: str
    phrasing: str
    repeat_index: int
    verdict: str
    errored: bool
    error_message: str | None
    latency_ms: int
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None
    langsmith_trace_url: str | None
    intent_question_type: str
    intent_complexity: str
    intent_domain: str
    failure_reasons: list[dict[str, Any]]
    tool_calls_count: int  # don't ship full tool calls in list views


class CaseResultDetail(CaseResultSummary):
    final_response: str
    tool_calls: list[dict[str, Any]]


class RunDetailResponse(BaseModel):
    run: RunSummary
    results: list[CaseResultSummary]


class CaseLibraryEntry(BaseModel):
    case_id: str
    intent_question_type: str | None
    intent_complexity: str | None
    intent_domain: str | None
    tags: list[str]
    phrasings_count: int
    repeats: int
    latest_verdict: str | None  # most recent verdict any phrasing produced
    latest_run_id: int | None


class CaseDetailRun(BaseModel):
    run_id: int
    started_at: str
    verdicts: dict[str, int]  # counts per verdict for this case in this run
    results: list[CaseResultSummary]


class CaseDetailResponse(BaseModel):
    case_id: str
    case_yaml_path: str | None
    intent_question_type: str | None
    intent_complexity: str | None
    intent_domain: str | None
    tags: list[str]
    runs: list[CaseDetailRun]


class RegressionItem(BaseModel):
    case_id: str
    latest_verdict: str
    latest_run_id: int
    prior_verdict: str
    prior_run_id: int
    direction: Literal["worsened", "improved"]


class SummaryResponse(BaseModel):
    total_runs: int
    latest_run: RunSummary | None
    overall_pass_rate_last_run: float | None
    cases_on_disk: int
    cases_with_history: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pass_rate(run: EvalRun) -> float | None:
    total = run.total_phrasings or 0
    if total == 0:
        return None
    return round((run.strict_passed + run.soft_passed) / total, 4)


def _run_summary(run: EvalRun) -> RunSummary:
    return RunSummary(
        id=run.id,
        started_at=run.started_at.isoformat(),
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        git_sha=run.git_sha,
        git_branch=run.git_branch,
        triggered_by=run.triggered_by,
        model=run.model,
        total_cases=run.total_cases,
        total_phrasings=run.total_phrasings,
        strict_passed=run.strict_passed,
        soft_passed=run.soft_passed,
        failed=run.failed,
        errored=run.errored,
        total_latency_ms=run.total_latency_ms,
        total_cost_usd=float(run.total_cost_usd) if run.total_cost_usd is not None else None,
        pass_rate=_pass_rate(run),
    )


def _result_summary(r: EvalCaseResult) -> CaseResultSummary:
    return CaseResultSummary(
        id=r.id,
        case_id=r.case_id,
        phrasing=r.phrasing,
        repeat_index=r.repeat_index,
        verdict=r.verdict,
        errored=r.errored,
        error_message=r.error_message,
        latency_ms=r.latency_ms,
        tokens_in=r.tokens_in,
        tokens_out=r.tokens_out,
        cost_usd=float(r.cost_usd) if r.cost_usd is not None else None,
        langsmith_trace_url=r.langsmith_trace_url,
        intent_question_type=r.intent_question_type,
        intent_complexity=r.intent_complexity,
        intent_domain=r.intent_domain,
        failure_reasons=r.failure_reasons or [],
        tool_calls_count=len(r.tool_calls or []),
    )


def _result_detail(r: EvalCaseResult) -> CaseResultDetail:
    return CaseResultDetail(
        **_result_summary(r).model_dump(),
        final_response=r.final_response,
        tool_calls=r.tool_calls or [],
    )


_VERDICT_ORDER = {"PASS": 0, "SOFT_PASS": 1, "FAIL": 2, "ERROR": 3}


def _verdict_rank(v: str) -> int:
    return _VERDICT_ORDER.get(v, 4)


def _discover_cases_on_disk() -> tuple[dict[str, EvalCase], dict[str, Path]]:
    cases, _errs = discover_cases(_CASES_ROOT)
    by_id = {c.id: c for c in cases}
    paths: dict[str, Path] = {}
    for path in list(_CASES_ROOT.rglob("*.yaml")) + list(_CASES_ROOT.rglob("*.yml")):
        # Pair YAMLs to case_ids by parsing top-level `id:` cheaply
        try:
            import yaml

            raw = yaml.safe_load(path.read_text())
            cid = raw.get("id") if isinstance(raw, dict) else None
            if cid:
                paths[str(cid)] = path
        except Exception:  # noqa: BLE001
            continue
    return by_id, paths


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=SummaryResponse)
async def get_summary(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    total_runs = (
        await db.execute(select(func.count()).select_from(EvalRun))
    ).scalar_one()
    latest = (
        await db.execute(select(EvalRun).order_by(desc(EvalRun.started_at)).limit(1))
    ).scalar_one_or_none()
    distinct_cases = (
        await db.execute(select(func.count(func.distinct(EvalCaseResult.case_id))))
    ).scalar_one()
    cases_by_id, _ = _discover_cases_on_disk()
    return SummaryResponse(
        total_runs=total_runs,
        latest_run=_run_summary(latest) if latest else None,
        overall_pass_rate_last_run=_pass_rate(latest) if latest else None,
        cases_on_disk=len(cases_by_id),
        cases_with_history=distinct_cases,
    )


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(
    limit: int = Query(default=30, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    runs = (
        await db.execute(
            select(EvalRun).order_by(desc(EvalRun.started_at)).limit(limit)
        )
    ).scalars().all()
    return [_run_summary(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    run = await db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    results = (
        await db.execute(
            select(EvalCaseResult)
            .where(EvalCaseResult.run_id == run_id)
            .order_by(EvalCaseResult.case_id, EvalCaseResult.repeat_index)
        )
    ).scalars().all()
    return RunDetailResponse(
        run=_run_summary(run),
        results=[_result_summary(r) for r in results],
    )


@router.get("/cases", response_model=list[CaseLibraryEntry])
async def list_cases(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    cases_by_id, _paths = _discover_cases_on_disk()

    # For each case_id with history, fetch the most recent result row.
    # One pass: pull all distinct (case_id, latest_run_id, latest_result_id)
    # via a window function would be more elegant, but for ~40 cases × N
    # results, a per-case subquery is fine here.
    latest_by_case: dict[str, tuple[str, int]] = {}
    rows = (
        await db.execute(
            select(
                EvalCaseResult.case_id,
                EvalCaseResult.verdict,
                EvalCaseResult.run_id,
                EvalCaseResult.id,
            )
            .order_by(EvalCaseResult.case_id, desc(EvalCaseResult.id))
        )
    ).all()
    # rows are ordered case_id asc, id desc — first per case_id is the latest.
    seen_case_ids: set[str] = set()
    for case_id, verdict, run_id, _rid in rows:
        if case_id in seen_case_ids:
            continue
        latest_by_case[case_id] = (verdict, run_id)
        seen_case_ids.add(case_id)

    entries: list[CaseLibraryEntry] = []
    # Cases that exist on disk
    for case_id, case in sorted(cases_by_id.items()):
        latest = latest_by_case.get(case_id)
        entries.append(
            CaseLibraryEntry(
                case_id=case_id,
                intent_question_type=str(case.intent.question_type.value)
                if hasattr(case.intent.question_type, "value")
                else str(case.intent.question_type),
                intent_complexity=str(getattr(case.intent.complexity, "value", case.intent.complexity)),
                intent_domain=str(getattr(case.intent.domain, "value", case.intent.domain)),
                tags=case.tags,
                phrasings_count=len(case.phrasings) if case.phrasings else 0,
                repeats=case.repeat,
                latest_verdict=latest[0] if latest else None,
                latest_run_id=latest[1] if latest else None,
            )
        )
    # Cases in DB but not on disk (e.g. renamed) — surface them anyway
    for case_id, (verdict, run_id) in latest_by_case.items():
        if case_id in cases_by_id:
            continue
        entries.append(
            CaseLibraryEntry(
                case_id=case_id,
                intent_question_type=None,
                intent_complexity=None,
                intent_domain=None,
                tags=[],
                phrasings_count=0,
                repeats=0,
                latest_verdict=verdict,
                latest_run_id=run_id,
            )
        )
    return entries


@router.get("/cases/{case_id}", response_model=CaseDetailResponse)
async def get_case(
    case_id: str,
    limit_runs: int = Query(default=10, ge=1, le=50),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    cases_by_id, paths = _discover_cases_on_disk()
    case = cases_by_id.get(case_id)
    yaml_path = paths.get(case_id)

    # Last N runs containing this case
    recent_run_ids = (
        await db.execute(
            select(EvalCaseResult.run_id)
            .where(EvalCaseResult.case_id == case_id)
            .group_by(EvalCaseResult.run_id)
            .order_by(desc(EvalCaseResult.run_id))
            .limit(limit_runs)
        )
    ).scalars().all()
    if not recent_run_ids and case is None:
        raise HTTPException(404, "case not found on disk or in DB")

    runs_meta: dict[int, EvalRun] = {}
    if recent_run_ids:
        run_rows = (
            await db.execute(
                select(EvalRun).where(EvalRun.id.in_(recent_run_ids))
            )
        ).scalars().all()
        runs_meta = {r.id: r for r in run_rows}

    results_by_run: dict[int, list[EvalCaseResult]] = {}
    if recent_run_ids:
        all_results = (
            await db.execute(
                select(EvalCaseResult)
                .where(
                    EvalCaseResult.case_id == case_id,
                    EvalCaseResult.run_id.in_(recent_run_ids),
                )
                .order_by(EvalCaseResult.run_id, EvalCaseResult.repeat_index)
            )
        ).scalars().all()
        for r in all_results:
            results_by_run.setdefault(r.run_id, []).append(r)

    run_blocks: list[CaseDetailRun] = []
    for run_id in recent_run_ids:
        run = runs_meta.get(run_id)
        rows = results_by_run.get(run_id, [])
        verdicts_counter = Counter(r.verdict for r in rows)
        run_blocks.append(
            CaseDetailRun(
                run_id=run_id,
                started_at=run.started_at.isoformat() if run else "",
                verdicts=dict(verdicts_counter),
                results=[_result_summary(r) for r in rows],
            )
        )

    return CaseDetailResponse(
        case_id=case_id,
        case_yaml_path=str(yaml_path.relative_to(_CASES_ROOT.parent.parent.parent.parent))
        if yaml_path
        else None,
        intent_question_type=str(getattr(case.intent.question_type, "value", case.intent.question_type))
        if case
        else None,
        intent_complexity=str(getattr(case.intent.complexity, "value", case.intent.complexity))
        if case
        else None,
        intent_domain=str(getattr(case.intent.domain, "value", case.intent.domain))
        if case
        else None,
        tags=case.tags if case else [],
        runs=run_blocks,
    )


@router.get("/regressions", response_model=list[RegressionItem])
async def list_regressions(
    limit: int = Query(default=20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """Cases whose worst-verdict-in-latest-run is worse than worst-verdict-in-prior-run.

    Worst is what matters because a 3/4 → 4/4 isn't a regression; what
    matters is whether *any* phrasing now fails that didn't before, and
    vice versa.
    """
    # Each case's two most recent runs (run_id list ordered desc)
    rows = (
        await db.execute(
            select(EvalCaseResult.case_id, EvalCaseResult.run_id, EvalCaseResult.verdict)
            .order_by(desc(EvalCaseResult.run_id))
        )
    ).all()

    # case_id -> [(run_id, worst_verdict)] in run-desc order; build it.
    by_case: dict[str, list[tuple[int, str]]] = {}
    seen_pairs: dict[tuple[str, int], str] = {}
    for case_id, run_id, verdict in rows:
        key = (case_id, run_id)
        prev = seen_pairs.get(key)
        if prev is None or _verdict_rank(verdict) > _verdict_rank(prev):
            seen_pairs[key] = verdict
    # Convert to per-case ordered list
    for (case_id, run_id), verdict in seen_pairs.items():
        by_case.setdefault(case_id, []).append((run_id, verdict))
    for case_id in by_case:
        by_case[case_id].sort(key=lambda x: -x[0])

    items: list[RegressionItem] = []
    for case_id, history in by_case.items():
        if len(history) < 2:
            continue
        latest_run, latest_verdict = history[0]
        prior_run, prior_verdict = history[1]
        latest_rank = _verdict_rank(latest_verdict)
        prior_rank = _verdict_rank(prior_verdict)
        if latest_rank == prior_rank:
            continue
        items.append(
            RegressionItem(
                case_id=case_id,
                latest_verdict=latest_verdict,
                latest_run_id=latest_run,
                prior_verdict=prior_verdict,
                prior_run_id=prior_run,
                direction="worsened" if latest_rank > prior_rank else "improved",
            )
        )
    # Worsened first, then improved
    items.sort(
        key=lambda i: (0 if i.direction == "worsened" else 1, i.case_id)
    )
    return items[:limit]
