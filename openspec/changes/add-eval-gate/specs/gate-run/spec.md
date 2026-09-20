# gate-run Specification

Behavior contract for the `superApp gate` command: running a curated task suite
N times through the existing deterministic runner and producing a CI-native
verdict.

## ADDED Requirements

### Requirement: Gate Command

The system SHALL provide a `superApp gate` command that accepts a target app
URL, a source path, a task-suite directory, a trial count, and an optional
baseline report path, runs the suite, and returns a CI-native exit code.

The command SHALL NOT invoke LLM-based test data generation; gate runs use the
fixed inputs declared in task files only.

#### Scenario: Basic gate run with a suite

- **WHEN** the operator runs `superApp gate --target URL --source PATH --suite tasks/ --n 7`
- **THEN** the command executes every task in `tasks/` 7 times, grades each
  trial, aggregates results, and writes a `gate_report.json` and
  `gate_report.md` to the output directory
- **AND** the process exits with code 0 when no significant regression is found
  and a baseline is not required, or establishes the baseline when none is
  provided

#### Scenario: Missing suite directory is an infra error

- **WHEN** the `--suite` path does not exist or contains no parseable task files
- **THEN** the command exits with code 2 without running trials
- **AND** it prints a diagnostic naming the missing or malformed suite

### Requirement: Trial Count Bounded

The system SHALL accept a trial count `N` and enforce a range of 5 to 10
inclusive, defaulting to 7 when the operator omits it.

#### Scenario: Default trial count

- **WHEN** the operator runs `superApp gate` without `--n`
- **THEN** each task runs 7 times

#### Scenario: Out-of-range trial count rejected

- **WHEN** the operator passes `--n 4` or `--n 12`
- **THEN** the command exits with code 2 and reports that `--n` must be 5–10

### Requirement: CI-Native Exit Contract

The system SHALL return one of three exit codes for a gate run:
`0` for pass or baseline-established, `1` for a significant regression when the
fail-on-regression behavior is active, and `2` for an infrastructure error.

#### Scenario: Significant regression blocks the build

- **WHEN** a baseline exists and at least one task's current success-rate CI
  indicates a significant regression
- **AND** the fail-on-regression behavior is active (default in CI)
- **THEN** the command exits with code 1

#### Scenario: Regression detected without failing

- **WHEN** a significant regression is detected but the operator requests a
  report-only run
- **THEN** the command still writes the report but exits with code 0

#### Scenario: Unreachable target is an infra error

- **WHEN** the target app URL cannot be reached at the start of a gate run
- **THEN** the command exits with code 2

### Requirement: Machine-Readable and Human-Readable Artifacts

The system SHALL write a machine-readable `gate_report.json` (tasks, per-trial
results, success rates, confidence intervals, baseline diff, verdict, and cost
metrics) and a human-readable `gate_report.md` (a table of task, current vs.
previous rate, CI, regressed/improved/unchanged, and cost delta) to the output
directory. It SHALL additionally emit optional JUnit XML with one suite per
task and one test case per trial.

#### Scenario: Reports emitted after a run

- **WHEN** a gate run completes
- **THEN** `gate_report.json`, `gate_report.md`, and JUnit XML are present in
  the output directory
- **AND** the JUnit XML is well-formed with one `<testsuite>` per task and one
  `<testcase>` per trial

## Constraints

- This command MUST NOT change the behavior of the existing `run`, `analyze`,
  `generate` commands or agent mode.
- The public `superApp` command name and existing flag surface are preserved
  unchanged.
