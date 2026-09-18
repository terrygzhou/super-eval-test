# Design: `suet gate` — Regression Quality Gating + Task Suite + Cost Tracking

Date: 2026-09-18
Status: draft
Reference: `report/agentic-eval-opportunity.md`, obsidian note `Agentic/2026-09-16-testing-vs-evaluation-ai-agentic-engineering.md`

## 1. Goal

Add a statistical regression gate to the existing deterministic pipeline:

- A **curated task suite** (versioned, repeatable) replaces per-run LLM data
  generation as the canonical input source.
- Each task is executed **N times** (default 7, configurable 5–10).
- **Per-task success rate** is compared against a stored **baseline** using a
  Wilson 95% confidence interval. The gate blocks only on **significant
  regression** (delta outside CI), never on single-run noise.
- **Cost/latency** (tokens, latency, tool-call count, estimated $) is
  tracked per task and reported alongside success rate — a first-class
  metric, not a post-hoc add-on.
- The command emits a **CI contract**: exit codes + machine-readable reports.

Deferred (interface kept open, not implemented): `suet ab` (model/prompt
A/B — same engine, pairwise CI between two candidates). Out of scope:
production/online monitoring.

## 2. CLI

```bash
suet gate \
  --target http://localhost:8081 \
  --source /path/to/source \
  --suite tasks/ \
  --n 7 \
  --baseline ./suet_output/baseline.json \
  [--fail-on-regression] \
  [--cost-gate] \
  [--output ./suet_output]
```

- `--suite`: directory of task YAML files (required; the canonical input
  source for gate runs — no LLM data generation in gate mode).
- `--n`: trials per task (default 7; range 5–10 per note §2.3).
- `--baseline`: prior gate report to compare against. If missing, the run
  **establishes** the baseline and exits 0 (no verdict possible).
- `--fail-on-regression`: exit 1 when a significant regression is detected
  (default true in CI; flag exists for local runs that only want the report).
- `--cost-gate`: additionally fail when a cost/latency threshold in the task
  definition is breached.

### Exit contract (CI-native)

| Exit | Meaning |
|---|---|
| 0 | Pass, or baseline-established run |
| 1 | Significant regression (and `--fail-on-regression` set) |
| 2 | Infra error (target unreachable, suite malformed, baseline corrupt) |

## 3. Task suite format

`tasks/*.yaml` — one file per task, versioned in-repo:

```yaml
name: create-project-happy
description: "Create a project with valid data; expect success page"
form: CreateProjectForm          # maps to source_analyzer form name
data:                           # fixed, curated inputs (NOT LLM-generated)
  name: "Test Project"
  owner: "terry@example.com"
graders:
  - type: scripted              # default: existing TestRunner step pass/fail
  - type: llm-judge             # optional, on a smaller "quality slice"
    rubric: "response is a coherent success confirmation; no error leakage"
cost_limits:                    # optional; enforced by --cost-gate
  max_tokens_out: 4000
  max_latency_s: 120
```

Rules:

- `graders` defaults to `[scripted]` only — keeps CI cheap and
  deterministic-leaning, per the note's CI discipline. LLM-judge tasks are
  marked and run on the "quality slice," not the whole suite every CI run.
- Task files are **data, not code**: a task never generates its own inputs.
  This is what makes runs comparable across model/prompt changes.

## 4. Components

### 4.1 `src/graders.py` (new)

- `Grader` protocol: `grade(trial_result) -> GradeResult(passed: bool,
  score: float | None, detail: str)`.
- `ScriptedGrader` — wraps the existing `TestRunResult` step status (pass if
  all steps passed and no error-indicator assertion fired). No LLM calls.
- `LlmJudgeGrader` — sends a compact rubric + trial transcript to the
  configured LLM endpoint; structured yes/no + 0–1 score. Reuses the
  OpenAI-compatible httpx pattern from `data_generator.py`. Judge model is
  a **separate config** (`judge:` block in config.yaml) so it can be kept
  independent of the model under test (note §2.2, self-preference bias).
- Per-task grader list is resolved from the task YAML.

### 4.2 `src/stat_gate.py` (new)

- `trial_success_rate(n_passed, n_trials)` — per-task rate.
- `wilson_ci(p, n, z=1.96)` — Wilson score interval (handles small n better
  than normal-approximation; standard for success-rate CIs).
