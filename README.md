# SuperApp Test

**AI-driven E2E web application testing pipeline.** Analyzes source code, generates realistic test data, runs browser automation, and correlates results with server logs.

## Features

- **4-phase pipeline**: Source analysis → Data generation → Browser testing → Log correlation
- **Dual execution modes**:
  - `scripted` — Deterministic Playwright-based pipeline (default)
  - `agent` — OpenHands AI agent delegation (3-conversation workflow)
- **Source-aware test data**: Extracts form schemas, endpoints, and input validation rules from source code
- **Git-URL source**: `--source https://…` or `git@…` clones into `<output>/source/` automatically
- **LLM-powered generation**: Uses any OpenAI-compatible model (default: `Qwen3.6-27B` on `localhost:8080`), with deterministic template fallback when the LLM is unreachable
- **Structured output**: JSON results with timestamps, test data, and server log correlation
- **Loop Engineering Factory integration**: SuperApp is the UAT node inside LEF's self-improving loop — LEF shells out to `superApp run` and the two systems share one OpenHands agent-server and LLM endpoint

## Quick Start

```bash
# Install (reinstall after pulling — the `superApp` entry point must resolve)
pip install -e .

# Run full pipeline
superApp run --target http://localhost:8081 --source /path/to/source

# Or run from a git URL (cloned into <output>/source/)
superApp run --target http://localhost:8081 --source https://github.com/org/app.git

# Dry run (analysis only)
superApp run --source /path/to/source --dry-run

# Source analysis only
superApp analyze --source /path/to/source

# Generate test data from existing schemas
superApp generate --schemas data/schemas.json

# Automated setup + run (sets env defaults, starts OpenHands, runs pipeline)
./run_test.sh
```

## CLI Reference

```bash
# Main pipeline
superApp run \
  --target http://localhost:8081 \
  --source /path/to/source \
  --output ./superApp_output \
  --config config.yaml \
  --llm-url http://localhost:8080 \
  --llm-model Qwen3.6-27B \
  --variations 3 \
  --mode scripted \
  --agent-workspace /path/to/host/dir \
  --agent-timeout 600

# OpenHands container management
superApp openhands-start   # Start container on port 3005
superApp openhands-stop    # Stop container
superApp openhands-status  # Check status
```

| Option | Default | Notes |
|---|---|---|
| `--target` / `-t` | — | Required unless `--dry-run` |
| `--source` / `-s` | — | Local path **or** git URL; required |
| `--output` / `-o` | `./superApp_output` | Artifacts directory |
| `--config` / `-c` | none | Optional `config.yaml` |
| `--llm-url` / `--llm-model` | `http://localhost:8080` / `Qwen3.6-27B` | OpenAI-compatible endpoint |
| `--variations` / `-v` | 3 | Test data variations per form (1–5) |
| `--dry-run` | off | Analysis only |
| `--mode` | `scripted` | `scripted` \| `agent` |
| `--agent-workspace` | empty | Host dir mounted into the OpenHands container (agent mode) |
| `--agent-timeout` | 600 | Agent timeout in seconds |

## Architecture

```mermaid
graph LR
    subgraph CLI["CLI Layer"]
        USER[("User")]
        CLI_CLI["cli.py\nTyper CLI"]
    end

    subgraph CORE["Core Pipeline"]
        PIPE["pipeline.py\nOrchestrator\n(scripted | agent)"]
    end

    subgraph SCRIPTED["Scripted Mode"]
        P1["P1: source_analyzer.py\nForm/Route Extraction"]
        P2["P2: data_generator.py\nLLM Test Data Gen"]
        P3["P3: test_runner.py\nPlaywright E2E"]
        P4["P4: log_monitor.py\nLog Correlation"]
    end

    subgraph AGENT["Agent Mode"]
        OH_CLI["openhands_client.py\nREST Client"]
        OH_SRV["OpenHands Agent Server\n(Docker :3005)"]
        CONV["3 Conversations\n1.Analyze → schemas\n2.Test → results\n3.Report → JSON/MD"]
    end

    subgraph EXT["External Systems"]
        LLM["LLM Endpoint\n(vLLM / OpenAI)"]
        BROWSER["Playwright\nChromium"]
        TARGET[/"Target Web App"/]
        LOGS[/"Server Logs\n(Docker/file/journalctl)"]
    end

    USER -->|"superApp run"| CLI_CLI
    CLI_CLI -->|"delegates"| PIPE

    PIPE -->|"mode=scripted"| P1
    P1 --> P2
    P2 --> P3
    P3 --> P4

    PIPE -->|"mode=agent"| OH_CLI
    OH_CLI -->|"REST API"| OH_SRV
    OH_SRV --> CONV

    P1 -->|"reads source"| TARGET
    P2 -->|"schema → test data"| LLM
    P3 -->|"headless browser"| BROWSER
    P3 -->|"navigate/fill/submit"| TARGET
    P4 -->|"error patterns"| LOGS

    OH_SRV -->|"sandbox testing"| TARGET
    CONV -->|"test data gen"| LLM
```

