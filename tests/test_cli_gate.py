"""Tests for the `superApp gate` CLI command (Group 6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from typer.testing import CliRunner

from src.cli import app, gate as gate_cmd

runner = CliRunner()


# --- 6.1 gate command flag surface ------------------------------------------------

def test_gate_help_lists_all_flags():
    result = runner.invoke(app, ["gate", "--help"])
    assert result.exit_code == 0
    out = result.output
    for flag in ("--target", "--source", "--suite", "--n",
                 "--baseline", "--fail-on-regression", "--cost-gate",
                 "--output"):
        assert flag in out, f"missing flag {flag} in gate --help:\n{out}"


def test_gate_requires_suite(tmp_path, monkeypatch):
    # No suite dir → infra error (exit 2), not a crash.
    # Point at a temp dir (empty) so we don't accidentally pick up the repo's tasks/.
    suite = tmp_path / "missing_suite"
    result = runner.invoke(
        app,
        [
            "gate", "--target", "http://x",
            "--suite", str(suite),
            "--output", str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 2, result.output


def test_gate_existing_commands_unchanged():
    # The public LEF contract: run/analyze/generate still present.
    for cmd in ("run", "analyze", "generate", "openhands-start",
                "openhands-stop", "openhands-status"):
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0, f"{cmd} --help broke:\n{result.output}"


# --- 6.2 config judge/cost blocks -------------------------------------------------

def test_config_example_has_judge_and_cost():
    cfg = Path("config.example.yaml")
    text = cfg.read_text()
    assert "judge:" in text, "config.example.yaml missing judge block"
    assert "cost:" in text, "config.example.yaml missing cost block"
    assert "rate_table" in text, "config.example.yaml missing cost.rate_table"


def test_gate_with_no_judge_config_uses_scripted(tmp_path, monkeypatch):
    import src.pipeline as P
    from src.test_runner import TestRunResult, TestStepResult

    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "t.yaml").write_text(
        "name: t\nform: CreateProjectForm\ndata: {name: X}\n")

    captured = {}

    class _Stub:
        def __init__(self, **_):
            pass
        async def start(self):
            pass
        async def close(self):
            pass
        async def run_form_tests(self, form_name, data, variation):
            r = TestRunResult(form_name=form_name, variation=variation)
            r.steps = [TestStepResult(step="1", action="navigate", status="passed")]
            r.status = "passed"
            return r

    # Patch the runner in the pipeline module's namespace so run_gate uses the stub.
    P.TestRunner = _Stub

    result = runner.invoke(
        app, [
            "gate", "--target", "http://x", "--source", ".",
            "--suite", str(suite), "--n", "5",
            "--output", str(tmp_path / "out"),
        ],
    )
    # With no judge config, gate runs via ScriptedGrader → PASS, exit 0.
    assert result.exit_code == 0, result.output
    report = (tmp_path / "out" / "gate_report.json")
    assert report.exists()
    import json
    rep = json.loads(report.read_text())
    assert rep["verdict"] in ("PASS", "ESTABLISHED")


# --- 6.3 run_test.sh gate passthrough --------------------------------------------

def test_run_test_sh_supports_gate_mode(tmp_path):
    sh = Path("run_test.sh").read_text()
    assert "gate" in sh, "run_test.sh has no gate mode handling"
    assert "SUPERAPP_MODE" in sh
    # gate mode must not require docker
    # (only agent mode requires docker)
