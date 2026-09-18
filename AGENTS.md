# AGENTS.md — AI Agent Guide for super-eval-test (SuperApp)

Guidance for AI coding agents working in this repository. Read this first; the README has full user-facing docs.


## Introduction

**AI-driven E2E web application testing pipeline.** Analyzes source code, generates realistic test data, runs browser automation, and correlates results with server logs.

## What This Project Is

`super-eval-test` ("SuperApp") is an **AI-driven E2E web app testing pipeline** in Python 3.12+. It analyzes a target app's source code, generates realistic test data (LLM with deterministic template fallback), runs Playwright browser tests, and correlates results with server logs.

Two execution modes:
- **`scripted`** (default): deterministic 4-phase pipeline — `source_analyzer` → `data_generator` → `test_runner` → `log_monitor`
- **`agent`**: delegates to an OpenHands Agent Server (Docker, port 3005) via a REST client, using 3 sequential conversations (analyze → test → report)

SuperApp is the **UAT node** in the external Loop Engineering Factory (LEF) self-improving loop. LEF shells out to `superApp run`; both systems share one OpenHands agent-server container and one LLM endpoint.

## Repository Layout

```
src/
  cli.py            Typer CLI (entry point `superApp`; commands: run, analyze, generate, openhands-start/stop/status)
  pipeline.py       Pipeline orchestrator (scripted | agent modes)
  source_analyzer.py  Phase 1: extracts form schemas, routes, validators from source (regex + pydantic)
  data_generator.py   Phase 2: LLM test data generation (OpenAI-compatible API), template fallback
  test_runner.py      Phase 3: Playwright (async) browser automation
  log_monitor.py      Phase 4: server log correlation (docker | file | journalctl)
  openhands_client.py OpenHands Agent Server REST client (httpx, polls conversation events)
  constants.py      Shared defaults (LLM URL/model)
compose.yaml        OpenHands Agent Server container (image ghcr.io/openhands/agent-server:1.30.0-python)
run_test.sh         Automated setup+run script; all settings overridable via SUPERAPP_* env vars
config.example.yaml Config template (config.yaml is gitignored — copy from example)
tools/mermaid-cli/  Local pnpm install of @mermaid-js/mermaid-cli (renders docs/diagrams/*.mmd → .svg)
docs/diagrams/      Mermaid + Archify architecture diagrams
```

## How to Build / Run / Test

```bash
pip install -e .        # must re-run after pulls — resolves the `superApp` entry point
superApp run --target http://localhost:8081 --source /path/to/source   # full pipeline
superApp run --source /path/to/source --dry-run                         # analysis only
playwright install       # only needed for scripted mode
docker compose -f compose.yaml up -d   # only needed for agent mode
curl -s http://localhost:3005/health   # verify OpenHands is healthy
./run_test.sh            # automated setup + run (SUPERAPP_* env overrides)
```

No test suite is currently present. `pyproject.toml` declares optional `dev` deps (`pytest`, `pytest-asyncio`), and CodeGraph reports no covering tests for any pipeline symbol. If you add tests, put them where pytest discovers them and run with `pytest`.

## Conventions & Architecture Notes

- **Python 3.12+**; all modules use `from __future__ import annotations`. Pydantic models for data structures (schemas, test records, datasets); dataclasses in `test_runner`/`log_monitor`.
- The CLI name `superApp` is a **public contract** — LEF invokes it by name. Do not rename the command or its flag surface without coordinating with LEF. LEF passes `superApp_mode` through its graph state.
- **LLM defaults** live in `src/constants.py`: `http://localhost:8080` + `Qwen3.6-27B` (OpenHands variant prefix: `openai/Qwen3.6-27B`). Override via `--llm-url`/`--llm-model`, `config.yaml`, or env in `compose.yaml`. The LLM must be reachable *from the host* (or from the container via `host.docker.internal`).
- **OpenHands version pin**: tested against Agent Server **v1.30.0**. `openhands_client.py` uses a hand-rolled REST client (conversation events polling + REST file ops) because no SDK is available; it expects agent tool names `terminal`, `file_editor`, `write_file`, `read_file`, `edit`, `glob`, `grep`, `list_directory`. Newer OpenHands versions may need payload alignment there.
- **Docker networking**: `compose.yaml` joins the *external* network `loop_factory_loop_factory_network` (shared with LEF's BUILD subgraph) and sets `extra_hosts: host.docker.internal:host-gateway`. Target URLs for agent mode must use `http://host.docker.internal:<port>` so the in-sandbox agent can reach host services.
- **Data flow / artifacts** (written under the `--output` dir, default `./superApp_output`):
  - `data/schemas.json` (phase 1) → `data/test_data.json` (phase 2) → `data/test_results.json` (phase 3) → `logs/correlation_report.json` (phase 4); `artifacts/` for screenshots/DOM; `agent_report.json` in agent mode.
- Git URLs passed to `--source` are cloned into `<output>/source/` automatically (see `resolve_source` in `cli.py`).
- `workspace/` is the host dir mounted into the OpenHands container as `/opt/workspace_base`. Crashed runs can leave **root-owned** files there; cleanup may need `sudo rm -rf workspace/source workspace/artifacts`.

## Gotchas

- Reinstall (`pip install -e .`) after pulling — the `superApp` entry point may not resolve otherwise.
- Agent mode with 0 actions from the agent = LLM unreachable from the container; check `LLM_BASE_URL` env (must be an IP/path reachable from Docker, not a bare hostname).
- `config.yaml` is gitignored; never commit real config, use `config.example.yaml` as the template.
- `report/`, `.codegraph/`, `.state/`, `node_modules/`, `workspace/` are all gitignored local-tooling artifacts — don't commit them.
- `tools/mermaid-cli/node_modules` is a vendored pnpm install; use it (via `mmdc`) to regenerate `docs/diagrams/*.svg` rather than installing new tooling.

## CodeGraph

This repo is indexed by CodeGraph (`.codegraph/` exists). Prefer `codegraph explore "<symbols or question>"` over grep/find when locating code or checking blast radius — it returns line-numbered source plus call paths, and flags which symbols have (or lack) test coverage.
