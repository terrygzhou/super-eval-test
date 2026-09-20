# regression-gating Specification

Behavior contract for the statistical layer: per-task success rate over N
trials, Wilson confidence intervals, and baseline comparison that gates on
significant regression rather than single-run noise.

## ADDED Requirements

### Requirement: Per-Task Success Rate

The system SHALL compute, for each task, a success rate as the fraction of
trials whose grading result is a pass, over the configured trial count N.

#### Scenario: Partial success rate

- **WHEN** a task passes 5 of 7 trials
- **THEN** its success rate is reported as 0.714 (5/7)

#### Scenario: All or nothing

- **WHEN** a task passes all N trials, or passes none
- **THEN** its success rate is 1.0 or 0.0 respectively

### Requirement: Wilson Confidence Interval

The system SHALL compute a 95% Wilson score confidence interval for each task's
success rate, using a z of 1.96. The interval MUST handle small N more
accurately than a normal approximation and MUST be finite for the edge cases
where observed rate is 0 or 1.

#### Scenario: Edge rates produce finite intervals

- **WHEN** a task's observed success rate is 0 or 1 for small N
- **THEN** the computed Wilson interval is a finite [low, high] pair within [0, 1]

#### Scenario: Symmetric interval for a known value

- **WHEN** the observed rate is 0.5 with a known N
- **THEN** the interval is symmetric about 0.5 and matches the reference Wilson
  computation to numerical tolerance

### Requirement: Baseline Comparison and Verdict

The system SHALL compare the current run to a stored baseline. For each task it
SHALL flag the task as regressed when the current success-rate interval does not
overlap the baseline's lower bound in a way that indicates a significant drop,
and flag it as improved symmetrically. The overall gate verdict SHALL be FAIL
if any task is regressed, and PASS otherwise. A run with no baseline SHALL
establish the baseline rather than produce a verdict.

#### Scenario: Baseline established on first run

- **WHEN** no baseline report is provided (or the provided path does not exist)
- **THEN** the run stores the observed results as the baseline and reports
  "baseline established" rather than a pass/fail verdict
- **AND** the run exits with code 0

#### Scenario: Significant regression is gated

- **WHEN** a task's current interval indicates a significant drop below the
  baseline interval
- **THEN** the task is flagged regressed and the overall verdict is FAIL

#### Scenario: Within-noise change is not gated

- **WHEN** a task's current interval overlaps the baseline interval
- **THEN** the task is flagged unchanged and does not contribute to a FAIL
  verdict (single-run noise must not block the gate)

### Requirement: Baseline Persistence

The system SHALL load a baseline from a prior `gate_report.json` path and SHALL
be able to save the current run as a new baseline. The baseline SHALL persist
per-task success rates, intervals, and cost metrics so a later run can compare
against them.

#### Scenario: Baseline round-trip

- **WHEN** a gate report is saved as a baseline and later loaded
- **THEN** the per-task success rates, intervals, and cost metrics are
  preserved
- **AND** a corrupt or schema-mismatched baseline file is treated as an
  infrastructure error (exit 2), not silently ignored

## Constraints

- The gate SHALL block on significant regression only; it MUST NOT block on a
  single-trial difference that lies within the confidence interval.
- This layer MUST NOT depend on LLM availability; it operates purely on the
  pass/fail results of already-graded trials.
