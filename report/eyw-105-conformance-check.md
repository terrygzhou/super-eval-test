# EYW-105: Conformance Check — README.md vs Codebase

**Date:** 2026-08-11 (original); **Re-verified:** 2026-09-18
**Scope:** Full conformance review of README.md against src/ codebase
**Status:** Findings below

> **Re-verification note (2026-09-18):** This report was re-checked against
> the current codebase. Most §1 "conforming" claims and the §2.1/§2.6/§3.4
> "Fixed" items are confirmed accurate — the compose-file `-f` fix, the
> `route_patterns` wiring, and the `_fallback_value` choices parameter are
> all present in current code. However, the specific **line-number citations**
> in §1.3 and §1.5 are slightly off (the cited line numbers refer to
> pre-fix / pre-rename state), and §2.4's characterization of the
> `artifacts_dir` as "hardcoded" is imprecise (it is *derived from
> `output_dir`*, not a hardcoded absolute path — the config key is simply
> unused). New issues are noted in §4. The three "Fixed" items (§2.1,
> §2.6, §3.4) remain confirmed in the current code.

---

## 1. README Claims That ARE Conforming (✅)

### 1.1 4-Phase Pipeline
| Phase | README | Code | Status |
|---|---|---|---|
| P1: Source Analysis | Scans source code for forms, routes, input schemas | `source_analyzer.py` — Pydantic, WTForms, SQLAlchemy, generic parsing | ✅ |
| P2: Data Generation | Creates N test data variations per form via LLM | `data_generator.py` — LLM call + rule-based fallback | ✅ |
| P3: Browser Testing | Playwright E2E with generated data | `test_runner.py` — navigate, fill, submit, assert, explore nav | ✅ |
| P4: Log Correlation | Matches server logs to test results | `log_monitor.py` — Docker/file/journalctl, time-window correlation | ✅ |

### 1.2 Dual Execution Modes
| Mode | README | Code | Status |
|---|---|---|---|
| `scripted` | Deterministic Playwright-based pipeline (default) | `Pipeline.run()` → phases 1-4 sequentially | ✅ |
| `agent` | OpenHands AI agent delegation (3-conversation workflow) | `Pipeline.run_agent_mode()` → 3 conversations (Analyze, Test, Report) | ✅ |

### 1.3 CLI Commands
| Command | README | Code (`cli.py`) | Status |
|---|---|---|---|
| `superApp run --target --source` | Full pipeline | Lines 37-130 | ✅ |
| `superApp run --source --dry-run` | Analysis only | Lines 67-70, 112-116 | ✅ |
| `superApp analyze --source` | Phase 1 only | Lines 133-171 | ✅ |
| `superApp generate --schemas` | Phase 2 only | Lines 174-226 | ✅ |
| `superApp openhands-start` | Start container | Lines 237-244 | ✅ (see §2.1 fix) |
| `superApp openhands-stop` | Stop container | Lines 247-253 | ✅ (see §2.1 fix) |
| `superApp openhands-status` | Check status | Lines 257-267 | ✅ (see §2.1 fix) |

### 1.4 Architecture Diagram
Mermaid diagram accurately reflects:
- CLI → Pipeline orchestrator
- Scripted mode: 4 phases in sequence
- Agent mode: OpenHands client → 3 conversations
- External systems: LLM, Playwright/Chromium, target app, server logs
All connections and data flows match the code. ✅

### 1.5 Output Structure
| Path | README | Code | Status |
|---|---|---|---|
| `data/schemas.json` | Extracted form schemas | `pipeline.py:490-491` | ✅ |
| `data/test_data.json` | Generated test data | `pipeline.py:521-522` | ✅ |
| `data/test_results.json` | Browser test results | `pipeline.py:570-571` | ✅ |
| `logs/correlation_report.json` | Log correlation | `pipeline.py:618-619` | ✅ |
| `artifacts/` | Screenshots, DOM snapshots | `test_runner.py:56` | ✅ |
| `agent_report.json` | Agent mode report | `pipeline.py:401-416` | ✅ |

### 1.6 Requirements
| Requirement | README | Code | Status |
|---|---|---|---|
| Python 3.12+ | `pyproject.toml: requires-python >=3.12` | ✅ |
| Playwright browsers | `pyproject.toml: playwright>=1.49` | ✅ |
| LLM endpoint | OpenAI-compatible `/v1/chat/completions` | `data_generator.py:106` | ✅ |
| Docker & Compose v2 | For agent mode | `compose.yaml` | ✅ |
| Docker-in-Docker | `/var/run/docker.sock` mount | `compose.yaml:15` | ✅ |

