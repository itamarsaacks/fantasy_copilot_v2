"""Invoke the real agent for one PhrasingRun, capture tool calls + response.

Uses the existing app.db.engine and the app's checkpointer. The runner is
responsible for starting/stopping the checkpointer around the batch of
invocations. LangSmith traces are routed to the `fantasy-copilot-evals`
project by env vars set in scripts/run_evals.py before any imports.

We pre-generate the LangSmith run_id per invocation so we can record the
trace URL deterministically in the result row.
"""

from __future__ import annotations

import time
import uuid

from app.evals.runner.result import PhrasingRun, ToolCallTrace


def _trace_url(run_id: uuid.UUID) -> str:
    """LangSmith resolves '/o/-/r/{id}' to the user's default org. Works for
    any logged-in user without us needing to know the org UUID.
    """
    return f"https://smith.langchain.com/o/-/r/{run_id}"


def _stringify_tool_output(content) -> str:
    """LangChain tool messages return varied content shapes. Stringify to ≤200 chars."""
    if content is None:
        return ""
    s = str(content)
    return s if len(s) <= 200 else s[:200] + "..."


def _extract_trace(state) -> tuple[list[ToolCallTrace], str]:
    """Walk the LangGraph state messages and pull out:
      - every tool call made during this invocation (with args + output preview)
      - the final assistant text response

    LangGraph returns the full message history (including prior turns if a
    thread had any). We rely on the runner using a fresh thread_id per call,
    so the entire trace IS this invocation.
    """
    messages = state.get("messages", []) if isinstance(state, dict) else []
    tool_calls: list[ToolCallTrace] = []
    # Build a map: tool_call_id -> output preview (filled from ToolMessage rows)
    tool_outputs: dict[str, str] = {}
    final_text = ""

    # First pass: collect tool message outputs by tool_call_id
    for m in messages:
        m_type = (getattr(m, "type", "") or m.__class__.__name__).lower()
        if "tool" in m_type:
            tc_id = getattr(m, "tool_call_id", None)
            if tc_id:
                tool_outputs[tc_id] = _stringify_tool_output(getattr(m, "content", ""))

    # Second pass: collect AIMessage.tool_calls AND final text
    for m in messages:
        m_type = (getattr(m, "type", "") or m.__class__.__name__).lower()
        if "ai" in m_type or "assistant" in m_type:
            for tc in getattr(m, "tool_calls", []) or []:
                # AIMessage.tool_calls items can be dicts or pydantic objects
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
                tool_calls.append(
                    ToolCallTrace(
                        name=name or "",
                        args=args or {},
                        output_preview=tool_outputs.get(tc_id, ""),
                    )
                )
            # The LAST AI message without tool_calls is the final response
            if not (getattr(m, "tool_calls", None) or []):
                content = getattr(m, "content", "")
                if isinstance(content, list):
                    # Some Anthropic responses arrive as list-of-blocks
                    content = "".join(
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in content
                    )
                if content:
                    final_text = content

    return tool_calls, final_text


async def invoke(
    *,
    user_message: str,
    user_id: int,
    league_id: int,
    scoring_type: str,
    case_id: str,
    phrasing_index: int,
    repeat_index: int,
    conversation_prefix: list[dict[str, str]] | None = None,
) -> PhrasingRun:
    """Run the agent once. Returns a PhrasingRun with raw observations.

    `conversation_prefix` is a list of {"role": "user"|"assistant", "content": str}
    turns that get prepended before `user_message` — required for any
    multi-turn case (pronoun resolution, "and second?", etc.). The runner
    builds it from case.conversation_prefix.

    Assertion evaluation happens AFTER this returns — in run.py.
    Errors during invocation are caught and reported via errored=True.
    """
    # Imports are deferred so the runner can override env vars before
    # any app.* code reads them (matters for snapshot mode, Phase E4).
    from app.agent.agent import get_agent

    thread_id = f"eval_{case_id}_{phrasing_index}_{repeat_index}_{uuid.uuid4().hex[:8]}"
    # Pre-generate the LangSmith trace ID. LangChain's RunnableConfig.run_id
    # propagates to LangSmith as the root run UUID — so we know the trace URL
    # before the call even starts.
    trace_id = uuid.uuid4()
    config = {
        "configurable": {
            "user_id": user_id,
            "league_id": league_id,
            "thread_id": thread_id,
        },
        "run_id": trace_id,
    }

    pr = PhrasingRun(
        case_id=case_id,
        phrasing=user_message,
        repeat_index=repeat_index,
        agent_thread_id=thread_id,
        langsmith_trace_id=str(trace_id),
        langsmith_trace_url=_trace_url(trace_id),
        langsmith_thread_id=thread_id,  # we use the same id for both
    )

    # Compose the full message history: prior turns from the case's
    # conversation_prefix (if any) + the current user phrasing.
    messages: list[dict[str, str]] = []
    if conversation_prefix:
        messages.extend(conversation_prefix)
    messages.append({"role": "user", "content": user_message})

    started = time.perf_counter()
    try:
        agent = get_agent(scoring_type)
        state = await agent.ainvoke(
            {"messages": messages},
            config=config,
        )
        tool_calls, final_text = _extract_trace(state)
        pr.tool_calls = tool_calls
        pr.final_response = final_text
    except Exception as e:  # noqa: BLE001
        pr.errored = True
        pr.error_message = f"{type(e).__name__}: {e}"
    finally:
        pr.latency_ms = int((time.perf_counter() - started) * 1000)

    return pr
