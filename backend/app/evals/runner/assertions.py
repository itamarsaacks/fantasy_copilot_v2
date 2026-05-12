"""Assertion evaluation.

Each function returns a list of AssertionFailure — empty means the assertion
passed. The runner collects all failures across all assertions for a single
PhrasingRun and the run passes iff the list stays empty.

The 13 assertion types in docs/EVAL_HARNESS.md §6 are implemented here. Some
(content-equality, clarification) are restricted by mode in the schema; this
module assumes the schema already validated those constraints.
"""

from __future__ import annotations

import re

from app.evals.runner.result import AssertionFailure, ToolCallTrace
from app.evals.schema import Expected, Severity, assertion_severity


def check_all(
    expected: Expected,
    *,
    tool_calls: list[ToolCallTrace],
    final_response: str,
    latency_ms: int,
    cost_usd: float | None = None,
    severity_overrides: dict[str, Severity] | None = None,
) -> list[AssertionFailure]:
    """Run every applicable assertion. Return failures (empty = pass).

    Each failure carries a severity (critical or warning) used by the runner
    to compute the PhrasingRun verdict. Severities come from the case's
    `severity_overrides` if set, otherwise from ASSERTION_SEVERITY_DEFAULTS.
    """

    def sev(name: str) -> Severity:
        return assertion_severity(name, severity_overrides)

    failures: list[AssertionFailure] = []
    tool_names = [tc.name for tc in tool_calls]
    response_lower = final_response.lower()

    # --- Tool routing --------------------------------------------------------

    if expected.must_call_tools:
        missing = [t for t in expected.must_call_tools if t not in tool_names]
        if missing:
            failures.append(
                AssertionFailure(
                    assertion="must_call_tools",
                    severity=sev("must_call_tools"),
                    expected=expected.must_call_tools,
                    actual=tool_names,
                    detail=f"missing tool(s): {missing}",
                )
            )

    if expected.must_not_call_tools:
        forbidden = [t for t in expected.must_not_call_tools if t in tool_names]
        if forbidden:
            failures.append(
                AssertionFailure(
                    assertion="must_not_call_tools",
                    severity=sev("must_not_call_tools"),
                    expected=f"none of {expected.must_not_call_tools}",
                    actual=tool_names,
                    detail=f"forbidden tool(s) were called: {forbidden}",
                )
            )

    if expected.must_call_tools_in_order:
        # Check the required tools appear in the trace in the given order.
        # Other tools may appear between them.
        idx = 0
        for name in tool_names:
            if idx < len(expected.must_call_tools_in_order) and name == expected.must_call_tools_in_order[idx]:
                idx += 1
        if idx < len(expected.must_call_tools_in_order):
            failures.append(
                AssertionFailure(
                    assertion="must_call_tools_in_order",
                    severity=sev("must_call_tools_in_order"),
                    expected=expected.must_call_tools_in_order,
                    actual=tool_names,
                    detail=f"order broken at step {idx} ('{expected.must_call_tools_in_order[idx]}')",
                )
            )

    if expected.tool_call_args_contain:
        for tool_name, required_args in expected.tool_call_args_contain.items():
            matching_calls = [tc for tc in tool_calls if tc.name == tool_name]
            if not matching_calls:
                failures.append(
                    AssertionFailure(
                        assertion="tool_call_args_contain",
                        severity=sev("tool_call_args_contain"),
                        expected={tool_name: required_args},
                        actual=tool_names,
                        detail=f"no call to {tool_name} found",
                    )
                )
                continue
            # At least one call to this tool must contain ALL required args.
            ok = any(
                all(tc.args.get(k) == v for k, v in required_args.items())
                for tc in matching_calls
            )
            if not ok:
                failures.append(
                    AssertionFailure(
                        assertion="tool_call_args_contain",
                        severity=sev("tool_call_args_contain"),
                        expected={tool_name: required_args},
                        actual=[tc.args for tc in matching_calls],
                        detail=f"no {tool_name} call matched required args",
                    )
                )

    # --- Response content ---------------------------------------------------

    if expected.response_contains_any:
        hit = any(s.lower() in response_lower for s in expected.response_contains_any)
        if not hit:
            failures.append(
                AssertionFailure(
                    assertion="response_contains_any",
                    severity=sev("response_contains_any"),
                    expected=expected.response_contains_any,
                    actual=final_response[:200],
                    detail="none of the expected phrases appeared",
                )
            )

    if expected.response_contains_all:
        missing = [s for s in expected.response_contains_all if s.lower() not in response_lower]
        if missing:
            failures.append(
                AssertionFailure(
                    assertion="response_contains_all",
                    severity=sev("response_contains_all"),
                    expected=expected.response_contains_all,
                    actual=final_response[:200],
                    detail=f"missing phrase(s): {missing}",
                )
            )

    if expected.response_contains_none:
        present = [s for s in expected.response_contains_none if s.lower() in response_lower]
        if present:
            failures.append(
                AssertionFailure(
                    assertion="response_contains_none",
                    severity=sev("response_contains_none"),
                    expected=f"none of {expected.response_contains_none}",
                    actual=final_response[:200],
                    detail=f"forbidden phrase(s) appeared: {present}",
                )
            )

    if expected.response_matches_regex:
        if not re.search(expected.response_matches_regex, final_response):
            failures.append(
                AssertionFailure(
                    assertion="response_matches_regex",
                    severity=sev("response_matches_regex"),
                    expected=expected.response_matches_regex,
                    actual=final_response[:200],
                    detail="regex did not match",
                )
            )

    # --- Clarification ------------------------------------------------------

    if expected.must_ask_clarification:
        # Heuristic: a clarifying response usually ends with `?` and didn't
        # call any tool. Strict: zero tool calls AND response ends with `?`.
        looks_like_clarif = response_lower.rstrip().endswith("?") and len(tool_calls) == 0
        if not looks_like_clarif:
            failures.append(
                AssertionFailure(
                    assertion="must_ask_clarification",
                    severity=sev("must_ask_clarification"),
                    expected="agent should ask a clarifying question (no tool calls, response ends with '?')",
                    actual=f"tool_calls={len(tool_calls)}, ends_with_q={response_lower.rstrip().endswith('?')}",
                    detail="agent did not ask for clarification",
                )
            )

    if expected.clarification_must_mention_any:
        hit = any(s.lower() in response_lower for s in expected.clarification_must_mention_any)
        if not hit:
            failures.append(
                AssertionFailure(
                    assertion="clarification_must_mention_any",
                    severity=sev("clarification_must_mention_any"),
                    expected=expected.clarification_must_mention_any,
                    actual=final_response[:200],
                    detail="clarification didn't reference any expected phrase",
                )
            )

    # --- Cost / efficiency budgets -----------------------------------------

    if expected.max_tool_calls is not None and len(tool_calls) > expected.max_tool_calls:
        failures.append(
            AssertionFailure(
                assertion="max_tool_calls",
                severity=sev("max_tool_calls"),
                expected=f"<= {expected.max_tool_calls}",
                actual=len(tool_calls),
                detail=f"agent made {len(tool_calls)} tool calls",
            )
        )

    if expected.max_latency_ms is not None and latency_ms > expected.max_latency_ms:
        failures.append(
            AssertionFailure(
                assertion="max_latency_ms",
                severity=sev("max_latency_ms"),
                expected=f"<= {expected.max_latency_ms}ms",
                actual=f"{latency_ms}ms",
                detail=f"agent took {latency_ms}ms (budget {expected.max_latency_ms}ms)",
            )
        )

    if expected.max_cost_usd is not None and cost_usd is not None and cost_usd > expected.max_cost_usd:
        failures.append(
            AssertionFailure(
                assertion="max_cost_usd",
                severity=sev("max_cost_usd"),
                expected=f"<= ${expected.max_cost_usd:.4f}",
                actual=f"${cost_usd:.4f}",
                detail="cost exceeded budget",
            )
        )

    # --- Length bounds ------------------------------------------------------

    response_len = len(final_response)
    if expected.min_response_chars is not None and response_len < expected.min_response_chars:
        failures.append(
            AssertionFailure(
                assertion="min_response_chars",
                severity=sev("min_response_chars"),
                expected=f">= {expected.min_response_chars}",
                actual=response_len,
                detail=f"response was {response_len} chars",
            )
        )

    if expected.max_response_chars is not None and response_len > expected.max_response_chars:
        failures.append(
            AssertionFailure(
                assertion="max_response_chars",
                severity=sev("max_response_chars"),
                expected=f"<= {expected.max_response_chars}",
                actual=response_len,
                detail=f"response was {response_len} chars",
            )
        )

    return failures