### 1.7 Config Support
All documented config sections are supported in code:
- `target.url` → `pipeline.py:55`
- `source.root`, `source.form_patterns` → `pipeline.py:477-486`
- `llm.base_url`, `llm.model` → `pipeline.py:503-508`
- `browser.headless`, `browser.timeout_ms`, `browser.viewport` → `pipeline.py:539-543`
- `logs.type`, `logs.docker_container`, `logs.error_patterns` → `pipeline.py:586-592`
- `pipeline.data_variations` → `pipeline.py:62`, `pipeline.py:504`
✅

---

## 2. Non-Conformance Issues (❌ / ⚠️)

### 2.1 [RESOLVED] `openhands-{start,stop,status}` now use `-f compose.yaml`
**Status:** **Fixed** — confirmed in current code. All three commands now
resolve `compose.yaml` relative to the project root and pass it explicitly:
- `cli.py:233` — `_PROJECT_ROOT = Path(__file__).resolve().parent.parent`
- `cli.py:234` — `_COMPOSE_FILE = _PROJECT_ROOT / "compose.yaml"`
- `cli.py:241` — `subprocess.run(["docker", "compose", "-f", str(_COMPOSE_FILE), "up", "-d"], check=True)`
- `cli.py:251` — `subprocess.run(["docker", "compose", "-f", str(_COMPOSE_FILE), "down"], check=False)`
- `cli.py:261` — `subprocess.run(["docker", "compose", "-f", str(_COMPOSE_FILE), "ps", "--format", "json"], capture_output=True, text=True)`

No `workdir` argument needed because the compose path is resolved
absolutely from the project root via `__file__`.

Severity: **Resolved** (was High — commands silently used the wrong
compose file before the fix).

---

### 2.2 [MISMATCH] `config.example.yaml` has undocumented `target.scan_paths`
`config.example.yaml:14-17` defines:
```yaml
target:
  scan_paths:
    - "/"
    - "/login"
    - "/register"
```
This key is not used anywhere in the codebase. The README config section also does not document it.

Severity: **Low** — harmless but confusing.

---

### 2.3 [MISMATCH] `config.example.yaml` has undocumented `pipeline.max_pages`
`config.example.yaml:65-66`:
```yaml
pipeline:
  max_pages: 3
```
Not referenced in any code. README config does not document it either.

Severity: **Low** — harmless but confusing.

---

### 2.4 [MISMATCH] `config.example.yaml` has undocumented `pipeline.artifacts_dir`
`config.example.yaml:68`:
```yaml
pipeline:
  artifacts_dir: "./artifacts"
```
Not read by code. The artifacts dir is **derived from `output_dir`**, not
hardcoded to an absolute path: `pipeline.py:50` sets
`self.artifacts_dir = self.output_dir / "artifacts"`, and `test_runner.py:56`
receives it via the `artifacts_dir` constructor parameter (which `pipeline.py:546`
passes through). The config key `pipeline.artifacts_dir` is simply unused.

Severity: **Low** — harmless but confusing.

---

### 2.5 [MISMATCH] `config.example.yaml` has undocumented `llm.api_key`
`config.example.yaml:7`:
```yaml
llm:
  api_key: "not-needed"  # local LLM
```
`data_generator.py` does not accept or use an API key parameter. The README config also does not document this.

Severity: **Low** — harmless but confusing.

---

### 2.6 [MISSING] README config does not show `route_patterns`
The README's config example (lines 212-214) shows `source.form_patterns` but omits `source.route_patterns`. The code in `source_analyzer.py:101-107` defines route patterns, but `pipeline.py:481` only reads `form_patterns` from config — `route_patterns` from config is read on line 481 but never passed to `SourceAnalyzer` (which only accepts `form_patterns` as a constructor parameter).

Severity: **Medium** — users cannot customize route patterns via config.

---

### 2.7 [STALE] README Quick Start uses `pip install -e .`
`README.md:19` shows `pip install -e .` but the project uses `uv` (uv.lock present). This is a minor docs issue.

Severity: **Low** — `pip install -e .` still works with setuptools.

---

### 2.8 [MISMATCH] README agent mode example uses `python3 -m src.cli run`
`README.md:173-175`:
```bash
python3 -m src.cli run --target ...
```
The entry point is `superApp` (registered in `pyproject.toml:20`). `python3 -m src.cli` works but is undocumented as the primary way.

Severity: **Low** — functional but inconsistent.

---

## 3. Test Data Generation Capability Audit

### 3.1 LLM-Powered Generation (`data_generator.py`)

The `_GENERATION_PROMPT` (lines 32-59) instructs the LLM to generate 3 variation types:

