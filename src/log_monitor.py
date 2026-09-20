"""Phase 4: Server log monitor — tail server logs, correlate errors with test timeline."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from datetime import datetime, timezone


@dataclass
class LogEvent:
    """A single server log event."""

    timestamp: str
    level: str  # ERROR | WARN | INFO
    message: str
    source: str = ""  # docker container, file path, etc.
    matched_pattern: str = ""


@dataclass
class TestEvent:
    """A test execution event for correlation."""

    timestamp: float
    form_name: str
    variation: int
    step: str
    action: str
    status: str  # pending | passed | failed


@dataclass
class ErrorCorrelation:
    """Correlation between a test event and server log errors."""

    test_event: TestEvent
    related_logs: list[LogEvent] = field(default_factory=list)
    time_window_sec: float = 5.0


class LogMonitor:
    """Monitor server logs and correlate with test execution timeline."""

    def __init__(
        self,
        log_type: str = "docker",
        docker_container: str | None = None,
        log_file: str | None = None,
        journal_unit: str | None = None,
        error_patterns: list[str] | None = None,
        time_window_sec: float = 5.0,
    ):
        self.log_type = log_type
        self.docker_container = docker_container
        self.log_file = log_file
        self.journal_unit = journal_unit
        self.error_patterns = error_patterns or [
            "ERROR", "Exception", "Traceback", "500",
            "Connection refused", "Internal Server Error",
        ]
        self.compiled_patterns = [re.compile(p) for p in self.error_patterns]
        self.time_window_sec = time_window_sec

        # Collected data
        self.log_events: list[LogEvent] = []
        self.test_events: list[TestEvent] = []
        self.correlations: list[ErrorCorrelation] = []

    def record_test_event(self, event: TestEvent):
        """Record a test event for later correlation."""
        self.test_events.append(event)

    def collect_logs(self, start_time: float, end_time: float) -> list[LogEvent]:
        """Collect server logs for a time window."""
        if self.log_type == "docker":
            return self._collect_docker_logs(start_time, end_time)
        elif self.log_type == "file":
            return self._collect_file_logs(start_time, end_time)
        elif self.log_type == "journalctl":
            return self._collect_journal_logs(start_time, end_time)
        return []

    def _collect_docker_logs(
        self, start_time: float, end_time: float
    ) -> list[LogEvent]:
        """Collect logs from a Docker container."""
        if not self.docker_container:
            return []

        try:
            start_dt = datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat()
            end_dt = datetime.fromtimestamp(end_time, tz=timezone.utc).isoformat()

            result = subprocess.run(
                ["docker", "logs", "--since", start_dt, "--until", end_dt, self.docker_container],
                capture_output=True, text=True, timeout=30,
            )
            raw = result.stdout + result.stderr

            ts = datetime.fromtimestamp(end_time, tz=timezone.utc).isoformat()
            return self._match_patterns(raw.splitlines(), self.docker_container, ts)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    def _collect_file_logs(
        self, start_time: float, end_time: float
    ) -> list[LogEvent]:
        """Collect logs from a file."""
        if not self.log_file:
            return []

        try:
            path = Path(self.log_file).expanduser().resolve()
            if not path.exists():
                return []
            content = path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()[-500:]  # Last 500 lines
            ts = datetime.now(timezone.utc).isoformat()
            return self._match_patterns(lines, str(path), ts)
        except OSError:
            return []

    def _collect_journal_logs(
        self, start_time: float, end_time: float
    ) -> list[LogEvent]:
        """Collect logs from journalctl."""
        if not self.journal_unit:
            return []

        try:
            start_dt = datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat()

            result = subprocess.run(
                ["journalctl", "-u", self.journal_unit, "--since", start_dt, "--no-pager"],
                capture_output=True, text=True, timeout=30,
            )
            raw = result.stdout
            ts = datetime.now(timezone.utc).isoformat()
            return self._match_patterns(raw.splitlines(), self.journal_unit, ts)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    def correlate(self) -> list[ErrorCorrelation]:
        """Correlate test events with log errors within a time window.

        Each log event is attached to test events that fall within
        ``time_window_sec`` of its timestamp. Log events without a parseable
        timestamp (docker ``--since/--until`` batches, journal files without
        embedded times) are attached to ALL test events as before, which
        matches the original behaviour when no timestamp information is
        available.
        """
        self.correlations = []

        if not self.log_events:
            return self.correlations

        for event in self.test_events:
            correlation = ErrorCorrelation(
                test_event=event,
                time_window_sec=self.time_window_sec,
            )

            for log_event in self.log_events:
                # Compare timestamps. LogEvent.timestamp is an ISO string;
                # TestEvent.timestamp is a float epoch.
                try:
                    log_ts = datetime.fromisoformat(log_event.timestamp).timestamp()
                except ValueError:
                    correlation.related_logs.append(log_event)
                    continue
                if abs(log_ts - event.timestamp) <= self.time_window_sec:
                    correlation.related_logs.append(log_event)

            if correlation.related_logs:
                self.correlations.append(correlation)

        return self.correlations

    def _match_patterns(
        self,
        lines: list[str],
        source: str,
        timestamp: str,
    ) -> list[LogEvent]:
        """Match log lines against compiled patterns; return matched LogEvents."""
        events: list[LogEvent] = []
        for line in lines:
            for i, pattern in enumerate(self.compiled_patterns):
                if pattern.search(line):
                    events.append(
                        LogEvent(
                            timestamp=timestamp,
                            level="ERROR",
                            message=line.strip(),
                            source=source,
                            matched_pattern=self.error_patterns[i],
                        )
                    )
                    break
        return events

    def generate_report(self) -> dict[str, Any]:
        """Generate a human-readable error correlation report."""
        correlations = self.correlate()

        report: dict[str, Any] = {
            "summary": {
                "total_test_events": len(self.test_events),
                "total_log_errors": len(self.log_events),
                "correlated_errors": len(correlations),
            },
            "correlations": [
                {
                    "test": {
                        "form": c.test_event.form_name,
                        "variation": c.test_event.variation,
                        "step": c.test_event.step,
                        "action": c.test_event.action,
                        "status": c.test_event.status,
                    },
                    "log_errors": [
                        {"message": log.message, "pattern": log.matched_pattern}
                        for log in c.related_logs
                    ],
                }
                for c in correlations
            ],
            "unmatched_errors": [
                {"message": log.message}
                for log in self.log_events
                if not any(log in c.related_logs for c in correlations)
            ],
        }

        return report

    def save_report(self, report: dict, output_path: str) -> str:
        """Save correlation report to JSON."""
        import json

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )
        return str(out)