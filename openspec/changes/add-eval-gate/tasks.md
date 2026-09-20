# Tasks: `superApp gate` evaluation layer

Dependency-ordered. Each task states how to verify it. Specs at
`specs/`, design decisions at `design.md`.

## 1. Statistical core (`src/stat_gate.py`)

- [ ] 1.1 Implement `wilson_ci(p, n, z=1.96)` and `trial_success_rate(n_passed, n_trials)`; add unit tests with known-value vectors (p=0.5 symmetry, p=0 and p=1 edge finiteness) and verify `pytest tests/test_stat_gate.py` passes.
- [ ] 1.2 Implement `compare_to_baseline(current, baseline)` returning per-task `regressed` / `improved` / `unchanged` + overall verdict (any regressed → FAIL); add unit tests covering regression, improvement, within-noise, and no-baseline (establish) cases and verify they pass.
- [ ] 1.3 Implement `load_baseline(path)` / `save_baseline(report, path)` with schema validation; add a round-trip test plus a corrupt-file → infra-error test and verify `pytest tests/test_stat_gate.py` passes.

## 2. Cost tracking (`src/cost_tracker.py`)

- [ ] 2.1 Add `CostTracker` capturing per-task + run-wide tokens_in/out, LLM call count, wall-clock latency, tool-call count, and estimated $ from a configurable rate table (default 0 = instrumented, not priced); verify a unit test asserts all fields are present in the emitted structure.
- [ ] 2.2 Emit `cost.json` and merge cost metrics into the gate report structure; verify a unit test confirms one artifact carries both quality and cost fields.

## 3. Graders (`src/graders.py`)

- [ ] 3.1 Define the `Grader` protocol (`grade(trial) -> GradeResult(passed, score, detail)`) and `ScriptedGrader` (pass when all runner steps passed and no error-indicator assertion fired; zero LLM calls); verify a unit test confirms a fully-passed trial grades pass and a failed trial grades fail.
- [ ] 3.2 Add `LlmJudgeGrader` reusing the OpenAI-compatible httpx pattern from `data_generator.py`, targeted at a separate `judge:` config block; verify a unit test (mock HTTP) confirms the judge request goes to the judge config, not the model-under-test config, and that the grader is off by default.

## 4. Task suite format (`tasks/*.yaml`)

- [ ] 4.1 Implement the task-suite loader (parse `tasks/*.yaml`: name, `form`, fixed `data`, optional `graders`, optional `cost_limits`; treat files as data, reject self-generated inputs); verify a unit test loads the initial 3-task suite (happy / boundary / special-chars) and a malformed task raises an infra error.
- [ ] 4.2 Author the initial curated suite: `tasks/` with a happy-path task, a boundary task, and a special-chars task (fixed inputs mirroring the `data_generator` archetypes); verify each file parses and its `form` maps to a source-analyzer form name.

## 5. Pipeline wiring (`src/pipeline.py`, additive)

- [ ] 5.1 Add `Pipeline.run_gate(suite_dir, n_trials, baseline_path, cost_gate)` that: loads the suite, runs each task × trial through the existing `TestRunner`+`LogMonitor` with fixed task data (no `DataGenerator`), grades each trial, aggregates per-task rates + Wilson CIs + cost, compares to baseline if present, and writes `gate_report.json` / `gate_report.md` / JUnit XML; verify an integration test against a tiny stub target produces a well-formed `gate_report.json` and JUnit XML.
- [ ] 5.2 Map results to the exit contract (0 pass / baseline-established; 1 significant regression when fail-on-regression active; 2 infra error); verify integration tests assert exit codes 0/1/2 across pass, regression (with and without fail-on-regression), and unreachable-target cases.

## 6. CLI + config (`src/cli.py`, `config.example.yaml`)

- [ ] 6.1 Add the `superApp gate` command with `--target`, `--source`, `--suite`, `--n` (default 7, enforce 5–10), `--baseline`, `--fail-on-regression`, `--cost-gate`, `--output`; verify `superApp gate --help` lists all flags and confirms existing `run`/`analyze`/`generate`/agent commands and flags are unchanged.
- [ ] 6.2 Add an optional `judge:` LLM block and a cost rate-table default to `config.example.yaml`; verify the example parses and a gate run with no `judge:` configured uses `ScriptedGrader` only.
- [ ] 6.3 Add an optional `SUPERAPP_MODE=gate` + `SUPERAPP_N` passthrough to `run_test.sh`; verify `SUPERAPP_MODE=gate` invokes the gate command and existing env vars still work.

## 7. Verification & artefacts

- [ ] 7.1 Run the full gate suite end-to-end against the loop_factory app with N=7 and a checked-in baseline; verify the produced `gate_report.md` + exit code (the "worked eval run" artefact) render correctly and JUnit XML is well-formed.
- [ ] 7.2 Run `openspec validate add-eval-gate` and confirm all four artifacts validate; verify `openspec status --change add-eval-gate` reports all artifacts complete.

## Out of scope (interface kept open, not built)

- `superApp ab` (model/prompt A/B): same engine + a candidate abstraction + pairwise CI — stub only.
- LLM-judge calibration on a human-labeled slice.
- Production/online monitoring.
