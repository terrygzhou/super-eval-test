"""CLI entry point for SuperApp Test."""

from __future__ import annotations

import asyncio
import gc
import subprocess
from pathlib import Path

import typer
from rich.console import Console

from .constants import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL

console = Console()
app = typer.Typer(
    name="superApp",
    help="AI-driven E2E web app testing pipeline",
    add_completion=True,
)


def resolve_source(source: str, output: str) -> str:
    """If source is a git URL, clone it to output/source; return local path."""
    if source.startswith("https://") or source.startswith("git@"):
        dest = Path(output) / "source"
        dest.mkdir(parents=True, exist_ok=True)
        console.print(f"[yellow]Cloning: {source} → {dest}[/yellow]")
        subprocess.run(["git", "clone", source, str(dest)], check=True)
        return str(dest)
    return source


# --- Commands ---


def _llm_url_option(help: str) -> typer.models.OptionInfo:
    return typer.Option(DEFAULT_LLM_BASE_URL, "--llm-url", help=help)


def _llm_model_option(help: str) -> typer.models.OptionInfo:
    return typer.Option(DEFAULT_LLM_MODEL, "--llm-model", help=help)


@app.command()
def run(
    *,
    target: str = typer.Option(
        "", "--target", "-t",
        help="URL of the target webapp (e.g. http://localhost:8081)",
    ),
    source: str = typer.Option(
        "", "--source", "-s",
        help="Local path or git URL of the webapp source code",
    ),
    output: str = typer.Option(
        "./superApp_output", "--output", "-o",
        help="Output/report directory for all artifacts",
    ),
    config: Path = typer.Option(
        None, "--config", "-c",
        help="Optional config.yaml (defaults to self-contained)",
    ),
    llm_url: str = _llm_url_option(
        "LLM endpoint base URL (OpenAI-compatible)",
    ),
    llm_model: str = _llm_model_option(
        "LLM model name",
    ),
    variations: int = typer.Option(
        3, "--variations", "-v",
        help="Test data variations per form (1-5)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Only analyze source, don't run browser tests",
    ),
    mode: str = typer.Option(
        "scripted", "--mode",
        help="Execution mode: scripted (deterministic pipeline) or agent (OpenHands-powered)",
    ),
    agent_workspace: str = typer.Option(
        "", "--agent-workspace",
        help="Host directory to mount into the OpenHands container (agent mode only). "
        "E.g. /home/terry/workspace/projects/openhands_output",
    ),
    agent_timeout: int = typer.Option(
        600, "--agent-timeout",
        help="Agent timeout in seconds (agent mode only, default 600)",
    ),
    openhands_url: str = typer.Option(
        "", "--openhands-url",
        help="OpenHands Agent Server base URL (agent mode). "
             "Default http://localhost:3005 (SuperApp's own compose container). "
             "Point at an existing server, e.g. http://localhost:43006 for openhands-canvas.",
    ),
    openhands_auth: str = typer.Option(
        "", "--openhands-auth",
        help="Auth token for the OpenHands server (agent mode). Sent as "
             "'Authorization: Bearer <token>'. For openhands-canvas use its API key.",
    ),
    use_existing_server: bool = typer.Option(
        False, "--use-existing-server",
        help="Reuse a running OpenHands server instead of docker-compose up "
             "(agent mode). Auto-inferred from --openhands-url / OPENHANDS_* env.",
    ),
) -> None:
    """Run the full testing pipeline against a webapp."""
    async def run_main():
        from src.pipeline import Pipeline

        if not source:
            console.print("[red]Error: --source path/git URL is required[/red]")
            raise SystemExit(1)
        if not dry_run and not target:
            console.print("[red]Error: --target URL is required (unless --dry-run)[/red]")
            raise SystemExit(1)

        source_path = resolve_source(source, output)

        p = Pipeline(
            config_path=str(config) if config else None,
            output_dir=output,
            target_url=target or "",
            source_root=source_path,
            llm_url=llm_url,
            llm_model=llm_model,
            n_variations=variations,
            mode=mode,
            agent_workspace=agent_workspace,
            agent_timeout=agent_timeout,
            openhands_url=openhands_url,
            openhands_auth=openhands_auth,
            use_existing_server=use_existing_server,
        )

        if dry_run:
            console.print("[yellow]Dry run: source analysis only[/yellow]")
            schemas = await p.phase1_analyze(source_path)
            console.print(f"Found {len(schemas)} form schemas")
            return

        report = await p.run(source_override=source_path, target_override=target)
        console.print(f"\n[bold]Pipeline complete.[/bold] Report: {output}/logs/correlation_report.json")
        # Force GC before asyncio.run() closes the event loop to avoid
        # "RuntimeError: Event loop is closed" on Playwright subprocess __del__
        gc.collect()

    asyncio.run(run_main())
    # Force GC AFTER the loop closes. Playwright browser is already shut down
    # so there's no real work — this just drains the finalizer queue without
    # the loop, which suppresses the benign "Event loop is closed" RuntimeError
    # (CPython issue 40674).
    import gc
    gc.collect()


