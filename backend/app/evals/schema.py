"""Pydantic schema for eval cases.

A case is a YAML file under `evals/cases/{manual,promoted,generated}/`.
This module is the single source of truth for what a valid case looks like.
The runner, the promoter, and the eval-author skill all load through here.

See docs/EVAL_HARNESS.md §6 for the prose spec.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Run mode (§4 — live vs snapshot)
# ---------------------------------------------------------------------------


class Mode(str, Enum):
    """Whether the case runs against the live DB or a frozen snapshot.

    See docs/EVAL_HARNESS.md §4 for the full rationale. Short version:
      - LIVE: most cases. Asserts on agent behavior (tool routing, no
        hallucination, format, cost). Default.
      - SNAPSHOT: minority of cases. Required when assertions need
        frozen ground truth (regression tests, numerical accuracy,
        date-sensitive logic).
    """

    LIVE = "live"
    SNAPSHOT = "snapshot"


# Assertion fields that perform content-equality. Forbidden in live mode
# because they require frozen ground truth to be stable.
CONTENT_EQUALITY_FIELDS = ("response_contains_all", "response_matches_regex")


# ---------------------------------------------------------------------------
# Severity tiers (introduced 2026-05-12)
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    """How seriously to treat an assertion failure.

    See docs/EVAL_HARNESS.md §6 for the verdict logic. Short version:
      - All criticals pass + all warnings pass → 🟢 PASS
      - All criticals pass, some warnings fail → 🟡 SOFT_PASS
                  (counts as pass for regression-tracking;
                   surfaced in weekly digest as drift)
      - Any critical fails → 🔴 FAIL
    """

    CRITICAL = "critical"
    WARNING = "warning"


# Default severity per assertion type. Override per-case via
# EvalCase.severity_overrides when the default doesn't fit.
ASSERTION_SEVERITY_DEFAULTS: dict[str, Severity] = {
    # --- Behavioral correctness (critical) ---
    "must_call_tools": Severity.CRITICAL,
    "must_not_call_tools": Severity.CRITICAL,
    "must_call_tools_in_order": Severity.CRITICAL,
    "tool_call_args_contain": Severity.CRITICAL,
    "response_contains_any": Severity.CRITICAL,
    "response_contains_all": Severity.CRITICAL,
    "response_contains_none": Severity.CRITICAL,
    "response_matches_regex": Severity.CRITICAL,
    "must_ask_clarification": Severity.CRITICAL,
    "clarification_must_mention_any": Severity.CRITICAL,
    # --- Performance / cost / format (warning) ---
    "max_tool_calls": Severity.WARNING,
    "max_latency_ms": Severity.WARNING,
    "max_cost_usd": Severity.WARNING,
    "min_response_chars": Severity.WARNING,
    "max_response_chars": Severity.WARNING,
}


def assertion_severity(name: str, overrides: dict[str, Severity] | None = None) -> Severity:
    """Resolve a case-level severity for one assertion name."""
    if overrides and name in overrides:
        return overrides[name]
    return ASSERTION_SEVERITY_DEFAULTS.get(name, Severity.CRITICAL)


# ---------------------------------------------------------------------------
# Intent taxonomy (§6 — structured intent block)
# ---------------------------------------------------------------------------


class QuestionType(str, Enum):
    DEFINITIONAL = "definitional"
    PROCEDURAL = "procedural"
    COMPARATIVE = "comparative"
    CONDITIONAL = "conditional"
    RECOMMENDATION = "recommendation"
    CLARIFICATION_NEEDED = "clarification_needed"


class Complexity(str, Enum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class Domain(str, Enum):
    ROSTER = "roster"
    WAIVERS = "waivers"
    TRADES = "trades"
    STANDINGS = "standings"
    NEWS = "news"
    RULES = "rules"
    PROJECTIONS = "projections"
    MATCHUPS = "matchups"
    META = "meta"


class AnswerShape(str, Enum):
    NUMBER = "number"
    LIST = "list"
    TABLE = "table"
    EXPLANATION = "explanation"
    RECOMMENDATION = "recommendation"
    CLARIFICATION = "clarification"


class Intent(BaseModel):
    """The structured intent block. Required on every case."""

    model_config = ConfigDict(extra="forbid")

    question_type: QuestionType
    complexity: Complexity
    domain: Domain
    answer_shape: AnswerShape


# ---------------------------------------------------------------------------
# Conversation prefix (multi-turn / memory testing)
# ---------------------------------------------------------------------------


class PriorTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str


# ---------------------------------------------------------------------------
# Assertions (§6 — assertion vocabulary table)
# ---------------------------------------------------------------------------


class Expected(BaseModel):
    """Assertions checked after the agent runs.

    All fields optional. A case with no assertions passes trivially —
    runner emits a warning when that happens.
    """

    model_config = ConfigDict(extra="forbid")

    # Tool routing (intent eval)
    must_call_tools: list[str] = Field(default_factory=list)
    must_not_call_tools: list[str] = Field(default_factory=list)
    must_call_tools_in_order: list[str] = Field(default_factory=list)
    tool_call_args_contain: dict[str, dict] = Field(default_factory=dict)

    # Response content
    response_contains_any: list[str] = Field(default_factory=list)
    response_contains_all: list[str] = Field(default_factory=list)
    response_contains_none: list[str] = Field(default_factory=list)
    response_matches_regex: str | None = None

    # Clarification cases
    must_ask_clarification: bool = False
    clarification_must_mention_any: list[str] = Field(default_factory=list)

    # Cost / efficiency budgets
    max_tool_calls: int | None = None
    max_latency_ms: int | None = None
    max_cost_usd: float | None = None

    # Length bounds
    min_response_chars: int | None = None
    max_response_chars: int | None = None

    def is_empty(self) -> bool:
        """True when no assertion is set. Runner warns on these."""
        return self == Expected()


# ---------------------------------------------------------------------------
# Provenance — where this case came from
# ---------------------------------------------------------------------------


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["manual", "promoted", "generated"]
    source_trace_id: str | None = None
    source_chat_date: str | None = None
    generator_version: str | None = None
    flaky_at_generation: bool = False


# ---------------------------------------------------------------------------
# The case
# ---------------------------------------------------------------------------


class EvalCase(BaseModel):
    """One eval case. One YAML file maps to one of these."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, pattern=r"^[a-z0-9_]+$")
    description: str = Field(..., min_length=1)

    # Run mode. `live` (default) runs against the actual local DB; assertions
    # are restricted to behavior. `snapshot` runs against a frozen snapshot;
    # content-equality assertions become legal. See §4.
    mode: Mode = Mode.LIVE
    snapshot_id: str | None = None

    intent: Intent

    # The user's message. Use either `user_message` (single) or `phrasings`
    # (multiple paraphrasings — each runs as its own row).
    user_message: str | None = None
    phrasings: list[str] = Field(default_factory=list)

    # Multi-turn / memory
    conversation_prefix: list[PriorTurn] = Field(default_factory=list)

    # Flakiness detection — run each phrasing this many times
    repeat: int = Field(default=1, ge=1, le=10)

    expected: Expected = Field(default_factory=Expected)

    # Per-case severity overrides. Maps assertion name -> Severity.
    # Use sparingly — the defaults in ASSERTION_SEVERITY_DEFAULTS are correct
    # for most cases. Override only when this specific case genuinely needs it
    # (e.g. a latency-sensitive case where max_latency_ms should be critical).
    severity_overrides: dict[str, Severity] = Field(default_factory=dict)

    tags: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def _validate_message(self) -> "EvalCase":
        """Exactly one of user_message / phrasings must be set."""
        has_single = self.user_message is not None and self.user_message.strip()
        has_multi = bool(self.phrasings)
        if has_single and has_multi:
            raise ValueError(
                "Set either `user_message` OR `phrasings`, not both. "
                "If you have one phrasing, use `user_message`."
            )
        if not has_single and not has_multi:
            raise ValueError("Must set either `user_message` or `phrasings`.")
        return self

    @model_validator(mode="after")
    def _validate_mode_snapshot(self) -> "EvalCase":
        """`live` mode forbids snapshot_id; `snapshot` mode requires it."""
        if self.mode == Mode.LIVE and self.snapshot_id is not None:
            raise ValueError(
                f"Case '{self.id}' has mode=live but sets snapshot_id="
                f"'{self.snapshot_id}'. Remove snapshot_id or change mode to snapshot."
            )
        if self.mode == Mode.SNAPSHOT and not self.snapshot_id:
            raise ValueError(
                f"Case '{self.id}' has mode=snapshot but no snapshot_id. "
                f"Set snapshot_id to the snapshot directory name."
            )
        return self

    @model_validator(mode="after")
    def _validate_content_equality_only_in_snapshot(self) -> "EvalCase":
        """Content-equality assertions require frozen state — snapshot mode only.

        See §6 of the design doc. In live mode the underlying DB shifts as
        sync jobs run; asserting specific text against it produces flaky
        cases. Loose-OR'd `response_contains_any` is fine in live mode,
        but `response_contains_all` and `response_matches_regex` require
        a snapshot.
        """
        if self.mode == Mode.SNAPSHOT:
            return self
        violations = []
        if self.expected.response_contains_all:
            violations.append("response_contains_all")
        if self.expected.response_matches_regex is not None:
            violations.append("response_matches_regex")
        if violations:
            raise ValueError(
                f"Case '{self.id}' uses content-equality assertions "
                f"({', '.join(violations)}) but mode=live. "
                f"These assertions need frozen state — switch to "
                f"mode=snapshot with a snapshot_id, or use "
                f"response_contains_any with loose-OR'd terms instead."
            )
        return self

    @model_validator(mode="after")
    def _validate_clarification_alignment(self) -> "EvalCase":
        """A clarification_needed case must use clarification assertions."""
        is_clarif_intent = self.intent.question_type == QuestionType.CLARIFICATION_NEEDED
        uses_clarif_assertion = (
            self.expected.must_ask_clarification
            or bool(self.expected.clarification_must_mention_any)
        )
        if is_clarif_intent and not uses_clarif_assertion:
            raise ValueError(
                f"Case '{self.id}' has intent.question_type=clarification_needed "
                f"but no clarification assertion. Set must_ask_clarification: true "
                f"or clarification_must_mention_any."
            )
        if uses_clarif_assertion and not is_clarif_intent:
            raise ValueError(
                f"Case '{self.id}' uses clarification assertions but "
                f"intent.question_type is {self.intent.question_type.value}. "
                f"Set question_type to clarification_needed."
            )
        return self

    def all_messages(self) -> list[str]:
        """Iterator-friendly view of every user message this case will run.

        Returns [user_message] or phrasings.
        """
        if self.user_message:
            return [self.user_message]
        return list(self.phrasings)

    def total_run_count(self) -> int:
        """Number of agent invocations this case produces.

        len(messages) * repeat. Used by the runner for progress reporting and
        by the dashboard for pass-rate denominators.
        """
        return len(self.all_messages()) * self.repeat
