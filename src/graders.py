"""Graders — grade a single trial result into pass/fail + optional score.

Two implementations:
  - ScriptedGrader: deterministic, no LLM. A trial passes when all runner steps
    passed and no error-indicator assertion fired.
  - LlmJudgeGrader: optional, sends a compact rubric + trial transcript to a
    *separate* judge LLM endpoint (independent of the model under test, to
    reduce self-preference bias).

The judge transport is injectable for testing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class GradeResult:
    """The outcome of grading one trial."""

    passed: bool
    score: float | None = None
    detail: str = ""
    grader_type: str = "scripted"


@runtime_checkable
class Grader(Protocol):
    """Protocol: grade a single trial (a TestRunResult) into a GradeResult."""

    def grade(self, trial: Any) -> GradeResult: ...


class ScriptedGrader:
    """Deterministic grader built on the runner's step pass/fail. No LLM."""

    grader_type = "scripted"

    # Step actions that, when they carry an error indicator, mean the trial
    # is a failure even if the overall status string says otherwise.
    _ERROR_MARKERS = ("error", "exception", "assertion failed", "not found")

    def grade(self, trial: Any) -> GradeResult:
        steps = getattr(trial, "steps", []) or []
        statuses = [getattr(s, "status", "") for s in steps]
        any_failed = any(st in ("failed", "error") for st in statuses)
        # An error-indicator assertion firing also counts as a failure.
        error_indicator = any(
            getattr(s, "status", "") in ("failed", "error")
            and any(m in getattr(s, "details", "").lower() for m in self._ERROR_MARKERS)
            for s in steps
        )
        trial_status = getattr(trial, "status", "")
        all_passed = bool(statuses) and all(st == "passed" for st in statuses)
        passed = trial_status == "passed" and not any_failed and not error_indicator
        detail = "all steps passed" if passed else (
            "a step failed / error indicator fired" if any_failed else "no steps recorded"
        )
        return GradeResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            detail=detail,
            grader_type=self.grader_type,
        )


# ---------------------------------------------------------------------------
# LLM judge
# ---------------------------------------------------------------------------

_JUDGE_TRANSPORT_DEFAULT = "http"


def _build_judge_prompt(rubric: str, transcript: str) -> str:
    return (
        "You are an impartial judge. Using the rubric, evaluate the trial "
        "transcript and respond with a single JSON object: "
        '{"passed": <bool>, "score": <0-1>}\n\n'
        f"Rubric: {rubric}\n\nTranscript:\n{transcript}"
    )


def _parse_judge_response(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {"passed": False, "score": 0.0, "detail": "judge returned unparseable JSON"}
    return {
        "passed": bool(data.get("passed", False)),
        "score": float(data.get("score", 0.0)),
        "detail": str(data.get("detail", "")),
    }


class LlmJudgeGrader:
    """Optional LLM judge. Uses a *separate* judge LLM config.

    The ``transport`` is an injectable callable with the signature
    ``(url, model, prompt, api_key) -> str`` returning the raw judge response
    body; the default posts to an OpenAI-compatible ``/v1/chat/completions``
    endpoint via httpx (mirroring ``data_generator.py``). This makes the judge
    unit-testable without a real LLM.
    """

    grader_type = "llm-judge"

    def __init__(
        self,
        judge_config: dict[str, Any] | None = None,
        *,
        rubric: str = "",
        transport: Any | None = None,
    ):
        self.rubric = rubric
        self.judge_config = judge_config or {}
        self._transport = transport

    def grade(self, trial: Any) -> GradeResult:
        # Scripted result feeds the judge transcript.
        scripted = ScriptedGrader().grade(trial)
        transcript = self._transcript(trial, scripted)
        return self._judge(scripted.passed, transcript)

    def _transcript(self, trial: Any, scripted: GradeResult) -> str:
        steps = getattr(trial, "steps", []) or []
        lines = [f"form: {getattr(trial, 'form_name', '?')} (status={getattr(trial, 'status', '?')})"]
        for s in steps:
            lines.append(f"  step {getattr(s, 'step', '?')} {getattr(s, 'action', '')}: "
                         f"{getattr(s, 'status', '')} {getattr(s, 'details', '')}".rstrip())
        lines.append(f"scripted verdict: {scripted.passed} ({scripted.detail})")
        return "\n".join(lines)

    def _judge(self, scripted_passed: bool, transcript: str) -> GradeResult:
        if not self.judge_config.get("base_url"):
            # No judge configured → fall back to the scripted verdict (off by default).
            return GradeResult(
                passed=scripted_passed,
                score=None,
                detail="judge not configured; used scripted verdict",
                grader_type=self.grader_type,
            )
        prompt = _build_judge_prompt(self.rubric, transcript)
        try:
            content = self._call_judge(prompt)
        except Exception as exc:  # judge unavailable → fall back, don't fail the trial
            return GradeResult(
                passed=scripted_passed,
                score=None,
                detail=f"judge unavailable ({exc}); used scripted verdict",
                grader_type=self.grader_type,
            )
        parsed = _parse_judge_response(content)
        return GradeResult(
            passed=parsed.get("passed", False),
            score=parsed.get("score"),
            detail=parsed.get("detail", "") or ("judge passed" if parsed.get("passed") else "judge failed"),
            grader_type=self.grader_type,
        )

    def _call_judge(self, prompt: str) -> str:
        base_url = self.judge_config.get("base_url")
        model = self.judge_config.get("model", "judge")
        api_key = self.judge_config.get("api_key", "")
        if self._transport is not None:
            return self._transport(base_url, model, prompt, api_key)
        return _http_judge(base_url, model, prompt, api_key)


def _http_judge(base_url: str, model: str, prompt: str, api_key: str) -> str:
    """Default transport: POST to an OpenAI-compatible chat-completions endpoint.

    Runs synchronously (the gate is a batch/CI command, not latency-critical).
    """
    import httpx

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 512,
    }
    resp = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions", json=payload, headers=headers, timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def resolve_graders(
    spec: list[dict[str, Any]] | None,
    judge_cfg: dict[str, Any] | None = None,
) -> list[Grader]:
    """Build the grader list for a task from its YAML spec.

    - ``None`` / empty → a single ScriptedGrader (default, cheap, deterministic)
    - Each entry's ``type`` selects the grader; missing ``type`` defaults to
      scripted. LLM-judge entries pull the shared ``judge_config``.
    """
    if not spec:
        return [ScriptedGrader()]
    graders: list[Grader] = []
    for entry in spec:
        gtype = entry.get("type", "scripted")
        if gtype == "llm-judge":
            graders.append(LlmJudgeGrader(judge_cfg, rubric=entry.get("rubric", "")))
        else:
            graders.append(ScriptedGrader())
    return graders