@app.command()
def analyze(
    *,
    source: str = typer.Option(
        "", "--source", "-s",
        help="Local path or git URL of the webapp source code",
    ),
    output: str = typer.Option(
        "./superApp_output", "--output", "-o",
        help="Output directory",
    ),
    config: Path = typer.Option(
        None, "--config", "-c",
    ),
) -> None:
    """Phase 1 only: Analyze source code for form schemas."""
    if not source:
        console.print("[red]Error: --source is required[/red]")
        raise SystemExit(1)

    source_path = resolve_source(source, output)

    async def main():
        from src.pipeline import Pipeline

        p = Pipeline(
            config_path=str(config) if config else None,
            output_dir=output,
            source_root=source_path,
        )
        schemas = await p.phase1_analyze(source_path)

        console.print(f"\n[bold]Found {len(schemas)} form schemas:[/bold]")
        for s in schemas:
            form = s.get("form_name", "Unknown")
            fields = s.get("fields", [])
            console.print(f"  • {form}: {len(fields)} fields")

    asyncio.run(main())


@app.command()
def generate(
    *,
    schemas_file: Path = typer.Option(
        Path("data/schemas.json"), "--schemas",
        help="Path to schemas.json",
    ),
    output: str = typer.Option(
        "./superApp_output", "--output", "-o",
        help="Output directory for test data",
    ),
    llm_url: str = _llm_url_option(
        "LLM endpoint base URL (OpenAI-compatible)",
    ),
    llm_model: str = _llm_model_option(
        "LLM model name",
    ),
    variations: int = typer.Option(
        3, "--variations", "-v",
    ),
) -> None:
    """Phase 2 only: Generate test data from schemas."""
    async def main():
        from src.data_generator import DataGenerator

        raw = __import__("json").loads(schemas_file.read_text())
        # Handle SourceAnalysisResult format (forms/routes/summary) vs flat list
        if isinstance(raw, list):
            schemas = raw
        elif isinstance(raw, dict) and "forms" in raw:
            schemas = raw["forms"]
        else:
            console.print("[red]Error: schemas file must contain a list of forms or {forms: [...]} structure[/red]")
            raise SystemExit(1)

        gen = DataGenerator(
            llm_base_url=llm_url,
            model=llm_model,
            n_variations=variations,
        )
        try:
            dataset = await gen.generate(schemas)
        except Exception as e:
            console.print(f"[yellow]LLM unavailable ({e}), using fallback[/yellow]")
            dataset = gen.generate_fallback(schemas)
        finally:
            await gen.close()

        out_path = Path(output) / "data" / "test_data.json"
        gen.save(dataset, str(out_path))
        console.print(f"Generated {len(dataset.records)} test records → {out_path}")

    asyncio.run(main())


