"""Prompt templates for agent-mode OpenHands conversations.

Keeping these in their own module makes the agent-mode prompt content
diff-able, testable, and readable without scrolling through the whole
pipeline.
"""

from __future__ import annotations


def analyze_goal(container_source: str, artifacts_dir: str) -> str:
    """Goal for conversation 1: scan source, write analysis.json + test_data.json."""
    return (
        f"You are a QA automation engineer. Your working directory is "
        f"{container_source}. Your output directory is {artifacts_dir}.\n\n"
        "CRITICAL: Only scan the `src/` subdirectory for frontend components. "
        "Ignore node_modules, dist, .venv, and any non-source directories.\n\n"
        "Use your tools (bash, write_file) to complete these steps:\n"
        "1. List ONLY frontend files: `find src/ -name '*.tsx' -o -name '*.ts' | sort`\n"
        "   If no src/ exists, try: `ls -la` then `find . -maxdepth 3 -name '*.tsx' -o -name '*.ts' | head -50`\n"
        "2. Read 5-10 key component files that contain forms, inputs, or API calls.\n"
        "   Focus on files matching: *Form*, *Dialog*, *Input*, *Chat*, *Settings*, *Search*, *Create*, *Upload*\n"
        f"3. Write a JSON file at {artifacts_dir}/analysis.json containing:\n"
        "   - forms: list of {{'name': ..., 'fields': [{{'field_name': ..., 'type': ..., 'required': ...}}], 'endpoint': ..., 'source_file': ...}}\n"
        "   - endpoints: list of API routes and expected methods\n"
        f"4. Generate 3 realistic test data variations per form, save to {artifacts_dir}/test_data.json\n\n"
        "TIME LIMIT: Complete within 8 minutes. If stuck on large repos, focus on 5-8 form components max.\n"
        "Use write_file or bash (echo/cat heredoc) to create the JSON files. "
        "Make sure each file is valid JSON before finishing."
    )


def test_goal(container_source: str, artifacts_dir: str, target_url: str) -> str:
    """Goal for conversation 2: run tests, write test_results.json."""
    return (
        f"You are a QA automation engineer. Your working directory is "
        f"{container_source}. Your output directory is {artifacts_dir}.\n\n"
        f"Run tests against {target_url}. Generate comprehensive, traceable test results.\n\n"
        "## Steps\n"
        "1. Read analysis from " + artifacts_dir + "/analysis.json to identify forms, endpoints, and source file mappings.\n"
        "2. Read test data from " + artifacts_dir + "/test_data.json.\n"
        "3. For each test case, perform the following:\n"
        "   a. Navigate to the target page URL.\n"
        "   b. Generate a unique session_id (UUIDv4) for this test run.\n"
        "   c. Fill form fields or make API requests with the test data.\n"
        "   d. Capture the HTTP response (status code, headers, body).\n"
        "   e. Capture frontend console logs (via Playwright page.on('console') or curl --verbose).\n"
        "   f. If the target app exposes a logs endpoint (e.g. /api/logs, /logs), fetch and capture server-side log output for this request.\n"
        "   g. Identify the source code file that implements the tested form/endpoint (from analysis.json).\n"
        "4. Save results to " + artifacts_dir + "/test_results.json\n\n"
        "## Output Schema — test_results.json\n"
        "Each test entry must contain ALL of these fields:\n"
        '{\n'
        "  \"tests\": [\n"
        "    {\n"
        "      \"test_name\": \"string (e.g. CreateProjectForm/Standard English Project)\",\n"
        '      "status": "passed" | "failed" | "error" | "skipped",\n'
        "      \"duration_ms\": number,\n"
        "      \"session_id\": \"UUIDv4 string\",\n"
        "      \"page_url\": \"full URL navigated to (e.g. http://host.docker.internal:19829/project/create)\",\n"
        '      \"test_data\": { field_name: value, ... },\n'
        '      \"action_performed\": "HTTP method + path or browser action description (e.g. POST /api/projects, filled and submitted CreateProjectForm)",\n'
        '      \"source_file\": "relative path to source file that implements this form/endpoint (e.g. src/forms/create_project.tsx or backend/api/projects.py)",\n'
        '      "http_response": {\n'
        '        "status_code": number | null,\n'
        '        "headers": { key: value, ... } | null,\n'
        '        "body_preview": "first 500 chars of response body or null"\n'
        "      },\n"
        '      "frontend_logs": [\n'
        '        { "level": "log|warn|error", "message": "string" }\n'
        "      ],\n"
        '      "server_logs": [\n'
        '        { "timestamp": "ISO string", "level": "INFO|WARN|ERROR", "message": "string" }\n'
        "      ],\n"
        '      "error": {\n'
        '        "error_code": "string (HTTP status, exception type, or null if passed)",\n'
        '        "exception_description": "stack trace or error message, or null",\n'
        '        "frontend_error": "console.error output or UI error text, or null",\n'
        '        "server_error": "server-side error from logs or response, or null"\n'
        "      },\n"
        '      "screenshot": "relative path to screenshot on failure, or null"\n'
        "    }\n"
        "  ],\n"
        "  \"summary\": { \"total\": number, \"passed\": number, \"failed\": number, \"skipped\": number }\n"
        "}\n\n"
        "IMPORTANT:\n"
        "- Every test entry MUST include session_id, page_url, test_data, action_performed, source_file, http_response, frontend_logs, server_logs, and error fields.\n"
        "- For passed tests, set error fields to null.\n"
        "- For failed tests, populate ALL error sub-fields with actual captured data.\n"
        "- Make the test_data object contain the exact values submitted (redact secrets if any).\n"
        "- Use bash/curl or write a Python test script to execute tests. Do NOT use Playwright if unavailable — curl/fetch is acceptable.\n"
        "- Verify the JSON is valid before saving."
    )


