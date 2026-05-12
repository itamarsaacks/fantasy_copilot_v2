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
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    expected: Any            # what the case said should happen
    actual: Any              # what we saw
    detail: str = ""        # human-readable explanation


class PhrasingRun(BaseModel):
    """One agent invocation: one phrasing × one repeat."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    phrasing: str
    repeat_index: int       # 0-based; useful when repeat > 1

    passed: bool
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


class CaseResult(BaseModel):
    """All PhrasingRuns for one case, plus aggregates."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    mode: str
    snapshot_id: str | None = None

    runs: list[PhrasingRun] = Field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.runs if r.passed and not r.errored)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.runs if not r.passed and not r.errored)

    @property
    def errored(self) -> int:
        return sum(1 for r in self.runs if r.errored)

    @property
    def total(self) -> int:
        return len(self.runs)

    @property
    def all_passed(self) -> bool:
        return self.passed == self.total and self.total > 0


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
        return sum(r.passed for r in self.results)

    @property
    def failed(self) -> int:
        return sum(r.failed for r in self.results)

    @property
    def errored(self) -> int:
        return sum(r.errored for r in self.results)
