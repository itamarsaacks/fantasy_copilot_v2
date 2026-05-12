"""Load eval cases from YAML files on disk.

Two entry points:
  - load_case(path) — load one file
  - discover_cases(root) — walk a directory tree, load every .yaml/.yml

The loader validates against the Pydantic schema. Any malformed case raises,
and the runner reports it as an `errored` result rather than silently skipping.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.evals.schema import EvalCase  # noqa: E402  (resolved via package install)


class CaseLoadError(Exception):
    """Raised when a case file is malformed or fails schema validation."""

    def __init__(self, path: Path, original: Exception):
        self.path = path
        self.original = original
        super().__init__(f"Failed to load case at {path}: {original}")


def load_case(path: Path) -> EvalCase:
    """Load a single case YAML file."""
    try:
        with path.open() as f:
            raw = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise CaseLoadError(path, e) from e

    if not isinstance(raw, dict):
        raise CaseLoadError(
            path, ValueError(f"Top-level YAML must be a mapping, got {type(raw).__name__}")
        )

    try:
        return EvalCase(**raw)
    except ValidationError as e:
        raise CaseLoadError(path, e) from e


def discover_cases(root: Path) -> tuple[list[EvalCase], list[CaseLoadError]]:
    """Recursively load every .yaml/.yml under root.

    Returns (cases, errors). The runner reports errors as `errored` results
    so a single broken file doesn't kill the whole run.
    """
    cases: list[EvalCase] = []
    errors: list[CaseLoadError] = []
    for path in sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml")):
        try:
            cases.append(load_case(path))
        except CaseLoadError as e:
            errors.append(e)
    return cases, errors