def report_goal(container_source: str, artifacts_dir: str) -> str:
    """Goal for conversation 3: generate report.json + report.md."""
    return (
        f"You are a QA automation engineer. Your working directory is "
        f"{container_source}. Your output directory is {artifacts_dir}.\n\n"
        "Generate a comprehensive, traceable test report.\n\n"
        "## Steps\n"
        "1. Read " + artifacts_dir + "/analysis.json for form/endpoint/source mapping.\n"
        "2. Read " + artifacts_dir + "/test_results.json for per-test results.\n"
        "3. Read " + artifacts_dir + "/test_data.json for test input data.\n"
        "4. Cross-reference all data sources and compile a full report.\n"
        "5. Save to " + artifacts_dir + "/report.json.\n\n"
        "## Output Schema — report.json\n"
        '{\n'
        '  "report_metadata": {\n'
        '    "generated_at": "ISO 8601 timestamp",\n'
        '    "target_url": "string",\n'
        '    "source_root": "path to analyzed source",\n'
        '    "pipeline_mode": "agent"\n'
        "  },\n"
        '  "summary": {\n'
        '    "forms_analyzed": number,\n'
        '    "test_records": number,\n'
        '    "tests_passed": number,\n'
        '    "tests_failed": number,\n'
        '    "tests_skipped": number,\n'
        '    "pass_rate": percentage (0-100),\n'
        '    "total_duration_ms": number,\n'
        '    "avg_duration_ms": number\n'
        "  },\n"
        '  "test_details": [\n'
        "    {\n"
        '      "test_name": "string",\n'
        '      "status": "passed" | "failed" | "error" | "skipped",\n'
        '      "duration_ms": number,\n'
        '      "session_id": "UUIDv4",\n'
        '      "page_url": "full URL",\n'
        '      "test_data": { field: value, ... },\n'
        '      "action_performed": "string",\n'
        '      "source_file": "relative path",\n'
        '      "http_response": {\n'
        '        "status_code": number | null,\n'
        '        "headers": { ... } | null,\n'
        '        "body_preview": "string | null"\n'
        "      },\n"
        '      "frontend_logs": [{ "level": "string", "message": "string" }],\n'
        '      "server_logs": [{ "timestamp": "string", "level": "string", "message": "string" }],\n'
        '      "error": {\n'
        '        "error_code": "string | null",\n'
        '        "exception_description": "string | null",\n'
        '        "frontend_error": "string | null",\n'
        '        "server_error": "string | null"\n'
        "      },\n"
        '      "screenshot": "path | null"\n'
        "    }\n"
        "  ],\n"
        '  "failures": [\n'
        "    {\n"
        '      "test_name": "string",\n'
        '      "error_code": "string",\n'
        '      "exception_description": "string",\n'
        '      "frontend_error": "string | null",\n'
        '      "server_error": "string | null",\n'
        '      "session_id": "UUIDv4",\n'
        '      "source_file": "string"\n'
        "    }\n"
        "  ],\n"
        '  "source_coverage": {\n'
        '    "files_tested": ["list of unique source files tested"],\n'
        '    "endpoints_tested": ["list of unique API endpoints tested"],\n'
        '    "forms_tested": ["list of unique form names tested"]\n'
        "  },\n"
        '  "narrative_summary": "string — concise summary of findings, key regressions, and recommendations"\n'
        "}\n\n"
        "## Requirements\n"
        "- ALL test entries from test_results.json must appear in test_details.\n"
        "- Cross-reference analysis.json to fill in source_file mappings where test_results.json is incomplete.\n"
        "- failures array lists only tests with status 'failed' or 'error'.\n"
        "- source_coverage aggregates unique values from all test entries.\n"
        "- narrative_summary must be 150-500 words, focusing on pass rate, failure patterns, and actionable recommendations.\n"
        "- Verify the JSON is valid before saving.\n\n"
        "## Generate Markdown Report\n"
        f"Then write a human-readable Markdown report to {artifacts_dir}/report.md.\n\n"
        "The Markdown must be easily parsable by coding agents for backlog generation AND readable by humans for action prioritization.\n\n"
        "## Markdown Structure\n\n"
        "```markdown\n"
        "# Test Report — <target_url>\n\n"
        "## Executive Summary\n\n"
        "| Metric | Value |\n"
        "| --- | --- |\n"
        "| Tests | <total> |\n"
        "| Passed | <passed> |\n"
        "| Failed | <failed> |\n"
        "| Pass Rate | <rate>% |\n"
        "| Duration | <duration_ms>ms |\n\n"
        "## Failure Triage (by root cause)\n\n"
        "Group all failures by error_code or root cause. For each group:\n\n"
        "### <Error Code> — <Exception Summary> (<count> failures)\n\n"
        "- **Severity:** CRITICAL | HIGH | MEDIUM | LOW\n"
        "- **Root Cause:** <one-sentence diagnosis>\n"
        "- **Affected Forms:** <list of test names>\n"
        "- **Source Files:** <list of source files>\n"
        "- **Action Required:** <specific remediation step>\n\n"
        "### <next group> ... (repeat for each error group)\n\n"
        "## Blocking Issues\n\n"
        "List issues that prevent other tests from passing:\n\n"
        "- **<Issue>** — <Why it blocks other tests, what must be fixed first>\n\n"
        "## Detailed Failures\n\n"
        "Each failure is a standalone task for agent-driven remediation.\n\n"
        "### <test_name>\n\n"
        "- **Session:** <session_id>\n"
        "- **Source:** <source_file>\n"
        "- **Error Code:** <error_code>\n"
        "- **Exception:** <exception_description>\n"
        "- **Frontend Error:** <frontend_error>\n"
        "- **Server Error:** <server_error>\n"
        "- **Action Performed:** <action_performed>\n\n"
        "### <next_failure> ... (repeat for each failure)\n\n"
        "## Test Details\n\n"
        "| Test | Status | Duration | Source File | Error Code |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| <test_name> | <status> | <duration_ms>ms | <source_file> | <error_code or - > |\n\n"
        "## Source Coverage\n\n"
        "| Category | Count | Details |\n"
        "| --- | --- | --- |\n"
        "| Files Tested | <count> | <comma-separated list> |\n"
        "| Endpoints Tested | <count> | <comma-separated list> |\n"
        "| Forms Tested | <count> | <comma-separated list> |\n\n"
        "## Coverage Gaps\n\n"
        "- **Untested Forms:** <list of forms from analysis.json that had no tests>\n"
        "- **Untested Endpoints:** <list of endpoints from analysis.json that had no tests>\n"
        "- **Risk Assessment:** <what's the risk of not testing these>\n\n"
        "## Recommendations\n\n"
        "1. <Highest priority action — usually the blocking issue or most impactful fix>\n"
        "2. <Second priority>\n"
        "3. <Third priority>\n\n"
        "## Narrative Summary\n\n"
        "<narrative_summary from report.json — 150-500 words>\n"
        "```"
    )
