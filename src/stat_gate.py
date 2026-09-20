"""Statistical regression gate — Wilson confidence intervals + baseline compare.

Pure, LLM-free, and dependency-free (stdlib only). This is the "evaluation"
layer that the deterministic 4-phase pipeline was missing: per-task success
rate over N trials, a 95% Wilson CI for that rate, and a baseline compare that
gates only on *significant* regression (interval non-overlap), never
single-run noise.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class BaselineError(Exception):
    """Raised when a baseline file is missing a required field, is corrupt, or
    has drifted schema relative to what the gate expects."""


_Z_DEFAULT = 1.96


def trial_success_rate(n_passed: int, n_trials: int) -> float:
    """Per-task success rate = fraction of trials that passed.

    An n_trials of 0 is a defensive guard and yields 0.0 (no data, no signal).
    """
    if n_trials <= 0:
        return 0.0
    return n_passed / n_trials


def wilson_ci(p: float, n: int, z: float = _Z_DEFAULT) -> tuple[float, float]:
    """Wilson score interval for a success rate p observed over n trials.

    Handles small n better than the normal approximation and stays finite at
    p = 0 and p = 1 (where the normal approximation is degenerate).
    """
    if n <= 0:
        return (0.0, 0.0)
    p = min(max(p, 0.0), 1.0)
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = (z / denom) * ((p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5)
    low = max(0.0, centre - half)
    high = min(1.0, centre + half)
    return (low, high)


def _entry_ci(entry: dict[str, Any]) -> tuple[float, float]:
    """Pull the CI (low, high) out of a report/baseline task entry.

    Accepts either an explicit "ci": [low, high] or the "rate" + "n_trials"
    from which the CI can be recomputed.
    """
    ci = entry.get("ci")
    if ci is not None:
        return (float(ci[0]), float(ci[1]))
    rate = float(entry.get("rate", 0.0))
    n = int(entry.get("n_trials", 0))
    return wilson_ci(rate, n)


def compare_to_baseline(
    current: dict[str, dict[str, Any]],
    baseline: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    """Compare a current per-task report to a stored baseline.

    Per-task verdict:
      - "regressed": current CI lower bound >= baseline rate (significant drop;
        the current interval sits clearly below the baseline point estimate)
      - "improved":  current CI upper bound <= baseline rate (significant rise)
      - "unchanged": intervals/point estimates overlap (single-run noise)

    Overall verdict:
      - "ESTABLISHED" when there is no baseline (first run)
      - "FAIL" if any task regressed
      - "PASS" otherwise
    """
    if baseline is None:
        return {"established": True, "overall": "ESTABLISHED", "tasks": {}}

    tasks: dict[str, Any] = {}
    overall = "PASS"
    for name, cur in current.items():
        base = baseline.get(name)
        if base is None:
            # New task not present in baseline: treat as established for it.
            tasks[name] = {"verdict": "established", "current": _entry_ci(cur)}
            continue
        cur_ci = _entry_ci(cur)
        cur_rate = float(cur.get("rate", 0.0))
        base_rate = float(base.get("rate", 0.0))
        base_ci = _entry_ci(base)

        cur_low, cur_high = cur_ci
        base_low, base_high = base_ci

        # Compare CIs (not raw rates): with small N the observed rate collapses
        # to 0 or 1, so the interval bounds are the meaningful signal. A task
        # has *significantly* regressed when the current interval sits entirely
        # below the baseline interval, and *improved* symmetrically.
        if cur_high < base_low:
            verdict = "regressed"
        elif cur_low > base_high:
            verdict = "improved"
        else:
            verdict = "unchanged"

        tasks[name] = {
            "verdict": verdict,
            "rate": cur_rate,
            "ci": list(cur_ci),
            "baseline_rate": base_rate,
            "baseline_ci": list(base_ci),
        }
        if verdict == "regressed":
            overall = "FAIL"

    return {"established": False, "overall": overall, "tasks": tasks}


def save_baseline(report: dict[str, Any], path: str) -> str:
    """Persist a gate report as a baseline (JSON) and return the path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return str(p)


def load_baseline(path: str) -> dict[str, Any] | None:
    """Load a prior gate report as a baseline.

    Returns None when the file does not exist (→ establish baseline). Raises
    BaselineError when the file exists but is corrupt or schema-mismatched.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BaselineError(f"baseline {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BaselineError(f"baseline {p} must be a JSON object")
    # A valid gate report carries a "tasks" mapping.
    if "tasks" not in data:
        raise BaselineError(f"baseline {p} is missing the 'tasks' key (schema drift)")
    return data
