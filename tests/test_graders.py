"""Tests for src.graders — Grader protocol, ScriptedGrader, LlmJudgeGrader."""

from __future__ import annotations

import pytest

from src.graders import (
    GradeResult,
    Grader,
    ScriptedGrader,
    LlmJudgeGrader,
    resolve_graders,
)
from src.test_runner import TestRunResult, TestStepResult


def _passed_run():
    r = TestRunResult(form_name="F", variation=1)
    r.steps = [
        TestStepResult(step="1", action="navigate", status="passed"),
        TestStepResult(step="3", action="assert", status="passed"),
    ]
    r.status = "passed"
    return r


def _failed_run():
    r = TestRunResult(form_name="F", variation=1)
    r.steps = [
        TestStepResult(step="2", action="fill", status="failed", details="boom"),
        TestStepResult(step="3", action="assert", status="failed", details="error indicator"),
    ]
    r.status = "failed"
    return r


def test_grader_protocol():
    assert isinstance(ScriptedGrader(), Grader)


def test_scripted_grader_pass():
    res = ScriptedGrader().grade(_passed_run())
    assert isinstance(res, GradeResult)
    assert res.passed is True
    assert res.score == 1.0


def test_scripted_grader_fail_on_failed_step():
    res = ScriptedGrader().grade(_failed_run())
    assert res.passed is False
    assert res.detail


def test_scripted_grader_no_llm_needed():
    assert ScriptedGrader().grade(_passed_run()).passed is True


def test_resolve_graders_default_is_scripted():
    graders = resolve_graders(None)
    assert len(graders) == 1
    assert isinstance(graders[0], ScriptedGrader)


def test_resolve_graders_parses_task_spec():
    spec = [
        {"type": "scripted"},
        {"type": "llm-judge", "rubric": "coherent success confirmation"},
    ]
    graders = resolve_graders(spec, judge_cfg={"base_url": "http://j", "model": "judge-m"})
    assert isinstance(graders[0], ScriptedGrader)
    assert isinstance(graders[1], LlmJudgeGrader)
    assert graders[1].rubric == "coherent success confirmation"


def test_resolve_graders_defaults_scripted_when_type_missing():
    graders = resolve_graders([{"rubric": "x"}])
    assert isinstance(graders[0], ScriptedGrader)


def test_llm_judge_targets_judge_endpoint_not_model_under_test():
    captured = {}

    def fake_transport(base_url, model, prompt, api_key):
        captured["url"] = base_url
        captured["model"] = model
        # Return the raw response body the parser expects (JSON string).
        return '{"passed": true, "score": 0.9}'

    judge_cfg = {"base_url": "http://judge/v1", "model": "judge-m", "api_key": "j"}
    g = LlmJudgeGrader(judge_cfg, rubric="be nice", transport=fake_transport)
    res = g.grade(_passed_run())
    assert captured["url"] == "http://judge/v1"
    assert captured["model"] == "judge-m"
    assert res.passed is True
    assert res.score == pytest.approx(0.9)
    assert res.grader_type == "llm-judge"


def test_llm_judge_falls_back_when_not_configured():
    g = LlmJudgeGrader({})  # no base_url → judge off
    res = g.grade(_passed_run())
    assert res.passed is True  # falls back to scripted verdict
    assert "judge not configured" in res.detail


def test_llm_judge_falls_back_on_transport_error():
    def boom(base_url, model, prompt, api_key):
        raise RuntimeError("judge down")
    g = LlmJudgeGrader({"base_url": "http://j", "model": "m"}, transport=boom)
    res = g.grade(_passed_run())
    assert res.passed is True  # scripted verdict preserved
    assert "judge unavailable" in res.detail