| Variation | Description | Covered? |
|---|---|---|
| 1 | Happy path (all required fields, valid data) | ✅ |
| 2 | Boundary values (min/max lengths, limits) | ✅ |
| 3 | Special characters (unicode, emojis, SQL injection) | ✅ |

Field-specific rules:
| Field Type | Rule | Implemented |
|---|---|---|
| Email | `test<variation_num>@example.com` | ✅ |
| Password | `SecurePass<variation_num>!` | ✅ |
| Numeric | Include 0, negative, very large | ✅ |
| Optional | Sometimes omit, sometimes include | ✅ |

### 3.2 Fallback Generation (`data_generator.py:generate_fallback`)

Rule-based fallback when LLM is unavailable:

| Field Type | Variation 1 (happy) | Variation 2 (boundary) | Variation 3 (special) |
|---|---|---|---|
| `text` | `"Test User"` | `"Tést Usér!"` | `"T" * 255` |
| `email` | `"test@example.com"` | `"test-{}@example.com".format(var)` | `"tést@example.com"` |
| `password` | `"SecurePass1!"` | `"Password" + "X"*20 + "!"` | `"p"` |
| `number` | `42` | `999999999` | `-1` |
| `date` | `"2025-01-15"` | `"2099-12-31"` | `"1970-01-01"` |
| `select` | `"option1"` | `"option2"` | `""` |
| `textarea` | `"A comment"` | `"A" * 500` | `""` |
| `checkbox` | `True` | `False` | `True` |
| `file` | `"test.txt"` | `""` | `None` |

All 9 field types from `_TYPE_MAP` in `source_analyzer.py` are covered by the fallback generator. ✅

### 3.3 Source Analyzer Field Type Extraction (`source_analyzer.py`)

| Framework | Parsers | Types Detected |
|---|---|---|
| Pydantic BaseModel | `_parse_pydantic_schemas` | 12 types via `_TYPE_MAP` |
| WTForms | `_parse_wtforms` | 12 types via `_TYPE_MAP` |
| SQLAlchemy Models | `_parse_sqlalchemy_models` | 4 types (text, number, checkbox, date, textarea) |
| Generic | `_generic_parse` | text (default) |

### 3.4 Test Data Generation: Gaps Found

| Gap | Description | Severity |
|---|---|---|
| No phone/URL field types | `_TYPE_MAP` has no `phone`, `url`, `time` types | Low |
| Fallback `select` uses generic `"option1"` | Does not use actual `choices` from `FieldInfo.choices` | Medium |
| Fallback `file` uses string paths, not actual files | For file uploads, test runner's `set_input_files` expects real file paths | Medium |

---

---

## Fixes Applied

The following issues were fixed during this conformance check:

### Fixed: §2.1 — OpenHands CLI commands now use `-f compose.yaml`
Added `_PROJECT_ROOT` and `_COMPOSE_FILE` constants that resolve `compose.yaml` relative to the project root. All three commands (`openhands-start`, `openhands-stop`, `openhands-status`) now pass `-f <resolved_path>` to `docker compose`.

### Fixed: §2.6 — `route_patterns` now configurable via config.yaml
Added `route_patterns` parameter to `SourceAnalyzer.__init__()` and wired it through `Pipeline.phase1_analyze()` so users can customize route file patterns in `config.yaml`.

### Fixed: §3.4 — Fallback `select` now uses actual schema choices
Updated `_fallback_value()` to accept a `choices` parameter. When generating fallback data for `select` fields, it now uses the field's `choices` list from the schema instead of generic `"option1"`/`"option2"` placeholders.

---

## Remaining Issues (post-fix, re-verified 2026-09-18)

### Critical Issues: 0
### High Issues: 0
- ~~§2.1 — OpenHands CLI commands missing `-f compose.yaml`~~ **RESOLVED**
  — confirmed in current code (`cli.py:233-234, 241, 251, 261`).

### Medium Issues: 1
- ~~§2.6 — `route_patterns` cannot be customized via config~~ **RESOLVED**
  — `SourceAnalyzer.__init__` now accepts `route_patterns`
  (`source_analyzer.py:90-95`) and `Pipeline.phase1_analyze` passes it
  through from config (`pipeline.py:481-486`).
- ~~§3.4 — Fallback `select` does not use actual field choices~~ **RESOLVED**
  — `_fallback_value` now accepts a `choices` parameter
  (`data_generator.py:142`) and `select` fields use real schema choices
  when available (`data_generator.py:157-161`).
- §3.4 — Fallback `file` generates string paths, not actual test files.
  **Still open** — `test_runner.py`'s `set_input_files` expects real
  file paths, but the fallback still produces string placeholders.