Higher-level scenario views (standalone pipeline and LEF × SuperApp integration) live in [`docs/diagrams/`](docs/diagrams/):
- `superapp-standalone.mmd` / `.svg` — the 4-stage pipeline, Mermaid-rendered
- `lef-superapp-integrated.mmd` / `.svg` — the LEF loop with SuperApp as UAT node
- `*.workflow.json` / `.html` — interactive Archify versions of the same two diagrams

### Scripted Mode

Runs the 4-phase pipeline deterministically:
1. **Analyze** — Scans source code for forms, routes, and input schemas
2. **Generate** — Creates N test data variations per form via LLM (template fallback when the LLM is down)
3. **Test** — Executes Playwright browser tests with generated data
4. **Correlate** — Matches server logs to test results by time window

### Agent Mode
Delegates to OpenHands Agent Server via 3 sequential conversations sharing one workspace:
1. **Analyze** — AI examines source code and generates schemas + test data
2. **Test** — AI writes and runs Playwright tests
3. **Report** — AI compiles structured results

## Loop Engineering Factory Integration

SuperApp is the **UAT node** in the LEF self-improving loop (LangGraph: `DISCOVER → DEFINE → PLAN → ARCH_REVIEW → BUILD → SEED_DATA → VERIFY → SHIP → REFLECT`).

```
LEF cycle:
  DISCOVER → … → BUILD (OpenHands) → SEED_DATA → VERIFY ─┐
      ↑                                                    │
      └──────── REFLECT ←── SHIP ←────────────────────────┘
                                    │
                                    └─ superApp run (subprocess)
                                       agent mode → shared OpenHands container
```

Key integration points:

- **Subprocess call** — LEF's `VERIFY` node shells out to `superApp run …`; the `superApp` command name is part of the public contract (rename it and LEF breaks). LEF reads its own `superApp:` config key and passes `superApp_mode` (`scripted` \| `agent`) through its graph state.
- **Shared OpenHands agent-server** — LEF's BUILD subgraph and SuperApp's agent mode both delegate to the *same* `openhands-server` container on `loop_factory_loop_factory_network`, so builds and UAT runs share one agent workspace.
- **Shared LLM** — both systems pin to `Qwen3.6-27B` on `:8080` (host-gateway path from Docker).
- **Feedback loop** — SuperApp verdicts feed LEF's `REFLECT` node (`FeedbackAggregator` + `diff_engine`), which proposes config diffs — including the `superApp:` key — applied through a HIL gate on the next cycle.

See [`docs/diagrams/lef-superapp-integrated.svg`](docs/diagrams/lef-superapp-integrated.svg) for the full topology.

## Output

```
superApp_output/
├── data/
│   ├── schemas.json          # Extracted form schemas
│   ├── test_data.json        # Generated test data
│   └── test_results.json     # Browser test results
├── logs/
│   └── correlation_report.json  # Log correlation analysis
├── artifacts/              # Screenshots, DOM snapshots
└── agent_report.json       # Agent mode final report
```

## Requirements

### All Modes
- **Python 3.12+**
- **LLM endpoint** (OpenAI-compatible API). Default: `Qwen3.6-27B` on `http://localhost:8080`. Must be reachable from your host machine.

### Scripted Mode Only
- **Playwright** browsers: `playwright install`

### Agent Mode — OpenHands Container

Agent mode requires the **OpenHands Agent Server** container. It is managed via `compose.yaml` in this repo and spawns ephemeral sandbox containers inside the OpenHands runtime.

