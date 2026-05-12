#!/usr/bin/env python3
"""Pretty-print a LangSmith trace from the terminal.

Two ways to call it:

  python scripts/inspect_trace.py <trace_uuid>
  python scripts/inspect_trace.py --case-result <id>   # look up trace_id in DB

Prints, in order:
  - case + phrasing + verdict (if --case-result)
  - user message
  - every tool call with args and a short snippet of the output
  - the final assistant response
  - latency / errors / LangSmith URL

Read-only. Safe to run any time.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agent import env_bridge  # noqa: F401, E402  — populates LANGSMITH_* env
from app.config import get_settings  # noqa: E402


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _hr(title: str = "") -> None:
    if title:
        print(f"\n── {title} " + "─" * max(0, 75 - len(title)))
    else:
        print("─" * 80)


def _short(s: str, limit: int = 400) -> str:
    s = s.replace("\n", " ").strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _wrap(s: str, indent: str = "  ") -> str:
    return textwrap.indent(textwrap.fill(s, 100), indent)


# ---------------------------------------------------------------------------
# DB lookup (when --case-result is passed)
# ---------------------------------------------------------------------------


def _sync_dsn() -> str:
    url = get_settings().database_url
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


def lookup_case_result(case_result_id: int) -> dict:
    import psycopg

    with psycopg.connect(_sync_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT case_id, phrasing, verdict, errored, error_message,
                   langsmith_trace_id, langsmith_trace_url,
                   final_response, failure_reasons, latency_ms,
                   intent_question_type, intent_complexity, intent_domain
            FROM eval_case_results
            WHERE id = %s
            """,
            (case_result_id,),
        )
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"No eval_case_results row with id={case_result_id}")
        keys = [
            "case_id", "phrasing", "verdict", "errored", "error_message",
            "trace_id", "trace_url", "final_response", "failure_reasons",
            "latency_ms", "qtype", "complexity", "domain",
        ]
        return dict(zip(keys, row))


# ---------------------------------------------------------------------------
# LangSmith fetch + render
# ---------------------------------------------------------------------------


def fetch_trace(trace_id: str) -> tuple:
    """Return (root_run, ordered_child_runs). Probes a couple of projects."""
    from langsmith import Client

    client = Client()
    settings = get_settings()
    # Where to look. Order matters — first hit wins.
    projects = [
        settings.langsmith_project,
        "fantasy-copilot-evals",
        "fantasy-copilot-v2",
    ]
    seen = set()
    root = None
    for proj in projects:
        if proj in seen:
            continue
        seen.add(proj)
        try:
            root = client.read_run(trace_id)
            break
        except Exception:
            continue
    if root is None:
        raise SystemExit(f"Could not fetch trace {trace_id} from LangSmith.")

    # children — sorted by start_time so the timeline reads naturally
    children = list(
        client.list_runs(project_ids=[root.session_id], trace_id=root.trace_id)
    )
    children.sort(key=lambda r: r.start_time or root.start_time)
    return root, children


def render(root, children, *, db_meta: dict | None) -> None:
    _hr("Case + verdict")
    if db_meta:
        print(f"  case_id : {db_meta['case_id']}")
        print(f"  intent  : {db_meta.get('qtype')} / {db_meta.get('complexity')} / {db_meta.get('domain')}")
        v = db_meta["verdict"]
        icon = {"pass": "🟢", "soft_pass": "🟡", "fail": "🔴"}.get(v, "💥")
        print(f"  verdict : {icon} {v.upper()}{'  (errored)' if db_meta['errored'] else ''}")
        if db_meta["error_message"]:
            print(f"  error   : {_short(db_meta['error_message'], 200)}")
        if db_meta["failure_reasons"]:
            print("  failure_reasons:")
            for f in db_meta["failure_reasons"]:
                sev = f.get("severity", "?")
                print(f"    - [{sev}] {f.get('assertion')}: {_short(str(f.get('detail', '')), 150)}")
    print(f"  trace   : {root.id}")
    print(f"  latency : {(root.end_time - root.start_time).total_seconds() * 1000:.0f}ms" if root.end_time else "  latency : (unfinished)")
    if root.error:
        print(f"  ROOT ERROR: {_short(root.error, 200)}")

    # ---- user message ----
    _hr("User message")
    msgs = (root.inputs or {}).get("messages") or []
    if db_meta and db_meta.get("phrasing"):
        print(f'  "{db_meta["phrasing"]}"')
    else:
        for m in msgs:
            if isinstance(m, dict) and m.get("role") == "user":
                print(_wrap(_short(m.get("content", ""), 500)))
                break

    # ---- tool calls (in order) ----
    _hr("Tool calls (in order)")
    tool_runs = [r for r in children if r.run_type == "tool"]
    if not tool_runs:
        print("  (no tool calls)")
    for i, r in enumerate(tool_runs, 1):
        args = r.inputs or {}
        # tool inputs are usually {"args": {...}} or just kwargs
        args_str = _short(json.dumps(args, default=str), 200)
        out = ""
        if r.outputs:
            out = _short(json.dumps(r.outputs, default=str), 400)
        err = f"  ERROR: {_short(r.error, 200)}" if r.error else ""
        dur = (r.end_time - r.start_time).total_seconds() * 1000 if r.end_time else 0
        print(f"\n  [{i}] {r.name}  ({dur:.0f}ms)")
        print(f"      args: {args_str}")
        if out:
            print(f"      out : {out}")
        if err:
            print(err)

    # ---- final response ----
    _hr("Final assistant response")
    text = None
    if db_meta and db_meta.get("final_response"):
        text = db_meta["final_response"]
    elif root.outputs:
        # walk the output structure
        out = root.outputs
        if isinstance(out, dict) and "messages" in out:
            for m in reversed(out["messages"]):
                if isinstance(m, dict) and m.get("role") in (None, "assistant", "ai"):
                    text = m.get("content") or ""
                    if text:
                        break
        if not text:
            text = json.dumps(out, default=str)
    if text:
        print(_wrap(_short(text, 1500)))
    else:
        print("  (no final response captured)")

    # ---- URL ----
    _hr("Open in LangSmith")
    print(f"  https://smith.langchain.com/o/-/r/{root.id}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("trace_id", nargs="?", help="LangSmith run/trace UUID")
    p.add_argument("--case-result", type=int, help="Look up trace_id from eval_case_results.id")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    db_meta = None
    trace_id = args.trace_id
    if args.case_result:
        db_meta = lookup_case_result(args.case_result)
        trace_id = db_meta["trace_id"]
        if not trace_id:
            raise SystemExit(f"case_result id={args.case_result} has no langsmith_trace_id")
    if not trace_id:
        raise SystemExit("Pass a trace UUID or --case-result <id>.")

    root, children = fetch_trace(trace_id)
    render(root, children, db_meta=db_meta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