- `compare_to_baseline(current, baseline)` — per task: flag
  `regressed` when the current CI does not overlap the baseline CI lower
  bound (i.e. significant drop), and `improved` symmetrically. Overall gate
  verdict: any task `regressed` → gate FAIL.
- `load_baseline(path)` / `save_baseline(report, path)` — baseline is the
  previous `gate_report.json` (success rates + CIs + cost metrics), stored
  under `suet_output/` and optionally checked in for the canonical suite.

### 4.3 `src/cost_tracker.py` (new)

- Wraps the LLM calls made during a gate run. In gate mode the scripted
  runner is LLM-free (fixed task data, no `DataGenerator`), so the only LLM
  traffic is **judge** traffic — and only when a task has an
  `llm-judge` grader enabled.
- Per task and per run: `tokens_in`, `tokens_out`, `llm_calls`,
  `latency_s` (wall clock for the trial), `tool_calls` (scripted runner
  step count), `estimated_cost_usd` (rate table in config, default 0 →
  "instrumented, not priced").
- Emits `cost.json` in the output dir and merges cost metrics into
  `gate_report.json` so one artifact carries both quality and cost
  (note §2.4: cost is a distinct use case, first-class alongside success
  rate).

### 4.4 Pipeline + CLI changes (bounded, existing files)

- `src/pipeline.py` — new `run_gate(suite_dir, n_trials, baseline_path,
  cost_gate)`:
  1. Load tasks from the suite.
  2. For each task × trial: run the scripted flow for that task's form using
     the **fixed** task data (reuses `TestRunner` + `LogMonitor`; no
     `DataGenerator`).
  3. Grade each trial (grader list from the task).
  4. Aggregate per-task rates + Wilson CIs; cost metrics from
     `cost_tracker`.
  5. If a baseline exists: compare; render verdict.
  6. Write `gate_report.json` (tasks, trials, rates, CIs, baseline diff,
     verdict, cost) + `gate_report.md` (table: task, rate now/prev, CI,
     regressed/improved/—, cost delta) + optional JUnit XML (one
  `<testsuite>` per task, trials as `<testcase>`) for CI systems that want
  native test reporting.
  7. Return the verdict; CLI maps to the exit contract.
- `src/cli.py` — new `gate` command (options per §2). No changes to
  existing `run` / `analyze` / `generate` commands.
- `tasks/` — initial suite: 3 tasks against the loop_factory app
  (happy path, boundary, special-chars — mirroring the existing
  `data_generator` variation scheme, but fixed).
- `run_test.sh` — optional `SUET_MODE=gate` + `SUET_N` env passthrough so
  the existing one-script entrypoint works in CI without new tooling.

## 5. What is deliberately NOT in scope

- `suet ab` — the design keeps the interface open (grader + trial engine is
  reusable; a future A/B adds a candidate abstraction: LLM endpoint/model
  override + pairwise CI). Stub only; no implementation.
- LLM-judge calibration (human-labeled slice) — noted as follow-up; the
  judge grader ships but is off by default in gate runs.
- Production/online monitoring — out of scope (no live traffic source).
- Promptfoo/DeepEval/Langfuse tooling — not adopted; the gap is
  statistics + gates, not tooling (see assessment §5).

## 6. Testing

- **Unit** (fast, no browser): Wilson CI math (known-value vectors),
  baseline load/save round-trip, regression/improvement/unchanged
  verdicts, task YAML parsing (valid + malformed → exit 2 path).
- **Integration** (stubbed target): gate command against a tiny FastAPI
  stub; verify `gate_report.json` schema, exit codes 0/1/2, JUnit XML
  well-formedness.
- **Manual validation target** (pitch artefact): N=7 gate run against
  loop_factory with a checked-in baseline; artefact is `gate_report.md` +
  exit code — the "worked eval run" the note asks for.

## 7. Files

| File | Change |
|---|---|
| `src/graders.py` | New — grader protocol + scripted + llm-judge |
| `src/stat_gate.py` | New — rates, Wilson CI, baseline compare, load/save |
| `src/cost_tracker.py` | New — token/latency/tool-call/cost capture |
| `src/pipeline.py` | Add `run_gate()` + suite loader; no changes to existing phases |
| `src/cli.py` | Add `gate` command |
| `tasks/*.yaml` | New — curated suite (3 tasks initially) |
| `run_test.sh` | `SUET_MODE=gate` passthrough (optional) |
| `report/agentic-eval-opportunity.md` | Done — assessment |
