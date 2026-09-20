# cost-tracking Specification

Behavior contract for treating cost and latency as first-class, per-task
metrics reported alongside quality.

## ADDED Requirements

### Requirement: Per-Task Cost Capture

The system SHALL record, for each task and for the overall run, the following
cost/latency metrics: tokens in, tokens out, LLM call count, wall-clock
latency, tool-call count, and an estimated cost. The estimated cost SHALL be
derived from a configurable rate table; when no rate is configured the field
SHALL be reported as instrumented-but-not-priced (a neutral default of 0).

#### Scenario: Metrics captured for a run

- **WHEN** a gate run completes
- **THEN** each task's report entry includes token-in, token-out, LLM-call
  count, latency, tool-call count, and estimated-cost fields
- **AND** a `cost.json` artifact is written to the output directory

#### Scenario: Cost merged into gate report

- **WHEN** a gate run completes
- **THEN** cost metrics are merged into `gate_report.json` so a single artifact
  carries both quality and cost

### Requirement: Cost Is a First-Class Metric

The system SHALL report cost/latency alongside success rate (not as a post-hoc
add-on) and SHALL support an optional cost-gate that fails the run when a
task-declared cost/latency threshold is breached.

#### Scenario: Cost gate triggers on threshold breach

- **WHEN** a task declares a cost/latency limit and a trial exceeds it
- **AND** the cost-gate behavior is active
- **THEN** the run reports the breach and the gate fails on the cost dimension

#### Scenario: Cost gate off by default

- **WHEN** a gate run is invoked without the cost-gate option
- **THEN** cost breaches are reported but do not fail the run

## Constraints

- In gate mode the deterministic runner is LLM-free (fixed task data), so the
  only LLM traffic that can be captured is from any LLM-judge graders enabled
  for a task. Cost capture MUST account for this and report zero LLM traffic for
  purely scripted tasks.
- Cost capture MUST NOT change the pass/fail verdict of a trial; it is an
  orthogonal metric.
