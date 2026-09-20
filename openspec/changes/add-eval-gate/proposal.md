## Why

The repo is a **testing-first harness missing its evaluation layer**. The scripted
4-phase pipeline (source_analyzer → data_generator → test_runner → log_monitor)
produces deterministic, code-based verdicts, but there is no statistical layer:
no N-trial runs, no confidence intervals, no baseline, no per-task success rate,
no cost/latency tracking, and no CI-blocking exit contract. This is confirmed in
`report/agentic-eval-opportunity.md`: `superApp gate` and its supporting modules
(`graders.py`, `stat_gate.py`, `cost_tracker.py`, `tasks/`) are not implemented.
We now add that evaluation layer so the existing, working pipeline becomes a
regression-gated, cost-instrumented quality gate — the prerequisite for model/prompt
A/B selection (deferred) and production monitoring (out of scope).

## What Changes

- New `superApp gate` CLI command that runs a **curated task suite** N times
  (default 7, range 5–10) against a target app and emits a CI-native verdict.
- **Statistical regression gate**: per-task success rate over N trials compared
  to a stored baseline using a **Wilson 95% CI**; the gate blocks only on
  **significant regression** (CI non-overlap), never single-run noise.
- **Cost/latency as a first-class metric**: tokens-in/out, LLM call count,
  wall-clock latency, tool-call count, and estimated $ tracked per task and
  reported alongside success rate.
- **Curated task suite** (`tasks/*.yaml`) as the canonical, versioned input
  source for gate runs — fixed inputs (no LLM data generation), making runs
  comparable across model/prompt changes.
- **Grader abstraction**: `ScriptedGrader` (existing pass/fail, no LLM) and
  `LlmJudgeGrader` (optional, separate `judge:` LLM config to avoid
  self-preference bias).
- **Exit contract (CI-native)**: 0 = pass / baseline established; 1 =
  significant regression (with `--fail-on-regression`); 2 = infra error.
- Machine-readable + human-readable artifacts: `gate_report.json`,
  `gate_report.md`, optional JUnit XML.
- `run_test.sh` gains an optional `SUPERAPP_MODE=gate` passthrough.

Non-breaking: existing `run` / `analyze` / `generate` / agent-mode and the public
`superApp` command/flag surface are unchanged (LEF contract preserved). No changes
to the existing 4-phase scripted flow.

## Capabilities

### New Capabilities
- `gate-run`: The `superApp gate` command — suite loading, N-trial execution of
  the existing deterministic runner, per-task grading, and a CI-native exit
  contract (0/1/2).
- `regression-gating`: Statistical layer — per-task success rate, Wilson 95%
  confidence interval, and baseline load/save/compare that flags significant
  regression or improvement.
- `cost-tracking`: Per-task cost/latency instrumentation (tokens, LLM calls,
  latency, tool-call count, estimated cost) emitted alongside quality metrics.
- `task-suite`: Curated, versioned task input format (`tasks/*.yaml`) defining
  fixed data + graders + optional cost limits, and the grader abstraction that
  grades each trial.

### Modified Capabilities
<!-- None. No existing spec-level behavior changes; this is a pure add-on. -->
<!-- (There is no openspec/specs/ yet; the existing pipeline is described in
  docs only. The gate is additive and does not alter scripted/agent behavior.) -->

## Impact

- **New code**: `src/graders.py`, `src/stat_gate.py`, `src/cost_tracker.py`,
  `tasks/*.yaml` (initial suite).
- **Modified code (additive only)**: `src/pipeline.py` (new `run_gate()` + suite
  loader), `src/cli.py` (new `gate` command). No edits to existing phases.
- **Config**: `config.example.yaml` gains an optional `judge:` LLM block and a
  cost rate-table default (0 = instrumented, not priced).
- **Artifacts (output dir)**: `gate_report.json`, `gate_report.md`, `cost.json`,
  optional JUnit XML.
- **Dependencies**: none added (reuses `httpx` + stdlib). Playwright already
  required for the scripted runner the gate reuses.
- **Out of scope (kept open)**: `superApp ab` (A/B), LLM-judge calibration,
  production/online monitoring.