#### Prerequisites

| Requirement | Notes |
|---|---|
| Docker & Docker Compose v2 | Container runtime + compose orchestration |
| Docker-in-Docker | OpenHands mounts `/var/run/docker.sock` to spawn sandbox containers |
| Accessible LLM | `LLM_BASE_URL` + `LLM_MODEL` env vars on the container (default: `Qwen3.6-27B` on host-gateway `:8080`) |
| `loop_factory_loop_factory_network` | External Docker network; the container joins it so it shares an agent-server with LEF's BUILD subgraph |

#### Quick Setup

```bash
# 1. LLM endpoint is configured in compose.yaml environment vars:
#    - LLM_BASE_URL=http://host.docker.internal:8080
#    - LLM_MODEL=Qwen3.6-27B
#
# 2. Start the OpenHands container:
docker compose -f compose.yaml up -d
#
# 3. Verify it is healthy:
curl -s http://localhost:3005/health
# → {"status":"ok"}
#
# 4. Run the pipeline in agent mode:
python3 -m src.cli run --target http://host.docker.internal:8081 \
  --source /path/to/source --output ./superApp_test \
  --mode agent --agent-timeout 3600
#
# 5. Stop when done (optional — pipeline auto-stops):
docker compose -f compose.yaml down
```

#### How It Works

The `compose.yaml` mounts:
- `~/.openhands` → persistent agent data (SQLite, sessions)
- `./workspace/` → source code workspace (mounted as `/opt/workspace_base` inside the container)
- `/var/run/docker.sock` → Docker socket for sandbox container spawning

The `extra_hosts` entry (`host.docker.internal:host-gateway`) allows the OpenHands container to reach the target application running on your host machine. **Use `http://host.docker.internal:<port>` as your `--target` URL** so the agent can reach it from inside the sandbox.

#### Supported OpenHands Versions

Tested with **OpenHands Agent Server v1.30.0**. Newer versions may require payload alignment in `src/openhands_client.py`. The agent uses these tool names: `terminal`, `file_editor`, `write_file`, `read_file`, `edit`, `glob`, `grep`, `list_directory`.

#### Troubleshooting

| Symptom | Fix |
|---|---|
| `Connection refused` on `http://localhost:3005` | Container not running. Run `docker compose -f compose.yaml up -d`. |
| Agent finishes with 0 actions | LLM not reachable from inside the container. Verify `LLM_BASE_URL` env var points to an IP reachable from Docker (e.g., host-gateway). |
| `PermissionError` on workspace cleanup | Root-owned artifacts from a crashed prior run. Run `sudo rm -rf workspace/source workspace/artifacts`. |
| Agent can't reach target URL | Target URL resolves to IPv6 or loopback from inside the container. Use `http://host.docker.internal:<port>`. |

## Config (Optional)

Create `config.yaml` for persistent settings (see [`config.example.yaml`](config.example.yaml)):

```yaml
target:
  url: "http://localhost:8081"
  scan_paths: ["/", "/login", "/register"]

source:
  root: "/path/to/source"
  form_patterns: ["**/forms.py", "**/schemas.py", "**/models.py"]
  route_patterns: ["**/routes.py", "**/api.py"]

llm:
  base_url: "http://localhost:8080"
  model: "Qwen3.6-27B"

browser:
  headless: true
  timeout_ms: 30000
  viewport:
    width: 1280
    height: 720

logs:
  type: "docker"            # docker | file | journalctl
  docker_container: "myapp"
  error_patterns:
    - "ERROR"
    - "Exception"
    - "Traceback"

pipeline:
  data_variations: 3
  max_pages: 3
```

## Repository Layout

```
src/                  CLI + pipeline modules (Typer app `superApp`)
compose.yaml          OpenHands agent-server container
run_test.sh           Automated setup & run script (SUPERAPP_* env overrides)
config.example.yaml   Configuration template
tools/mermaid-cli/    Local pnpm install of @mermaid-js/mermaid-cli
                      (used to render docs/diagrams/*.mmd → .svg)
docs/diagrams/        Architecture diagrams (Mermaid .mmd/.svg + Archify .json/.html)
report/               Test reports (gitignored)
```

## License

MIT
