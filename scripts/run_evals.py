#!/usr/bin/env python3
"""CLI wrapper for the eval runner.

See backend/app/evals/runner/run.py for full usage. This script:
  1. Routes LangSmith traces to a separate project so eval runs don't
     pollute the prod chat traces. Must happen BEFORE any app.* import
     because env_bridge.py reads env vars at import time.
  2. Adds backend/ to sys.path so `app.*` imports resolve when run from
     the repo root.
  3. Delegates to app.evals.runner.run.main.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Step 1: route eval traces to their own LangSmith project.
# We use os.environ.__setitem__ (not setdefault) so we override whatever's
# in .env — eval runs MUST land in fantasy-copilot-evals, never prod.
os.environ["LANGSMITH_PROJECT"] = "fantasy-copilot-evals"
os.environ["LANGCHAIN_PROJECT"] = "fantasy-copilot-evals"

# Step 2: make `app.*` importable.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# Step 3: delegate.
from app.evals.runner.run import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
