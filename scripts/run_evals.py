#!/usr/bin/env python3
"""CLI wrapper for the eval runner.

See backend/app/evals/runner/run.py for full usage. This script just sets
up the Python path and delegates.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add backend/ to sys.path so `app.*` imports resolve when run from repo root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.evals.runner.run import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
