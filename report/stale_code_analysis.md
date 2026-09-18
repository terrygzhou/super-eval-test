# SuperApp Test — Stale Code Analysis Report

**Date:** 2026-08-10 (original); **Re-verified:** 2026-09-18
**Analyzer:** codegraph static analysis + import cross-reference
**Project:** `/home/terry/projects/super-eval-test` (repo dir `superweb-testing`)
**Python files scanned:** 10 in `src/` (`cli.py`, `pipeline.py`, `source_analyzer.py`, `data_generator.py`, `test_runner.py`, `log_monitor.py`, `openhands_client.py`, `constants.py`, `__init__.py`, `__main__.py`)
**Total source lines:** ~3,300 (original scan); current tree is smaller

> **Re-verification note (2026-09-18):** This report was re-checked against the
> current codebase. Nearly every "stale code" item it flagged has since been
> **resolved** — the `tests/` tree, the orphaned `crm_test_runner.py`, the
> root-level `test_openhands_connection.py`, the unused constants, and the
> unused module-level regex patterns are all **gone from the current tree**.
> Sections below are kept for provenance but each is annotated with its
> current status. The "Summary of Actions Required" table is superseded by
> the re-verification status section at the bottom.

---

## Executive Summary

| Category | Files | Status |
|---|---|---|
| Confirmed stale (original scan) | 4 | Dead code / unreachable / broken |
| Orphaned modules | 1 | Not wired into any pipeline |
| Unused constants | 4 | Defined but never imported |
| Broken dependencies | 1 | Import error (missing package) |

> **Current status (2026-09-18):** All four "confirmed stale" items, the one
> orphaned module, and the unused constants have been **removed** from the
> tree. The only still-relevant observations are in §3.

---

## 1. Confirmed Stale Code

> **Status: RESOLVED** — none of the items in this section exist in the
> current codebase.

### 1.1 `tests/conftest.py` — Broken test configuration

**Severity:** High (original)
**Current status:** **RESOLVED** — the entire `tests/` directory no longer
exists in the repo (confirmed: `tests/` absent, no `conftest.py`, no
`test_*.py` anywhere). AGENTS.md confirms "No test suite is currently present."

**Original evidence (historical):**
- `tests/conftest.py:8` imported `pytest_playwright.PlaywrightBrowser`
- `pyproject.toml` dev deps: `pytest>=8.3`, `pytest-asyncio>=0.24` (no `pytest-playwright`)
- `tests/__init__.py` was an empty stub; no `test_*.py` files

**Recommendation (superseded):** `tests/` was removed. If a real test
infrastructure is later added, it should use `pytest-asyncio` and ship with
actual test files.

---

### 1.2 `src/constants.py` — Two unused constants

**Severity:** Medium (original)
**Current status:** **RESOLVED** — `constants.py` is now 8 lines defining
exactly 3 constants: `DEFAULT_LLM_BASE_URL` (line 6), `DEFAULT_LLM_MODEL`
(line 7), `DEFAULT_OPENHANDS_LLM_MODEL` (line 8). The unused
`DEFAULT_OPENHANDS_BASE_URL` and `DEFAULT_OPENHANDS_TIMEOUT` have been
removed.

**Original evidence (historical):**
- 5 constants were defined; 2 unused.
- The original claim that "pipeline.py L118-120 uses hardcoded `timeout=2400`"
  was **incorrect** — current `pipeline.py:118-120` passes
  `timeout=self.agent_timeout`, `model=DEFAULT_OPENHANDS_LLM_MODEL`,
  `base_llm_url=DEFAULT_LLM_BASE_URL` to `OpenHandsClient()`. No `2400`
  literal exists in the current source.

---

### 1.3 `src/source_analyzer.py` — Unused module-level regex patterns

**Severity:** Low (original)
**Current status:** **RESOLVED** — `_FORM_PATTERNS` and `_ROUTE_PATTERNS`
no longer exist. `source_analyzer.py` now defines `_TYPE_MAP` (lines 52-78)
at module level, and the class accepts `form_patterns` / `route_patterns`
instance parameters in `__init__` (lines 90-95) with defaults that are
actually used (`self.form_patterns` drives `_extract_forms` at line 134;
`self.route_patterns` drives `_extract_routes` at line 396).

**Original evidence (historical):** module-level compiled regexes for
Pydantic models and route decorators were defined but never referenced.

---

### 1.4 `test_openhands_connection.py` — Orphaned root-level script

**Severity:** Low (original)
**Current status:** **RESOLVED** — the file does not exist. There are zero
Python files at the repo root (the root now holds `run_test.sh` as the only
executable script plus the usual config/docs files).

---

## 2. Orphaned Modules

### 2.1 `src/crm_test_runner.py` — 505-line module not wired into pipeline

