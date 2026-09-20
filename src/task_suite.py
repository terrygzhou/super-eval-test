"""Task suite — load and validate the curated, versioned task files for gate runs.

A task is *data, not code*: a fixed input set + form reference + optional
graders/cost limits. Tasks never generate their own inputs — that is what makes
gate runs comparable across model/prompt changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class TaskSuiteError(Exception):
    """Raised when a task file (or the suite) is malformed."""


@dataclass
class Task:
    """A single curated gate task."""

    name: str
    form: str
    data: dict[str, Any]
    description: str = ""
    graders: list[dict[str, Any]] = field(default_factory=list)
    cost_limits: dict[str, Any] | None = None
    path: str = ""


def _coerce_task(raw: dict[str, Any], path: str) -> Task:
    if not isinstance(raw, dict):
        raise TaskSuiteError(f"{path}: task file must contain a mapping")

    name = raw.get("name")
    form = raw.get("form")
    data = raw.get("data")

    if not name:
        raise TaskSuiteError(f"{path}: task is missing required field 'name'")
    if not form:
        raise TaskSuiteError(f"{path}: task is missing required field 'form'")
    if not isinstance(data, dict) or not data:
        raise TaskSuiteError(f"{path}: task is missing a non-empty 'data' mapping (fixed inputs)")

    graders = raw.get("graders", [])
    if not isinstance(graders, list):
        raise TaskSuiteError(f"{path}: 'graders' must be a list")

    cost_limits = raw.get("cost_limits")
    if cost_limits is not None and not isinstance(cost_limits, dict):
        raise TaskSuiteError(f"{path}: 'cost_limits' must be a mapping")

    # A task must not declare itself as a data generator.
    if raw.get("generate") is True:
        raise TaskSuiteError(f"{path}: tasks are data, not generators — remove 'generate'")

    return Task(
        name=str(name),
        form=str(form),
        data=data,
        description=str(raw.get("description", "")),
        graders=graders,
        cost_limits=cost_limits,
        path=path,
    )


def load_task(path: str) -> Task:
    """Load and validate a single task YAML file."""
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TaskSuiteError(f"{path}: unparseable YAML: {exc}") from exc
    return _coerce_task(raw, str(p))


def load_suite(suite_dir: str) -> list[Task]:
    """Load every ``*.yaml`` task in a suite directory (sorted, deterministic).

    Raises TaskSuiteError when the directory is missing or contains no task
    files, or when any file is malformed.
    """
    root = Path(suite_dir)
    if not root.is_dir():
        raise TaskSuiteError(f"suite directory not found: {suite_dir}")
    files = sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml"))
    if not files:
        raise TaskSuiteError(f"no task files (*.yaml) in suite directory: {suite_dir}")
    return [load_task(str(f)) for f in files]
