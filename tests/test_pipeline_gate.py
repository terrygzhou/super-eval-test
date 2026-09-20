"""Tests for Pipeline.run_gate — the evaluation layer's orchestration."""

from __future__ import annotations

import asyncio
import json

import pytest

from src.pipeline import Pipeline
from src.task_suite import TaskSuiteError, load_suite


class _FakeRunner:
    """Deterministic stand-in for TestRunner so run_gate can be tested
    without a browser / reachable target."""

    def __init__(self, **_):
        self._n = 0

    async def start(self):
        pass

    async def close(self):
        pass

    async def run_form_tests(self, form_name, data, variation):
        from src.test_runner import TestRunResult, TestStepResult
        self._n += 1
        result = TestRunResult(form_name=form_name, variation=variation)
        # Deterministically pass the first N-1 trials, fail the last, per task
        # count, to exercise both verdicts.
        ok = (self._n % 2) != 0
        result.steps = [TestStepResult(step="1", action="navigate",
                                       status="passed" if ok else "failed")]
        result.status = "passed" if ok else "failed"
        return result


@pytest.fixture(autouse=True)
def _patch_runner(monkeypatch):
    import src.pipeline as P
    monkeypatch.setattr(P, "TestRunner", _FakeRunner)


@pytest.fixture
def suite(tmp_path):
    d = tmp_path / "suite"
    d.mkdir()
    (d / "happy.yaml").write_text(
        "name: happy\nform: CreateProjectForm\ndata: {name: X, owner: o@x.com}\n")
    (d / "edge.yaml").write_text(
        "name: edge\nform: CreateProjectForm\ndata: {name: 'a', owner: o@x.com}\n")
    return str(d)


def test_run_gate_produces_report_and_exit0(suite, tmp_path):
    p = Pipeline(output_dir=str(tmp_path / "out"), target_url="http://x",
                 source_root=".", mode="scripted")
    verdict = asyncio.run(p.run_gate(
        suite_dir=suite, n_trials=5,
        baseline_path=str(tmp_path / "nope.json"),
        target_override="http://x",
    ))
    report_path = tmp_path / "out" / "gate_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text())
    assert report["verdict"] == "ESTABLISHED"
    assert verdict["exit_code"] == 0
    for task_name in ("happy", "edge"):
        assert task_name in report["tasks"]
        assert "success_rate" in report["tasks"][task_name]
        assert "ci" in report["tasks"][task_name]


def test_run_gate_n_bounds_enforced(suite, tmp_path):
    p = Pipeline(output_dir=str(tmp_path / "out"), target_url="http://x",
                 source_root=".", mode="scripted")
    with pytest.raises(ValueError):
        asyncio.run(p.run_gate(suite_dir=suite, n_trials=4,
                               baseline_path=None, target_override="http://x"))
    with pytest.raises(ValueError):
        asyncio.run(p.run_gate(suite_dir=suite, n_trials=12,
                               baseline_path=None, target_override="http://x"))


def test_run_gate_suite_error_is_infra(suite, tmp_path):
    p = Pipeline(output_dir=str(tmp_path / "out"), target_url="http://x",
                 source_root=".", mode="scripted")
    with pytest.raises(TaskSuiteError):
        asyncio.run(p.run_gate(suite_dir=str(tmp_path / "missing"), n_trials=5,
                               baseline_path=None, target_override="http://x"))


def test_run_gate_junit_wellformed(suite, tmp_path):
    import xml.etree.ElementTree as ET
    p = Pipeline(output_dir=str(tmp_path / "out"), target_url="http://x",
                 source_root=".", mode="scripted")
    asyncio.run(p.run_gate(suite_dir=suite, n_trials=5,
                           baseline_path=str(tmp_path / "nope.json"),
                           target_override="http://x"))
    junit = tmp_path / "out" / "gate_report.xml"
    root = ET.parse(junit).getroot()
    assert root.tag == "testsuites"
    suites = root.findall("testsuite")
    assert len(suites) == 2
    # each suite has one <testcase> per trial
    assert len(suites[0].findall("testcase")) == 5


def _make_runner(pass_all: bool):
    """Deterministic runner that passes every trial (pass_all=True) or fails
    every trial (pass_all=False) — no odd/even jitter, so success rates are
    exactly 1.0 or 0.0."""
    from src.test_runner import TestRunResult, TestStepResult

    class _Runner:
        def __init__(self, **_):
            pass

        async def start(self):
            pass

        async def close(self):
            pass

        async def run_form_tests(self, form_name, data, variation):
            r = TestRunResult(form_name=form_name, variation=variation)
            r.steps = [TestStepResult(step="1", action="navigate",
                                      status="passed" if pass_all else "failed")]
            r.status = "passed" if pass_all else "failed"
            return r

    return _Runner


def test_run_gate_baseline_regression_blocks(suite, tmp_path):
    import json as _json
    import src.pipeline as P
    out = tmp_path / "out"
    baseline = out / "baseline.json"
    # Establish a clearly-high baseline: all trials pass (100% success at
    # n=10). Save the resulting gate_report as the baseline file.
    P.TestRunner = _make_runner(pass_all=True)
    p = Pipeline(output_dir=str(out), target_url="http://x",
                 source_root=".", mode="scripted")
    asyncio.run(p.run_gate(suite_dir=suite, n_trials=10,
                           baseline_path=str(baseline),
                           target_override="http://x"))
    # Now a run where every trial fails (0% success at n=10) → the Wilson CI
    # for current sits entirely below the baseline CI → "regressed" → FAIL.
    P.TestRunner = _make_runner(pass_all=False)
    p2 = Pipeline(output_dir=str(out), target_url="http://x",
                  source_root=".", mode="scripted")
    verdict = asyncio.run(p2.run_gate(
        suite_dir=suite, n_trials=10,
        baseline_path=str(baseline), target_override="http://x"))
    assert verdict["exit_code"] == 1
    assert verdict["verdict"] == "FAIL"
