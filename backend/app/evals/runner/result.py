"""Result types for one runner invocation.

The runner produces a tree: Run → CaseResult → PhrasingRun → AssertionFailure.
A PhrasingRun is "one phrasing × one repeat" — the unit the dashboard counts
when computing pass rates.

These types match the §7 result schema in docs/EVAL_HARNESS.md. In Phase E1
they live in-memory only (printed to console). Phase E2 maps them onto the
`eval_runs` / `eval_case_results` Postgres tables.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.evals.schema import Severity


class Verdict(str, Enum):
    """The runner's verdict on one PhrasingRun.

    See docs/EVAL_HARNESS.md §6 and schema.Severity for the rationale.
      - PASS: every assertion (critical + warning) passed
      - SOFT_PASS: all critical passed, at least one warning failed
      - FAIL: at least one critical failed
    Plus the orthogonal `errored` flag for crashes that prevent verdicting.
    """

    PASS = "pass"
    SOFT_PASS = "soft_pass"
    FAIL = "fail"


class ToolCallTrace(BaseModel):
    """One tool call captured from the agent's message trace."""

    model_config = ConfigDict(extra="forbid")

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    output_preview: str = ""  # truncated string view for logging


class AssertionFailure(BaseModel):
    """One assertion that didn't pass for one PhrasingRun."""

    model_config = ConfigDict(extra="forbid")

    assertion: str          # e.g. "must_call_tools"
    severity: Severity      # critical or warning — drives the verdict
    expected: Any            # what the case said should happen
    actual: Any              # what we saw
    detail: str = ""        # human-readable explanation


class PhrasingRun(BaseModel):
    """One agent invocation: one phrasing × one repeat."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    phrasing: str
    repeat_index: int       # 0-based; useful when repeat > 1

    # Verdict is computed from failures + their severities. See compute_verdict().
    verdict: Verdict = Verdict.PASS
    errored: bool = False
    error_message: str = ""

    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    final_response: str = ""
    latency_ms: int = 0

    failures: list[AssertionFailure] = Field(default_factory=list)

    # Phase E2 will populate these:
    langsmith_trace_id: str | None = None
    langsmith_trace_url: str | None = None
    agent_thread_id: str | None = None

    @property
    def critical_failures(self) -> list[AssertionFailure]:
        return [f for f in self.failures if f.severity == Severity.CRITICAL]

    @property
    def warning_failures(self) -> list[AssertionFailure]:
        return [f for f in self.failures if f.severity == Severity.WARNING]


def compute_verdict(failures: list[AssertionFailure]) -> Verdict:
    """Map a list of failures to a verdict using severity tiers."""
    if any(f.severity == Severity.CRITICAL for f in failures):
        return Verdict.FAIL
    if any(f.severity == Severity.WARNING for f in failures):
        return Verdict.SOFT_PASS
    return Verdict.PASS


class CaseResult(BaseModel):
    """All PhrasingRuns for one case, plus aggregates."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    runs: list[PhrasingRun] = Field(default_factory=list)

    @property
    def passed(self) -> int:
        """PASS + SOFT_PASS — both ship without blocking regression-tracking."""
        return sum(
            1 for r in self.runs
            if not r.errored and r.verdict in (Verdict.PASS, Verdict.SOFT_PASS)
        )

    @property
    def strict_passed(self) -> int:
        """Only PASS (no warning failures)."""
        return sum(1 for r in self.runs if not r.errored and r.verdict == Verdict.PASS)

    @property
    def soft_passed(self) -> int:
        """SOFT_PASS — passing on critical assertions, drifting on warnings."""
        return sum(1 for r in self.runs if not r.errored and r.verdict == Verdict.SOFT_PASS)

    @property
    def failed(self) -> int:
        """FAIL — at least one critical assertion failed. Blocks merges."""
        return sum(1 for r in self.runs if not r.errored and r.verdict == Verdict.FAIL)

    @property
    def errored(self) -> int:
        return sum(1 for r in self.runs if r.errored)

    @property
    def total(self) -> int:
        return len(self.runs)

    @property
    def all_passed(self) -> bool:
        """True when zero failures and zero errors (soft passes still count)."""
        return self.failed == 0 and self.errored == 0 and self.total > 0


class RunSummary(BaseModel):
    """Top-level summary of one harness invocation."""

    model_config = ConfigDict(extra="forbid")

    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    results: list[CaseResult] = Field(default_factory=list)

    @property
    def total_phrasings(self) -> int:
        return sum(r.total for r in self.results)

    @property
    def passed(self) -> int:
        """PASS + SOFT_PASS."""
        return sum(r.passed for r in self.results)

    @property
    def strict_passed(self) -> int:
        return sum(r.strict_passed for r in self.results)

    @property
    def soft_passed(self) -> int:
        return sum(r.soft_passed for r in self.results)

    @property
    def failed(self) -> int:
        return sum(r.failed for r in self.results)

    @property
    def errored(self) -> int:
        return sum(r.errored for r in self.results)
