"""Mirror Settings (which reads backend/.env) into os.environ.

Required because:
- `langchain-anthropic` reads ANTHROPIC_API_KEY from os.environ.
- `langsmith` reads LANGSMITH_API_KEY / LANGSMITH_TRACING / LANGSMITH_PROJECT
  from os.environ.

Pydantic-settings only populates the `Settings` object, not the process env,
so without this bridge the third-party libraries don't see the values.

Import this module BEFORE importing anything from `deepagents` /
`langchain-anthropic` / `langsmith`.
"""

import os

from app.config import get_settings

_s = get_settings()

if _s.anthropic_api_key:
    os.environ.setdefault("ANTHROPIC_API_KEY", _s.anthropic_api_key)

if _s.langsmith_api_key:
    os.environ.setdefault("LANGSMITH_API_KEY", _s.langsmith_api_key)
    os.environ.setdefault("LANGCHAIN_API_KEY", _s.langsmith_api_key)  # legacy alias
    os.environ.setdefault("LANGSMITH_TRACING", "true" if _s.langsmith_tracing else "false")
    os.environ.setdefault(
        "LANGCHAIN_TRACING_V2", "true" if _s.langsmith_tracing else "false"
    )
    os.environ.setdefault("LANGSMITH_PROJECT", _s.langsmith_project)
    os.environ.setdefault("LANGCHAIN_PROJECT", _s.langsmith_project)
