# task-suite Specification

Behavior contract for the curated, versioned task input format and the grader
abstraction that grades each trial.

## ADDED Requirements

### Requirement: Task File Format

The system SHALL load tasks from a suite directory as individual YAML files,
one per task. Each task SHALL declare a name, the target form (mapping to a
source-analyzer form name), fixed input data (curated, not generated), an
optional grader list, and optional cost limits. Task files SHALL be treated as
data, not code: a task MUST NOT generate its own inputs.

#### Scenario: Suite loaded from directory

- **WHEN** the suite directory contains three well-formed task files
- **THEN** all three tasks are loaded and available to the gate run

#### Scenario: Task declares graders and cost limits

- **WHEN** a task file declares a grader list and cost limits
- **THEN** the gate run uses that grader list for that task and enforces those
  cost limits when the cost gate is active

### Requirement: Grader Abstraction

The system SHALL provide a grader abstraction where each grader grades a single
trial result and returns a pass/fail, an optional 0–1 score, and a detail
string. It SHALL include a deterministic scripted grader that requires no LLM
calls, and an optional LLM-judge grader that uses a separate judge LLM
configuration so it is independent of the model under test.

#### Scenario: Default grader is scripted

- **WHEN** a task declares no graders
- **THEN** the scripted grader is used, which passes the trial when all runner
  steps passed and no error-indicator assertion fired, without any LLM call

#### Scenario: LLM-judge grader uses an independent judge

- **WHEN** a task enables the LLM-judge grader
- **THEN** the judge request is sent to the separately configured judge LLM,
  not to the model under test, to reduce self-preference bias
- **AND** the LLM-judge grader is off by default in gate runs

### Requirement: Malformed Task Handling

The system SHALL treat a malformed task file (missing required fields, invalid
form reference, unparseable YAML) as an infrastructure error for the gate run.

#### Scenario: Malformed task aborts the run

- **WHEN** a task file is missing its required `form` or `data` field
- **THEN** the gate run aborts with an infrastructure error (exit 2) and a
  diagnostic identifying the offending task

## Constraints

- The initial suite SHALL contain a small set of tasks (happy path, boundary,
  and special-character cases) mirroring the existing data-generation variation
  scheme, but with fixed inputs.
