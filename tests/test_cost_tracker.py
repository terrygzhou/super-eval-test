"""Tests for src.cost_tracker — per-task cost/latency capture."""

from __future__ import annotations

from src.cost_tracker import CostTracker


def test_cost_tracker_has_all_fields_after_record():
    tracker = CostTracker()
    rec = tracker.record_trial(
        task="create-project",
        n_trials=1,
        tokens_in=120,
        tokens_out=40,
        llm_calls=1,
        latency_s=12.5,
        tool_calls=5,
    )
    for key in (
        "task", "n_trials", "tokens_in", "tokens_out", "llm_calls",
        "latency_s", "tool_calls", "estimated_cost_usd",
    ):
        assert key in rec, f"missing cost field {key}"


def test_default_rate_table_is_not_priced():
    tracker = CostTracker()  # no rate table → 0 (instrumented, not priced)
    rec = tracker.record_trial(
        task="t", tokens_in=100, tokens_out=50, llm_calls=1,
        latency_s=1.0, tool_calls=2,
    )
    assert rec["estimated_cost_usd"] == 0.0


def test_rate_table_prices_cost():
    # rate: 1000 input tokens = $0.10, 1000 output tokens = $0.30
    tracker = CostTracker(rate_table={"per_1k_input_usd": 0.10, "per_1k_output_usd": 0.30})
    rec = tracker.record_trial(
        task="t", tokens_in=1000, tokens_out=1000, llm_calls=1,
        latency_s=1.0, tool_calls=1,
    )
    assert rec["estimated_cost_usd"] == 0.40


def test_run_totals_aggregate():
    tracker = CostTracker(rate_table={"per_1k_input_usd": 0.1, "per_1k_output_usd": 0.3})
    for _ in range(3):
        tracker.record_trial(task="t", tokens_in=100, tokens_out=100, llm_calls=1,
                             latency_s=2.0, tool_calls=1)
    totals = tracker.run_totals()
    assert totals["tokens_in"] == 300
    assert totals["tokens_out"] == 300
    assert totals["llm_calls"] == 3
    assert totals["tool_calls"] == 3
    # 3 * (100/1000*0.1 + 100/1000*0.3) = 3 * 0.04 = 0.12
    assert totals["estimated_cost_usd"] == 0.12
    assert set(totals["per_task"]) == {"t"}


def test_cost_json_structure():
    tracker = CostTracker()
    tracker.record_trial(task="a", tokens_in=1, tokens_out=1, llm_calls=0,
                         latency_s=0.1, tool_calls=0)
    out = tracker.to_cost_json()
    # One artifact carries cost: has per-task entries + run totals
    assert "per_task" in out and "totals" in out
    assert "a" in out["per_task"]


def test_scripted_trial_reports_zero_llm_traffic():
    tracker = CostTracker()
    rec = tracker.record_trial(
        task="scripted", tokens_in=0, tokens_out=0, llm_calls=0,
        latency_s=1.0, tool_calls=3,
    )
    assert rec["llm_calls"] == 0
    assert rec["tokens_in"] == 0
