# Design: `superApp gate` (evaluation / regression-gating layer)

See `proposal.md` for motivation and `specs/` for the requirements this
design satisfies. This document covers HOW.

## Context

The scripted 4-phase pipeline (`source_analyzer` → `data_generator` →
`test_runner` → `log_monitor`) is deterministic and code-graded, but
single-trial: one pass, no CI, no baseline, no cost. The gate reuses the
already-working deterministic runner (`test_runner` + `log_monitor`) and wraps
it in a trial loop + statistics + cost capture. No new external dependencies;
we reuse `httpx` (already a dep) and stdlib. `TestRunner` and `LogMonitor`
are reused as-is; `DataGenerator` is NOT used in gate mode.

Existing symbols to lean on: `Pipeline` (orchestrator), `TestRunner.run_form_tests`,
`LogMonitor`, and the OpenAI-compatible `httpx` call pattern already in
`data_generator.py` (reused by the LLM-judge grader).

## Goals / Non-Goals

**Goals**
- A `superApp gate` command that is CI-native (exit 0/1/2) and machine-readable.
- Statistical regression gating (Wilson CI vs. baseline) that ignores single-run
  noise.
- Cost/latency as a first-class per-task metric.
- A curated, versioned task suite as the canonical gate input.
- Purely additive: leave `run`/`analyze`/`generate`/agent-mode untouched.

**Non-Goals**
- `superApp ab` (A/B model/prompt) — interface kept open (grader + trial engine
  are reusable), but not implemented.
- LLM-judge calibration on a human-labeled slice (judge grader ships, off by
  default).
- Production/online monitoring.
- Adopting external eval tooling (Promptfoo/DeepEval/Langfuse).

## Decisions

### D1 — Reuse the deterministic runner; skip `DataGenerator` in gate mode
The gate feeds the runner **fixed** per-task data instead of LLM-generated data.
- **Why:** repeatability/comparability across model/prompt changes — the whole
  point of a regression baseline. LLM data-gen introduces nondeterminism.
- **Alternatives considered:** (a) reuse `DataGenerator` — rejected (nondeterministic
  inputs defeat baseline comparison); (b) generate once and cache — rejected (still
  not a curated, versioned, reviewable suite).

### D2 — Wilson 95% CI, gate on interval non-overlap (not point-estimate delta)
Use the Wilson score interval (z=1.96) for per-task success rate; flag regression
only when the current CI does not overlap the baseline.
- **Why:** Wilson handles small N (5–10) better than the normal approximation and
  stays finite at observed rate 0/1. Gating on CI non-overlap means the gate is
  robust to single-run noise — it only blocks on *significant* regression.
- **Alternatives:** normal-approx CI (unstable at small n/edge rates), exact
  binomial (heavier, near-identical verdicts here). Chosen Wilson for simplicity
  + stability.

### D3 — Baseline is a stored `gate_report.json`
`save_baseline` writes the previous report; `load_baseline` reads it; a missing
or corrupt baseline path → the run establishes the baseline (exit 0) or exits 2
(corrupt).
- **Why:** keeps the whole layer self-contained in the existing `superApp_output/`
  dir; optionally checked in for the canonical suite. No new store required.
- **Alternatives:** a separate baseline DB — rejected (overkill; JSON is enough).

### D4 — Grader protocol with two implementations
`Grader.grade(trial) -> GradeResult(passed, score, detail)`.
- `ScriptedGrader`: wraps the runner's step pass/fail + error-indicator
  assertions; zero LLM calls. Default.
- `LlmJudgeGrader`: compact rubric + trial transcript → structured yes/no + 0–1,
  via the OpenAI-compatible httpx pattern reused from `data_generator.py`. Uses a
  **separate `judge:` config block** (independent model/endpoint) to avoid
  self-preference bias. Off by default in gate runs.
- **Why:** keeps CI cheap/deterministic by default; optional richer quality
  grading on a "quality slice" without coupling the judge to the model under test.

### D5 — Cost capture wraps only LLM-judge traffic
In gate mode the runner is LLM-free, so the only LLM traffic is from LLM-judge
graders. `cost_tracker` records tokens_in/out, LLM call count, wall-clock
latency, tool-call count (runner step count), and estimated $ from a
configurable rate table (default 0 = instrumented, not priced).
- **Why:** honest accounting — we don't fabricate token counts for a
  deterministic run. Cost is orthogonal to the pass/fail verdict.
- **Alternatives:** a global tracing middleware — rejected (scope; per-call
  capture in the judge grader is sufficient for the pitch artefact).

### D6 — New modules; additive pipeline/CLI wiring
New: `src/graders.py`, `src/stat_gate.py`, `src/cost_tracker.py`, `tasks/*.yaml`.
Additive: `Pipeline.run_gate(suite_dir, n_trials, baseline_path, cost_gate)` and
a `gate` Typer subcommand. No edits to existing phases or existing CLI flags.
- **Why:** the gate is a new consumer of the existing runner; isolating the new
  logic in new modules means zero blast radius on the working scripted/agent flow
  and on the LEF `superApp` public contract.

### D7 — JUnit XML for CI-native reporting
Emit one `<testsuite>` per task, one `<testcase>` per trial.
- **Why:** most CI systems ingest JUnit natively without extra tooling.

## Risks / Trade-offs

- [Reused `TestRunner` is async Playwright and needs a live browser + reachable
  target] → gate runs require the same Playwright install + reachable target as
  scripted mode; document this in the command's preconditions.
- [Small N (5–10) gives wide CIs] → a small regression may not clear the CI and
  won't block; acceptable by design (gate on *significant* regression). Note the
  trade-off in `gate_report.md`.
- [Corrupt / schema-drifted baseline] → `load_baseline` validates the schema and
  returns an infra error (exit 2) with a clear message, rather than silently
  comparing against stale data.
- [LLM-judge grader adds latency + cost] → off by default; only enabled tasks pay
  for it, and cost is itself captured by D5.
- [OpenHands/agent-mode version drift (1.30.0 vs 1.49.2) is separate] → out of
  scope for this change; gate is scripted/LLM-free and does not depend on it.

## Migration Plan

- Additive only: no data migration. New artifacts land under the existing
  `--output` dir (`superApp_output/`). `run_test.sh` gets an optional
  `SUPERAPP_MODE=gate` passthrough; existing `SUPERAPP_DRY_RUN`/`SUPERAPP_MAX_PAGES`
  behavior is unchanged. Rollback = remove the new modules + `gate` command; the
  4-phase flow is untouched.

## Open Questions

- Where to persist the canonical checked-in baseline (in-repo under
  `superApp_output/` vs. a dedicated `baselines/` dir) — does not change specs,
  approach, or task breakdown; default to `superApp_output/` and decide at
  implementation.
