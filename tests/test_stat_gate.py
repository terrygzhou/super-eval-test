"""Tests for src.stat_gate — Wilson CI, success rates, baseline compare/persist.

Contract (see design D3): compare_to_baseline operates on *task-entry maps*
(`{task_name: entry}`), where each entry carries at least "rate" and either
"ci" or "n_trials".
"""

from __future__ import annotations

import math

import pytest

from src import stat_gate


def _entry(rate, ci, n=7):
    return {"rate": rate, "ci": ci, "n_trials": n}


# --- 1.1 Wilson CI + success rate -------------------------------------------------

def test_trial_success_rate():
    assert stat_gate.trial_success_rate(0, 7) == 0.0
    assert stat_gate.trial_success_rate(7, 7) == 1.0
    assert stat_gate.trial_success_rate(5, 7) == pytest.approx(5 / 7)
    assert stat_gate.trial_success_rate(3, 0) == 0.0  # defensive


def test_wilson_ci_handles_edge_rates():
    for p in (0.0, 1.0):
        low, high = stat_gate.wilson_ci(p, 7)
        assert 0.0 <= low <= high <= 1.0
        assert math.isfinite(low) and math.isfinite(high)
    # Wilson is conservative: all-pass still has a lower bound > 0
    assert stat_gate.wilson_ci(1.0, 7)[0] > 0.0
    # all-fail still has an upper bound < 1
    assert stat_gate.wilson_ci(0.0, 7)[1] < 1.0


def test_wilson_ci_brackets_half():
    # The interval around p=0.5 must bracket 0.5 and be finite / in-range.
    low, high = stat_gate.wilson_ci(0.5, 8)
    assert low < 0.5 < high
    assert low >= 0.0 and high <= 1.0
    # and it must be narrower than the trivial full [0,1] interval
    assert (high - low) < 1.0


def test_wilson_ci_matches_reference():
    # Wilson score interval (z=1.96) for p=5/7, n=7 — independently computed.
    p, n, z = 5 / 7, 7, 1.96
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = (z / denom) * ((p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5)
    low, high = stat_gate.wilson_ci(p, n)
    assert low == pytest.approx(centre - half, abs=1e-6)
    assert high == pytest.approx(centre + half, abs=1e-6)


# --- 1.2 baseline compare ----------------------------------------------------------

def test_compare_flags_regression():
    baseline = {"task-a": _entry(1.0, [0.75, 1.0])}
    current = {"task-a": _entry(0.0, [0.0, 0.30])}
    result = stat_gate.compare_to_baseline(current, baseline)
    assert result["tasks"]["task-a"]["verdict"] == "regressed"
    assert result["overall"] == "FAIL"


def test_compare_flags_improvement():
    baseline = {"task-a": _entry(0.0, [0.0, 0.25])}
    current = {"task-a": _entry(1.0, [0.75, 1.0])}
    result = stat_gate.compare_to_baseline(current, baseline)
    assert result["tasks"]["task-a"]["verdict"] == "improved"
    assert result["overall"] == "PASS"


def test_compare_within_noise_is_unchanged():
    baseline = {"task-a": _entry(0.7, [0.30, 0.95])}
    current = {"task-a": _entry(0.6, [0.25, 0.90])}
    result = stat_gate.compare_to_baseline(current, baseline)
    assert result["tasks"]["task-a"]["verdict"] == "unchanged"
    assert result["overall"] == "PASS"


def test_compare_missing_baseline_means_establish():
    result = stat_gate.compare_to_baseline({"t": _entry(0.5, [0.2, 0.8])}, None)
    assert result["established"] is True
    assert result["overall"] == "ESTABLISHED"


def test_compare_new_task_not_in_baseline_is_established():
    baseline = {"a": _entry(1.0, [0.75, 1.0])}
    current = {"a": _entry(1.0, [0.75, 1.0]), "new": _entry(0.5, [0.2, 0.8])}
    result = stat_gate.compare_to_baseline(current, baseline)
    assert result["tasks"]["new"]["verdict"] == "established"
    assert result["overall"] == "PASS"


# --- 1.3 baseline persist ----------------------------------------------------------

def test_baseline_roundtrip(tmp_path):
    report = {"tasks": {"t1": _entry(0.5, [0.2, 0.8])}}
    path = tmp_path / "baseline.json"
    stat_gate.save_baseline(report, str(path))
    loaded = stat_gate.load_baseline(str(path))
    assert loaded == report


def test_load_missing_baseline_returns_none(tmp_path):
    assert stat_gate.load_baseline(str(tmp_path / "nope.json")) is None


def test_corrupt_baseline_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(stat_gate.BaselineError):
        stat_gate.load_baseline(str(bad))


def test_schema_drifted_baseline_raises(tmp_path):
    drift = tmp_path / "drift.json"
    drift.write_text('{"unexpected": 1}', encoding="utf-8")
    with pytest.raises(stat_gate.BaselineError):
        stat_gate.load_baseline(str(drift))
