"""Tests for the four defect fixes documented in report/.

Run with:  pytest tests/test_fixes.py -v
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. .gitignore — superApp_output/ present, suet_output/ removed
# ---------------------------------------------------------------------------

class TestGitignoreOutputDir:
    """The default CLI output dir is ./superApp_output (cli.py:48);
    .gitignore must ignore it, not the legacy suet_output/."""

    def test_gitignore_ignores_superApp_output(self):
        content = (PROJECT_ROOT / ".gitignore").read_text()
        assert "superApp_output/" in content, (
            ".gitignore must contain superApp_output/ (the CLI default output dir)"
        )

    def test_gitignore_no_suet_output(self):
        content = (PROJECT_ROOT / ".gitignore").read_text()
        assert "suet_output/" not in content, (
            "stale suet_output/ line must be removed from .gitignore"
        )

    def test_gitignore_actually_ignores_output_dir(self):
        """git check-ignore must confirm the real output dir is ignored."""
        result = subprocess.run(
            ["git", "check-ignore", "superApp_output/"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            "git check-ignore says superApp_output/ is NOT ignored; "
            f"stderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# 2. cli.py:119 — success message points at logs/, not report/
# ---------------------------------------------------------------------------

class TestCliReportPathMessage:
    """pipeline.py writes {output}/logs/correlation_report.json (line 619);
    the CLI success message must match that path."""

    def test_cli_message_uses_logs_dir(self):
        cli_src = (PROJECT_ROOT / "src" / "cli.py").read_text()
        # The message after a full run must reference logs/, not report/
        assert "{output}/logs/correlation_report.json" in cli_src, (
            "cli.py success message should point to {output}/logs/correlation_report.json"
        )
        assert "{output}/report/correlation_report.json" not in cli_src, (
            "stale {output}/report/... reference must be removed from cli.py"
        )

    def test_pipeline_writes_to_logs_dir(self):
        """Sanity-check the invariant the CLI message relies on."""
        pipe_src = (PROJECT_ROOT / "src" / "pipeline.py").read_text()
        assert '"logs" / "correlation_report.json"' in pipe_src, (
            "pipeline.py must still write the correlation report under logs/"
        )


# ---------------------------------------------------------------------------
# 3. pipeline.py — no hardcoded LEF loop_factory source-root default
# ---------------------------------------------------------------------------

class TestNoHardcodedSourceDefault:
    """Both run() and phase1_analyze() must require an explicit source root
    instead of silently defaulting to ~/workspace/projects/loop_factory."""

    def test_no_loop_factory_reference_in_pipeline(self):
        pipe_src = (PROJECT_ROOT / "src" / "pipeline.py").read_text()
        assert "loop_factory" not in pipe_src, (
            "pipeline.py must not hardcode the LEF loop_factory workspace path"
        )

    def test_run_requires_source_root(self):
        """Pipeline.run() must raise SystemExit when no source root is
        configured or passed — it must not fall back to a default path."""
        from src.pipeline import Pipeline

        p = Pipeline(output_dir=str(Path("/tmp").absolute() / "suet-test-out"))
        with pytest.raises(SystemExit):
            import asyncio
            asyncio.run(p.run())

    def test_phase1_analyze_requires_source_root(self):
        """phase1_analyze() with no source anywhere must raise SystemExit."""
        from src.pipeline import Pipeline

        p = Pipeline(output_dir=str(Path("/tmp").absolute() / "suet-test-out"))
        with pytest.raises(SystemExit):
            import asyncio
            asyncio.run(p.phase1_analyze())

    def test_explicit_source_root_accepted(self):
        """When a source root IS provided, phase1_analyze must not raise
        SystemExit at the guard — it should reach analysis and return.
        (Running against src/ finds 0 forms, which is fine; the point is
        the guard does NOT fire.)"""
        from src.pipeline import Pipeline
        import asyncio

        out_dir = "/tmp/suet-test-out"
        p = Pipeline(
            output_dir=out_dir,
            source_root=str(PROJECT_ROOT / "src"),
        )
        # Should complete without SystemExit from the source-root guard.
        schemas = asyncio.run(p.phase1_analyze())
        assert isinstance(schemas, list)
        # Verify the config override was applied
        assert p.config.get("source", {}).get("root") == str(PROJECT_ROOT / "src")


# ---------------------------------------------------------------------------
# 4. config.example.yaml — source.root is a generic placeholder, not a
#    machine-specific LEF path
# ---------------------------------------------------------------------------

class TestConfigExampleSourceRoot:
    def test_source_root_is_generic_placeholder(self):
        import yaml

        cfg = yaml.safe_load((PROJECT_ROOT / "config.example.yaml").read_text())
        root = cfg.get("source", {}).get("root", "")
        assert "loop_factory" not in root, (
            "config.example.yaml source.root must not reference loop_factory"
        )
        assert "workspace/projects" not in root, (
            "config.example.yaml source.root must not be a machine-specific path"
        )
