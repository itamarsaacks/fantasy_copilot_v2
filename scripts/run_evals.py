#!/usr/bin/env python3
"""CLI wrapper for the eval runner.

Routes LangSmith traces to a separate project so eval runs don't
pollute prod chat traces, then delegates to app.evals.runner.run.main.

Note: app.config calls load_dotenv(override=True) at import time, which
overwrites any pre-set LANGSMITH_PROJECT. So we set the env AFTER the
app modules have loaded — LangChain reads the env at trace-emit time,
not at import time, so this is the correct override point.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.evals.runner.run import main  # noqa: E402

# Override AFTER imports — load_dotenv(override=True) in app.config would
# clobber a pre-import value. This is the value LangChain reads when it
# actually emits traces.
os.environ["LANGSMITH_PROJECT"] = "fantasy-copilot-evals"
os.environ["LANGCHAIN_PROJECT"] = "fantasy-copilot-evals"

if __name__ == "__main__":
    sys.exit(main())
