"""Pipeline orchestrator — runs all phases end-to-end."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.table import Table

from .constants import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_OPENHANDS_LLM_MODEL,
)

from src.source_analyzer import SourceAnalyzer
from src.data_generator import DataGenerator, TestDataset
from src.test_runner import TestRunner, TestRunResult
from src.log_monitor import LogMonitor, TestEvent
from src.prompts import analyze_goal, report_goal, test_goal

console = Console()


class Pipeline:
    """Orchestrate the full testing pipeline: analyze → generate → run → correlate."""

    def __init__(
        self,
        config_path: str | None = None,
        output_dir: str = "./superApp_output",
        target_url: str = "",
        source_root: str = "",
        llm_url: str = "",
        llm_model: str = "",
        n_variations: int = 3,
        mode: str = "scripted",
        agent_workspace: str = "",
        agent_timeout: int = 600,
        openhands_url: str = "",
        openhands_auth: str = "",
        use_existing_server: bool = False,
    ):
        self.config = self._load_config(config_path)
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir = self.output_dir / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Override config with explicit CLI args
        if target_url:
            self.config.setdefault("target", {})["url"] = target_url
        if source_root:
            self.config.setdefault("source", {})["root"] = source_root
        if llm_url:
            self.config.setdefault("llm", {})["base_url"] = llm_url
        if llm_model:
            self.config.setdefault("llm", {})["model"] = llm_model
        self.config.setdefault("pipeline", {})["data_variations"] = n_variations

        # Execution mode
        self.mode = mode
        self.agent_workspace = agent_workspace
        self.agent_timeout = agent_timeout

        # OpenHands endpoint / auth / reuse. Explicit kwargs win, then config
        # (openhands: block), then env, then the built-in :3005 compose default.
        oh_cfg = self.config.get("openhands", {})
        self.openhands_url = (
            openhands_url
            or oh_cfg.get("url")
            or os.environ.get("OPENHANDS_URL", "http://localhost:3005")
        )
        self.openhands_auth = (
            openhands_auth
            or oh_cfg.get("auth_token", "")
            or os.environ.get("OPENHANDS_AUTH_TOKEN", "")
        )
        # Reuse a running server (e.g. openhands-canvas:43006) when requested
        # explicitly, OR when a non-default URL is configured.
        self.use_existing_server = bool(
            use_existing_server
            or oh_cfg.get("use_existing_server", False)
            or os.environ.get("OPENHANDS_USE_EXISTING", "0") == "1"
        )

        # Intermediate data
        self.schemas: list[dict] = []
        self.dataset: TestDataset | None = None

    def _load_config(self, config_path: str | None) -> dict:
        """Load configuration from YAML."""
        if config_path is None:
            return {}
        path = Path(config_path)
        if path.exists():
            return yaml.safe_load(path.read_text()) or {}
        return {}

    async def run_agent_mode(
        self, source_root: str, target_url: str
    ) -> dict:
        """Run in agent mode: delegate to OpenHands Agent Server.

        Strategy: split monolithic task into 3 sequential conversations to avoid timeouts.
        Each conversation shares the same workspace directory for state handoff.
        """
        from src.openhands_client import OpenHandsClient, OpenHandsError

        # Copy source into the host workspace dir that compose.yaml mounts
        # into the container as /opt/workspace_base. An explicit
        # --agent-workspace overrides the default ./workspace/source.
        host_workspace = (
            Path(self.agent_workspace).resolve()
            if self.agent_workspace
            else Path(__file__).parent.parent / "workspace" / "source"
        )
        host_workspace.parent.mkdir(parents=True, exist_ok=True)
        if host_workspace.exists():
            shutil.rmtree(str(host_workspace))
        shutil.copytree(
            source_root, host_workspace,
            symlinks=False,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".venv"),
        )
        # All paths must be inside the workspace working_dir so the agent can access them.
        # compose.yaml mounts ./workspace → /opt/workspace_base
        # working_dir is /opt/workspace_base/source — agent sandbox is confined here.
        container_source = "/opt/workspace_base/source"
        artifacts_dir = "/opt/workspace_base/source/artifacts"
        # Ensure the artifacts dir exists so the agent can write to it without sudo
        host_artifacts = host_workspace / "artifacts"
        host_artifacts.mkdir(parents=True, exist_ok=True)

        console.print(f"[blue]Copied source → {host_workspace}[/blue]")

        compose_path = str(Path(__file__).parent.parent / "compose.yaml")
        client = OpenHandsClient(
            base_url=self.openhands_url,
            compose_file=compose_path,
            timeout=self.agent_timeout,
            model=DEFAULT_OPENHANDS_LLM_MODEL,
            base_llm_url=DEFAULT_LLM_BASE_URL,
            auth_header=self.openhands_auth or None,
            use_existing_server=self.use_existing_server,
        )

        banner = (
            "[bold blue]Agent mode: Reusing existing OpenHands server "
            f"({self.openhands_url})...[/bold blue]"
            if self.use_existing_server
            else "[bold blue]Agent mode: Starting OpenHands container...[/bold blue]"
        )
        console.print(banner)
        try:
            client.start_server()
        except Exception as e:
            console.print(f"[red]OpenHands startup failed: {e}[/red]")
            raise OpenHandsError(f"OpenHands startup failed: {e}")

        try:
            # ── Conversation 1: Analyze ──────────────────────────────
            console.print("[bold blue]Conversation 1: Analyze source...[/bold blue]")
            goal1 = analyze_goal(container_source, artifacts_dir)
            conv1_id = client.create_conversation(goal1, container_source)
            console.print(f"  Conversation ID: {conv1_id}")

            event_count = [0]
            def on_event(evt):
                kind = evt.get("kind", "unknown")
                code = evt.get("code")
                source = evt.get("source", "")
                event_count[0] += 1
                if code:
                    console.print(f"  [red]⚠ Event #{event_count[0]}: {kind} (code: {code})[/red]")
                elif source == "agent":
                    console.print(f"  [dim]→ {kind}[/dim]")

            result1 = client.poll_conversation_with_events(conv1_id, on_event=on_event)
            exec_status = result1.get("execution_status", "unknown")
            console.print(f"  [green]✓ Analysis complete (status: {exec_status}, events: {event_count[0]})[/green]")

            # ── Conversation 2: Test ─────────────────────────────────
            console.print("[bold blue]Conversation 2: Run tests...[/bold blue]")
            goal2 = test_goal(container_source, artifacts_dir, target_url)
            conv2_id = client.create_conversation(goal2, container_source)
            console.print(f"  Conversation ID: {conv2_id}")

            event_count[0] = 0
            result2 = client.poll_conversation_with_events(conv2_id, on_event=on_event)
            exec_status = result2.get("execution_status", "unknown")
            console.print(f"  [green]✓ Tests complete (status: {exec_status}, events: {event_count[0]})[/green]")

            # ── Conversation 3: Report ────────────────────────────────
            console.print("[bold blue]Conversation 3: Generate report...[/bold blue]")
            goal3 = report_goal(container_source, artifacts_dir)
            conv3_id = client.create_conversation(goal3, container_source)
            console.print(f"  Conversation ID: {conv3_id}")

            event_count[0] = 0
            result3 = client.poll_conversation_with_events(conv3_id, on_event=on_event)
            exec_status = result3.get("execution_status", "unknown")
            console.print(f"  [green]✓ Report complete (status: {exec_status}, events: {event_count[0]})[/green]")

            # ── Copy all artifacts from workspace to output ──────────
            self.output_dir.mkdir(parents=True, exist_ok=True)
            host_artifacts = host_workspace / "artifacts"
            if host_artifacts.exists():
                # Copy entire artifacts directory (analysis.json, test_data.json,
                # test_results.json, report.json, run_tests.py, screenshots/)
                dest = self.output_dir / "artifacts"
                if dest.exists():
                    shutil.rmtree(str(dest))
                shutil.copytree(host_artifacts, dest, symlinks=False)
                console.print(f"[bold]Artifacts copied: {dest}[/bold]")
                # Also write agent_report.json as the top-level summary
                host_report = host_artifacts / "report.json"
                if host_report.exists():
                    report_data = json.loads(host_report.read_text())
                    report_path = self.output_dir / "agent_report.json"
                    report_path.write_text(
                        json.dumps(report_data, indent=2, default=str),
                        encoding="utf-8",
                    )
                    console.print(f"[bold]Agent report saved: {report_path}[/bold]")
                    return report_data
            # Fallback: combine conversation results
            combined = {"analysis": result1, "tests": result2, "report": result3}
            report_path = self.output_dir / "agent_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(combined, indent=2, default=str), encoding="utf-8"
            )
            console.print(f"[yellow]Report fallback: {report_path}[/yellow]")
            return combined
        finally:
            console.print("[yellow]Stopping OpenHands container...[/yellow]")
            client.stop_server()
            client.close()

    async def run(self, source_override: str = "", target_override: str = "") -> dict:
        """Run the full pipeline in the configured mode."""
        if self.mode == "agent":
            source_root = source_override or self.config.get("source", {}).get(
                "root", ""
            )
            if not source_root:
                console.print("[red]Error: source root is required (set --source or source.root in config)[/red]")
                raise SystemExit(1)
            target_url = target_override or self.config.get("target", {}).get(
                "url", "http://localhost:8081"
            )
            return await self.run_agent_mode(source_root, target_url)

        # Scripted mode (existing pipeline)
        start_time = time.time()

        console.print("\n[bold cyan]🚀 SuperApp Test Pipeline[/bold cyan]")
        console.print("=" * 50)

        # Phase 1: Source Analysis
        console.print("\n[bold green]Phase 1[/bold green]: Source Analysis...")
        schemas = await self.phase1_analyze(source_override)

        # Phase 2: Data Generation
        console.print("\n[bold green]Phase 2[/bold green]: Data Generation...")
        dataset = await self.phase2_generate(schemas)

        # Phase 3: Browser Testing
        console.print("\n[bold green]Phase 3[/bold green]: Browser Testing...")
        results = await self.phase3_test(dataset, target_override)

        # Phase 4: Log Correlation
        console.print("\n[bold green]Phase 4[/bold green]: Log Correlation...")
        report = await self.phase4_correlate(results, start_time)

        # Summary
        elapsed = time.time() - start_time
        console.print(f"\n[bold]{'=' * 50}[/bold]")
        console.print(f"[bold]Pipeline complete[/bold] — {elapsed:.1f}s")

        table = Table(title="Summary")
        table.add_column("Metric")
        table.add_column("Value")
        table.add_row("Forms analyzed", str(len(schemas)))
        table.add_row("Test records", str(len(dataset.records) if dataset else "0"))
        table.add_row(
            "Tests passed/total",
            f"{sum(1 for r in results if r.status == 'passed')}/{len(results)}",
        )
        table.add_row("Correlated errors", str(report.get("summary", {}).get("correlated_errors", 0)))
        table.add_row("Total time", f"{elapsed:.1f}s")
        console.print(table)

        return report

    async def phase1_analyze(self, source_override: str = "") -> list[dict]:
        """Phase 1: Analyze source code for form schemas."""
        source_root = source_override or self.config.get("source", {}).get(
            "root", ""
        )
        if not source_root:
            console.print("[red]Error: source root is required (set --source or source.root in config)[/red]")
            raise SystemExit(1)
        form_patterns = self.config.get("source", {}).get("form_patterns", [])
        route_patterns = self.config.get("source", {}).get("route_patterns", [])

        analyzer = SourceAnalyzer(
            source_root=source_root,
            form_patterns=form_patterns if form_patterns else None,
            route_patterns=route_patterns if route_patterns else None,
        )
        result = analyzer.analyze()

        # Save schemas
        schema_path = self.output_dir / "data" / "schemas.json"
        analyzer.save_results(result, str(schema_path))

        console.print(f"  Found {result.summary['forms_found']} forms, "
                      f"{result.summary['routes_found']} routes, "
                      f"{result.summary['total_fields']} fields")
        console.print(f"  Schemas saved: {schema_path}")

        self.schemas = [s.model_dump() for s in result.forms]
        return self.schemas

    async def phase2_generate(self, schemas: list[dict]) -> TestDataset:
        """Phase 2: Generate test data using LLM."""
        llm_cfg = self.config.get("llm", {})
        n_variations = self.config.get("pipeline", {}).get("data_variations", 3)

        generator = DataGenerator(
            llm_base_url=llm_cfg.get("base_url", DEFAULT_LLM_BASE_URL),
            model=llm_cfg.get("model", DEFAULT_LLM_MODEL),
            n_variations=n_variations,
        )

        try:
            dataset = await generator.generate(schemas)
        except Exception as e:
            console.print(f"  [yellow]LLM unavailable ({e}), using fallback[/yellow]")
            dataset = generator.generate_fallback(schemas)
        finally:
            await generator.close()

        # Save dataset
        data_path = self.output_dir / "data" / "test_data.json"
        generator.save(dataset, str(data_path))

        console.print(f"  Generated {len(dataset.records)} test records "
                      f"({dataset.metadata.get('generator', 'unknown')})")
        console.print(f"  Data saved: {data_path}")

        self.dataset = dataset
        return dataset

    async def phase3_test(
        self, dataset: TestDataset, target_override: str = ""
    ) -> list[TestRunResult]:
        """Phase 3: Run browser tests."""
        browser_cfg = self.config.get("browser", {})
        target_cfg = self.config.get("target", {})
        target_url = target_override or target_cfg.get("url", "http://localhost:8081")

        runner = TestRunner(
            target_url=target_url,
            headless=browser_cfg.get("headless", True),
            timeout_ms=browser_cfg.get("timeout_ms", 30000),
            viewport=browser_cfg.get("viewport", {"width": 1280, "height": 720}),
            storage_state=browser_cfg.get("storage_state"),
            artifacts_dir=str(self.artifacts_dir),
        )

        await runner.start()
        results: list[TestRunResult] = []

        # Group records by form name
        forms: dict[str, list] = {}
        for record in dataset.records:
            forms.setdefault(record.form_name, []).append(record)

        for form_name, records in forms.items():
            for record in records:
                console.print(f"  Testing: {form_name} (variation {record.variation})")
                result = await runner.run_form_tests(form_name, record.data, record.variation)
                results.append(result)
                status = "✅" if result.status == "passed" else "❌"
                console.print(f"    {status} {result.status} ({result.total_duration_ms}ms)")

        await runner.close()

        passed = sum(1 for r in results if r.status == "passed")
        console.print(f"\n  Total: {passed}/{len(results)} passed")

        # Save results
        results_path = self.output_dir / "data" / "test_results.json"
        results_json = json.dumps(
            [r.__dict__ for r in results], indent=2, default=str
        )
        Path(results_path).parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text(results_json, encoding="utf-8")
        console.print(f"  Results saved: {results_path}")

        return results

    async def phase4_correlate(
        self, results: list[TestRunResult], pipeline_start: float
    ) -> dict:
        """Phase 4: Correlate server logs with test events."""
        logs_cfg = self.config.get("logs", {})

        monitor = LogMonitor(
            log_type=logs_cfg.get("type", "docker"),
            docker_container=logs_cfg.get("docker_container"),
            log_file=logs_cfg.get("log_file"),
            journal_unit=logs_cfg.get("journal_unit"),
            error_patterns=logs_cfg.get("error_patterns", ["ERROR", "Exception"]),
        )

        # Record test events
        for result in results:
            for step in result.steps:
                monitor.record_test_event(
                    TestEvent(
                        timestamp=step.timestamp,
                        form_name=result.form_name,
                        variation=result.variation,
                        step=step.step,
                        action=step.action,
                        status=step.status,
                    )
                )

        # Collect and correlate
        logs = monitor.collect_logs(pipeline_start, time.time())
        monitor.log_events = logs
        correlations = monitor.correlate()
        report = monitor.generate_report()

        console.print(f"  Log errors found: {len(logs)}")
        console.print(f"  Correlated with tests: {len(correlations)}")

        # Save report
        report_path = self.output_dir / "logs" / "correlation_report.json"
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        console.print(f"  Report saved: {report_path}")

        return report

    async def run_gate(
        self,
        *,
        suite_dir: str,
        n_trials: int = 7,
        baseline_path: str | None = None,
        target_override: str = "",
        cost_gate: bool = False,
        fail_on_regression: bool = True,
    ) -> dict:
        """Run the evaluation gate: deterministic task-suite trials + regression gating."""
        return await _run_gate_impl(
            self,
            suite_dir,
            n_trials,
            baseline_path,
            target_override,
            cost_gate,
            fail_on_regression,
        )

# Exit codes per the gate contract: 0 pass/established, 1 regression, 2 infra
EXIT_PASS = 0
EXIT_REGRESSION = 1
EXIT_INFRA = 2


def _junit_xml(report: dict, n_trials: int) -> str:
    """Render a JUnit-XML gate report: one <testsuite> per task, one
    <testcase> per trial. Stdlib xml only."""
    import xml.etree.ElementTree as ET

    suites = ET.Element("testsuites", {"name": "superApp-gate"})
    for name, entry in report["tasks"].items():
        fails = 0
        trials = entry.get("trials", [])
        tsuite = ET.SubElement(
            suites, "testsuite", name=name, tests=str(n_trials), failures="0",
        )
        for i in range(n_trials):
            trial = trials[i] if i < len(trials) else {}
            tc = ET.SubElement(tsuite, "testcase", name=f"trial-{i + 1}")
            if not trial.get("passed", False):
                fails += 1
                ET.SubElement(tc, "failure", message="trial failed")
        tsuite.set("failures", str(fails))
    ET.indent(suites, space="  ")
    return ET.tostring(suites, encoding="unicode", xml_declaration=False)


def _gate_report_md(report: dict) -> str:
    """Human-readable gate report: task, rate, CI, verdict, cost."""
    lines = ["# SuperApp Gate Report", ""]
    lines.append(f"**Verdict:** {report['verdict']}   ")
    lines.append(f"**Trials per task:** {report.get('n_trials', '?')}   ")
    lines.append("")
    lines.append("| Task | Rate | 95% CI | Verdict | Cost (USD) |")
    lines.append("|---|---|---|---|---|")
    for name, entry in report["tasks"].items():
        lo, hi = entry["ci"]
        cost = entry.get("cost", {}).get("estimated_cost_usd", 0.0)
        verdict = entry.get("baseline_verdict", "—")
        lines.append(
            f"| {name} | {entry['success_rate']:.3f} | [{lo:.3f}, {hi:.3f}] "
            f"| {verdict} | {cost:.4f} |"
        )
    lines.append("")
    return "\n".join(lines)


async def _run_gate_impl(
    self: "Pipeline",
    suite_dir: str,
    n_trials: int,
    baseline_path: str | None,
    target_override: str,
    cost_gate: bool,
    fail_on_regression: bool,
) -> dict:
    """Core gate orchestration. Kept as a free function so `Pipeline.run_gate`
    is a thin, discoverable method."""
    from src import stat_gate
    from src.cost_tracker import CostTracker
    from src.graders import resolve_graders
    from src.task_suite import load_suite

    if not (5 <= n_trials <= 10):
        raise ValueError(f"--n must be between 5 and 10 (got {n_trials})")

    tasks = load_suite(suite_dir)
    judge_cfg = self.config.get("judge", {})
    rate_table = self.config.get("cost", {}).get("rate_table")
    tracker = CostTracker(rate_table=rate_table)

    target_url = target_override or self.config.get("target", {}).get(
        "url", "http://localhost:8081"
    )
    browser_cfg = self.config.get("browser", {})
    runner = TestRunner(
        target_url=target_url,
        headless=browser_cfg.get("headless", True),
        timeout_ms=browser_cfg.get("timeout_ms", 30000),
        viewport=browser_cfg.get("viewport", {"width": 1280, "height": 720}),
        storage_state=browser_cfg.get("storage_state"),
        artifacts_dir=str(self.artifacts_dir),
    )
    await runner.start()

    task_entries: dict[str, dict] = {}
    try:
        for task in tasks:
            trial_passed = 0
            trial_details: list[dict] = []
            total_latency = 0.0
            for trial in range(n_trials):
                t0 = time.time()
                result = await runner.run_form_tests(task.form, task.data, trial + 1)
                total_latency += time.time() - t0

                graders = resolve_graders(task.graders, judge_cfg=judge_cfg)
                grade = graders[0].grade(result)
                for g in graders[1:]:
                    grade = g.grade(result)
                trial_passed += int(grade.passed)
                trial_details.append({
                    "trial": trial + 1,
                    "passed": bool(grade.passed),
                    "score": grade.score,
                    "detail": grade.detail,
                    "graders": [g.grader_type for g in graders],
                })

            used_judge = any(g == "llm-judge" for d in trial_details for g in d["graders"])
            tokens_in = tokens_out = llm_calls = 0
            if used_judge:
                llm_calls = n_trials
                tokens_in = n_trials * 400
                tokens_out = n_trials * 80
            tool_calls = n_trials  # one runner step-count per trial
            cost = tracker.record_trial(
                task=task.name, n_trials=n_trials,
                tokens_in=tokens_in, tokens_out=tokens_out,
                llm_calls=llm_calls, latency_s=total_latency, tool_calls=tool_calls,
            )

            success_rate = stat_gate.trial_success_rate(trial_passed, n_trials)
            ci = stat_gate.wilson_ci(success_rate, n_trials)
            task_entries[task.name] = {
                "form": task.form,
                "success_rate": success_rate,
                "n_trials": n_trials,
                "n_passed": trial_passed,
                "ci": list(ci),
                "trials": trial_details,
                "cost": cost,
            }
    finally:
        await runner.close()

    baseline = stat_gate.load_baseline(baseline_path) if baseline_path else None
    baseline_tasks = baseline["tasks"] if baseline else None
    comparison = stat_gate.compare_to_baseline(task_entries, baseline_tasks)

    verdict = "PASS"
    if comparison["established"]:
        verdict = "ESTABLISHED"
    elif comparison["overall"] == "FAIL":
        verdict = "FAIL"
    for name, entry in comparison.get("tasks", {}).items():
        if name in task_entries:
            task_entries[name]["baseline_verdict"] = entry["verdict"]

    cost_breach = False
    if cost_gate:
        for task in tasks:
            limits = task.cost_limits or {}
            cost = task_entries[task.name]["cost"]
            if limits.get("max_tokens_out") and cost["tokens_out"] > limits["max_tokens_out"]:
                cost_breach = True
            if limits.get("max_latency_s") and cost["latency_s"] > limits["max_latency_s"]:
                cost_breach = True

    report = {
        "verdict": verdict,
        "n_trials": n_trials,
        "tasks": task_entries,
        "baseline_path": baseline_path,
        "cost_totals": tracker.run_totals(),
        "cost_breach": cost_breach,
    }
    report_path = self.output_dir / "gate_report.json"
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (self.output_dir / "gate_report.md").write_text(_gate_report_md(report), encoding="utf-8")
    (self.output_dir / "gate_report.xml").write_text(_junit_xml(report, n_trials), encoding="utf-8")
    (self.output_dir / "cost.json").write_text(
        json.dumps(tracker.to_cost_json(), indent=2, default=str), encoding="utf-8"
    )
    if comparison["established"] and baseline_path:
        stat_gate.save_baseline(report, baseline_path)

    if cost_breach and cost_gate:
        exit_code = EXIT_REGRESSION
    elif verdict == "FAIL" and fail_on_regression:
        exit_code = EXIT_REGRESSION
    else:
        exit_code = EXIT_PASS

    console.print(f"\n[bold]Gate verdict: {verdict}[/bold] (exit {exit_code})")
    return {
        "verdict": verdict,
        "exit_code": exit_code,
        "report_path": str(report_path),
        "cost_breach": cost_breach,
    }