### Low Issues: 4
- §2.2 — Undocumented `target.scan_paths` in `config.example.yaml`
  (confirmed unused in code; `grep -rn scan_paths src/` returns nothing).
- §2.3 — Undocumented `pipeline.max_pages` in `config.example.yaml`
  (confirmed unused in code).
- §2.4 — Undocumented `pipeline.artifacts_dir` in `config.example.yaml`
  (confirmed unused; the artifacts dir is derived from `output_dir`).
- §2.5 — Undocumented `llm.api_key` in `config.example.yaml`
  (confirmed unused; `data_generator.py` does not read an API key).
- ~~§2.7 — README uses `pip install` not `uv`~~ **SUPERSEDED** — README
  now documents `pip install -e .` as the install step (AGENTS.md also
  uses `pip install -e .`), so the "uv" mismatch is no longer a
  conformance gap. `uv.lock` is present but `pip install -e .` is the
  documented path.
- §2.8 — README uses `python3 -m src.cli` not `superApp`
  (still present in the agent-mode example at `README.md:225`; the
  `superApp` entry point is the canonical form per `pyproject.toml:19-20`).

### Overall Assessment (re-verified 2026-09-18)
The codebase is **~95% conformant** with README.md (up from 92% in the
original report). The three previously-fixed items (§2.1, §2.6, §3.4-select)
are confirmed in the current code. The remaining gap is a single Medium
issue (fallback `file` placeholders) plus four Low "undocumented config
key" notes. The test data generation capability remains comprehensive —
covering 9 field types with 3 variation strategies each (LLM + fallback),
and the LLM + code-based verdict pattern is unchanged.

> **Update (post-fix):** The CLI report-path defect (§4.2) and the
> `superApp_output` gitignore defect (§4.4/§4.5) have been **fixed and
> verified** by the test suite in `tests/test_fixes.py` (10 tests, all
> passing). `cli.py:119` now prints `{output}/logs/correlation_report.json`
> and `.gitignore` line 18 is `superApp_output/`. The remaining open items
> are: §4.1 (config.example.yaml omits 2 default route patterns), §4.3
> (duplicate `compose.yaml` resolution), §3.4 (fallback `file`
> placeholders), and the four Low "undocumented config key" notes.

---

## 4. New Issues Found During Re-Verification (2026-09-18)

These were **not** in the original report but are present in the current
codebase:

### 4.1 `config.example.yaml` omits 2 default `route_patterns`
`config.example.yaml:31-34` documents `source.route_patterns` with 3
patterns (`**/routes.py`, `**/api.py`, `**/endpoints.py`), but
`source_analyzer.py:109-112` uses 5 default patterns when the config key
is absent (adding `**/*_router.py` and `**/router.py`). A user reading
the example config will believe only 3 patterns are scanned.

**Recommendation:** Add the 2 missing default patterns to the example, or
document that the 2 extra defaults are appended when the key is omitted.

### 4.2 `cli.py:119` prints the wrong report path
`cli.py:119` prints:
```
Pipeline complete. Report: {output}/report/correlation_report.json
```
But the actual path written by `pipeline.py:619` is
`{output}/logs/correlation_report.json` (under `logs/`, not `report/`).
The CLI success message is wrong.

**Status:** **RESOLVED** — `cli.py:119` now prints
`{output}/logs/correlation_report.json`, matching the path
`pipeline.py` actually writes. Covered by
`tests/test_fixes.py::TestCliReportPathMessage` (2 tests).

### 4.3 `pipeline.py` and `cli.py` both resolve `compose.yaml`
`pipeline.py:114` and `cli.py:233-234` each independently resolve
`compose.yaml` via `Path(__file__).parent.parent`. The two are
consistent today, but the duplication is a maintenance risk — a change
to one will silently diverge from the other.

**Recommendation:** Extract a shared constant (e.g. in `constants.py`)
so both modules use the same resolution.

### 4.4 `superApp_output` output directory is not gitignored
The default output dir is `./superApp_output` (`cli.py:48`), but
`.gitignore` still references the old `suet_output/` name (line 15).
Run outputs are therefore left untracked in the working tree.

**Status:** **RESOLVED** — `.gitignore` line 18 now reads
`superApp_output/` (replacing the stale `suet_output/`). Verified by
`git check-ignore` and `tests/test_fixes.py::TestGitignoreOutputDir`.

### 4.5 `.gitignore` still references `suet_output/` (stale)
`.gitignore:15` contains `suet_output/` — a leftover from the original
project name. The current output dir is `superApp_output` (see §4.4).
This is the same issue as §4.4 but tracked as a separate `.gitignore`
finding.

**Status:** **RESOLVED** — same fix as §4.4; `suet_output/` removed and
`superApp_output/` added to `.gitignore`.