**Severity:** Medium (original)
**Current status:** **RESOLVED** — `crm_test_runner.py` does not exist.
`src/` now contains exactly: `cli.py`, `pipeline.py`, `source_analyzer.py`,
`data_generator.py`, `test_runner.py`, `log_monitor.py`,
`openhands_client.py`, `constants.py`, `__init__.py`, `__main__.py`.
Grep for `crm_test_runner` across the repo returns zero references.

**Original evidence (historical):** `CRMTestRunner` duplicated the 4-phase
pipeline orchestration; `pipeline.py` and `cli.py` never imported it.

---

## 3. Additional Observations

### 3.1 CLI `extract_forms` command duplicates pipeline logic
**Current status:** **RESOLVED** — `cli.py` has no `extract_forms` command.
The registered commands are: `run` (line 37), `analyze` (line 134),
`generate` (line 175), `openhands-start` (line 237), `openhands-stop`
(line 247), `openhands-status` (line 257), plus `main()` (line 270). The
L179-211 region of `cli.py` is part of the `generate` command, which writes
`data/test_data.json` — not `forms_data.json`.

### 3.2 config.yaml generated at runtime
**Current status:** **PARTIALLY ACCURATE** — `run_test.sh` still generates
`config.yaml` at runtime (heredoc at lines 80-133). However the original
claim that `pipeline.py` has a `from_config()` classmethod is **incorrect**
against the current code: `Pipeline` is constructed via `__init__` only,
which calls `_load_config` internally (lines 47, 73-80). There is no
`from_config` method.

### 3.3 No async in test infrastructure
**Current status:** **STILL RELEVANT** — `pyproject.toml` still lists
`pytest-asyncio>=0.24` as a dev dependency (line 17) but there is no test
suite anywhere in the repo to exercise it (confirmed: no `tests/`, no
`test_*.py`). This is a declared-but-unused dev dependency.

---

## 4. New Issues Found During Re-Verification (2026-09-18)

These were **not** in the original report but are present in the current
codebase:

### 4.1 `.gitignore` references the old `suet_output/` name
`.gitignore` line 15 contains `suet_output/` (a leftover from the original
project name). The current default output directory is `./superApp_output`
(`cli.py:48`), so the gitignore pattern no longer matches the real output
dir, and the real output dir is **not** gitignored.

**Recommendation:** Replace `suet_output/` with `superApp_output/` in
`.gitignore`.

### 4.2 Stale `superApp_output` directory is untracked
The default output dir `./superApp_output` is not in `.gitignore`, so any
run will leave untracked files in the working tree.

**Recommendation:** Add `superApp_output/` to `.gitignore`.

### 4.3 `config.yaml` checked into the working tree
A real `config.yaml` (839 bytes) sits in the repo root. AGENTS.md states
"config.yaml is gitignored; never commit real config, use
`config.example.yaml` as the template." The current `.gitignore` does
`config.yaml` (line 21) with `!.config.example.yaml` / `!config.example.yaml`
exclusions, so `config.yaml` is ignored by git but the local file still
holds real endpoint config that should not be exposed.

**Recommendation:** Confirm `config.yaml` is untracked in git status; keep
the real file local and use `config.example.yaml` as the template.

### 4.4 `pipeline.py` hardcodes an LEF-specific default source root
`pipeline.py` defaults `source.root` to `~/workspace/projects/loop_factory`
when none is configured (lines 425-427 in `run()` and lines 477-479 in
`phase1_analyze`). This is an implicit coupling to the external Loop
Engineering Factory workspace that the original report never mentions.

**Recommendation:** Document this default in README, or make it a required
CLI/config value to avoid silent coupling.

---

## Summary of Actions Required (Updated 2026-09-18)

| Priority | Action | File(s) | Status |
|---|---|---|---|
| P1 | ~~Fix test infrastructure or remove tests/~~ | `tests/`, `pyproject.toml` | **RESOLVED** — `tests/` removed; no test suite present |
| P2 | ~~Wire or remove crm_test_runner~~ | `src/crm_test_runner.py` | **RESOLVED** — file removed |
| P3 | ~~Remove unused constants~~ | `src/constants.py` | **RESOLVED** — now 3 constants |
| P4 | ~~Remove unused regex patterns~~ | `src/source_analyzer.py` | **RESOLVED** — replaced with instance-level globs |
| P5 | ~~Relocate or remove root script~~ | `test_openhands_connection.py` | **RESOLVED** — file removed |
| P6 (new) | Replace stale `suet_output/` with `superApp_output/` in `.gitignore` | `.gitignore` | Open |
| P7 (new) | Add `superApp_output/` to `.gitignore` | `.gitignore` | Open |
| P8 (new) | Document LEF-specific default `source.root` in README or make it required | `pipeline.py`, `README.md` | Open |