# --- Evaluation gate (superApp gate) ---


@app.command()
def gate(
    *,
    target: str = typer.Option(
        "", "--target", "-t",
        help="URL of the target webapp to gate against",
    ),
    source: str = typer.Option(
        "", "--source", "-s",
        help="Local path or git URL of the webapp source (optional; gate uses the "
             "task suite, not the analyzer)",
    ),
    suite: str = typer.Option(
        "tasks", "--suite",
        help="Directory of task YAML files (default ./tasks)",
    ),
    n: int = typer.Option(
        7, "--n",
        help="Trials per task (enforced 5-10; default 7)",
    ),
    baseline: Path = typer.Option(
        None, "--baseline",
        help="Path to a prior gate_report.json to compare against; "
             "omit to establish a baseline",
    ),
    fail_on_regression: bool = typer.Option(
        True, "--fail-on-regression/--no-fail-on-regression",
        help="Exit 1 when a significant regression vs baseline is detected "
             "(default true)",
    ),
    cost_gate: bool = typer.Option(
        False, "--cost-gate",
        help="Treat a cost-limit breach as a gate failure",
    ),
    output: str = typer.Option(
        "./superApp_output", "--output", "-o",
        help="Output/report directory for all artifacts",
    ),
    config: Path = typer.Option(
        None, "--config", "-c",
        help="Optional config.yaml (defaults to self-contained)",
    ),
    llm_url: str = _llm_url_option(
        "LLM endpoint base URL (used by an optional LLM judge)",
    ),
    llm_model: str = _llm_model_option(
        "LLM model name",
    ),
) -> None:
    """Run the evaluation gate: deterministic task-suite trials + regression gating."""

    async def gate_main():
        from src.pipeline import Pipeline

        source_path = resolve_source(source, output) if source else ""

        p = Pipeline(
            config_path=str(config) if config else None,
            output_dir=output,
            target_url=target or "",
            source_root=source_path,
            llm_url=llm_url,
            llm_model=llm_model,
        )

        try:
            verdict = await p.run_gate(
                suite_dir=suite,
                n_trials=n,
                baseline_path=str(baseline) if baseline else None,
                target_override=target,
                cost_gate=cost_gate,
                fail_on_regression=fail_on_regression,
            )
        except Exception as exc:
            console.print(f"[red]Gate infra error: {exc}[/red]")
            raise SystemExit(2)

        exit_code = int(verdict.get("exit_code", 0))
        console.print(
            f"[bold]Gate: {verdict.get('verdict')}[/bold] "
            f"→ {output}/gate_report.json"
        )
        gc.collect()
        if exit_code:
            raise SystemExit(exit_code)

    asyncio.run(gate_main())
    gc.collect()


# --- OpenHands container management ---


# Resolve compose.yaml relative to the project root (same directory as this file).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_COMPOSE_FILE = _PROJECT_ROOT / "compose.yaml"


@app.command(name="openhands-start")
def openhands_start() -> None:
    """Start the OpenHands Agent Server container."""
    subprocess.run(
        ["docker", "compose", "-f", str(_COMPOSE_FILE), "up", "-d"],
        check=True,
    )
    console.print("[green]OpenHands container started on port 3005[/green]")


@app.command(name="openhands-stop")
def openhands_stop() -> None:
    """Stop the OpenHands Agent Server container."""
    subprocess.run(
        ["docker", "compose", "-f", str(_COMPOSE_FILE), "down"],
        check=False,
    )
    console.print("[yellow]OpenHands container stopped[/yellow]")


@app.command(name="openhands-status")
def openhands_status() -> None:
    """Check OpenHands container status."""
    result = subprocess.run(
        ["docker", "compose", "-f", str(_COMPOSE_FILE), "ps", "--format", "json"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        console.print(result.stdout)
    else:
        console.print("[red]OpenHands container not running[/red]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()