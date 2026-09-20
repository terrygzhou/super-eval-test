"""Cost / latency capture — a first-class per-task metric for gate runs.

In gate mode the deterministic runner is LLM-free, so the only LLM traffic that
can be captured is from any LLM-judge graders enabled on a task. This tracker
records tokens in/out, LLM call count, wall-clock latency, and tool-call count
per task and across the run, plus an estimated cost from a configurable rate
table. A rate table of ``None`` (the default) means "instrumented, not priced"
— every cost field reports 0.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _estimate_cost_usd(tokens_in: int, tokens_out: int, rate_table: dict[str, Any] | None) -> float:
    """Cost in USD from a rate table.

    Rate table keys (all optional):
      - per_1k_input_usd:  USD per 1000 input tokens
      - per_1k_output_usd: USD per 1000 output tokens

    A None / empty table yields 0.0 (instrumented, not priced).
    """
    if not rate_table:
        return 0.0
    per_in = float(rate_table.get("per_1k_input_usd", 0.0))
    per_out = float(rate_table.get("per_1k_output_usd", 0.0))
    return (tokens_in / 1000.0) * per_in + (tokens_out / 1000.0) * per_out


@dataclass
class CostTracker:
    """Accumulate per-task cost/latency metrics for a single gate run."""

    rate_table: dict[str, Any] | None = None
    _records: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def record_trial(
        self,
        task: str,
        *,
        n_trials: int = 1,
        tokens_in: int = 0,
        tokens_out: int = 0,
        llm_calls: int = 0,
        latency_s: float = 0.0,
        tool_calls: int = 0,
    ) -> dict[str, Any]:
        """Record one task's cost/latency snapshot and return it.

        ``tokens_in`` / ``tokens_out`` are summed over the task's N trials;
        ``llm_calls`` likewise. ``tool_calls`` is the runner step count.
        """
        record = {
            "task": task,
            "n_trials": n_trials,
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
            "llm_calls": int(llm_calls),
            "latency_s": float(latency_s),
            "tool_calls": int(tool_calls),
            "estimated_cost_usd": round(
                _estimate_cost_usd(tokens_in, tokens_out, self.rate_table), 6,
            ),
        }
        self._records.append(record)
        return record

    def per_task(self) -> dict[str, dict[str, Any]]:
        """Map of task name → its cost record (last write wins)."""
        out: dict[str, dict[str, Any]] = {}
        for rec in self._records:
            out[rec["task"]] = rec
        return out

    def run_totals(self) -> dict[str, Any]:
        """Aggregate cost/latency across the whole run."""
        totals = {
            "tokens_in": 0,
            "tokens_out": 0,
            "llm_calls": 0,
            "tool_calls": 0,
            "latency_s": 0.0,
            "estimated_cost_usd": 0.0,
        }
        for rec in self._records:
            totals["tokens_in"] += rec["tokens_in"]
            totals["tokens_out"] += rec["tokens_out"]
            totals["llm_calls"] += rec["llm_calls"]
            totals["tool_calls"] += rec["tool_calls"]
            totals["latency_s"] += rec["latency_s"]
            totals["estimated_cost_usd"] += rec["estimated_cost_usd"]
        totals["per_task"] = self.per_task()
        totals["estimated_cost_usd"] = round(totals["estimated_cost_usd"], 6)
        return totals

    def to_cost_json(self) -> dict[str, Any]:
        """The ``cost.json`` artifact: per-task entries + run totals."""
        return {
            "rate_table": self.rate_table,
            "per_task": self.per_task(),
            "totals": self.run_totals(),
        }
