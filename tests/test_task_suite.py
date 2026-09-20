"""Tests for src.task_suite — load + validate a curated task suite."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.task_suite import Task, load_suite, load_task


def _write(tmp_path, name, body):
    f = tmp_path / name
    f.write_text(textwrap.dedent(body), encoding="utf-8")
    return f


def test_load_task_basic(tmp_path):
    f = _write(tmp_path, "t.yaml", """
        name: create-project-happy
        description: "happy path"
        form: CreateProjectForm
        data:
          name: "Test Project"
          owner: "terry@example.com"
    """)
    task = load_task(str(f))
    assert task.name == "create-project-happy"
    assert task.form == "CreateProjectForm"
    assert task.data == {"name": "Test Project", "owner": "terry@example.com"}
    assert task.graders == []           # default
    assert task.cost_limits is None


def test_load_task_graders_and_cost_limits(tmp_path):
    f = _write(tmp_path, "t.yaml", """
        name: q
        form: F
        data: {a: 1}
        graders:
          - type: llm-judge
            rubric: "coherent"
        cost_limits:
          max_tokens_out: 4000
          max_latency_s: 120
    """)
    task = load_task(str(f))
    assert task.graders == [{"type": "llm-judge", "rubric": "coherent"}]
    assert task.cost_limits == {"max_tokens_out": 4000, "max_latency_s": 120}


def test_load_task_missing_form_raises(tmp_path):
    f = _write(tmp_path, "bad.yaml", """
        name: bad
        data: {a: 1}
    """)
    with pytest.raises(Exception) as exc:
        load_task(str(f))
    assert "form" in str(exc.value)


def test_load_task_missing_data_raises(tmp_path):
    f = _write(tmp_path, "bad.yaml", """
        name: bad
        form: F
    """)
    with pytest.raises(Exception) as exc:
        load_task(str(f))
    assert "data" in str(exc.value)


def test_load_suite_from_directory(tmp_path):
    for name in ("a.yaml", "b.yaml", "c.yaml"):
        _write(tmp_path, name, f"name: {name[:-5]}\nform: F\ndata: {{k: v}}\n")
    tasks = load_suite(str(tmp_path))
    assert len(tasks) == 3
    assert {t.name for t in tasks} == {"a", "b", "c"}


def test_load_suite_ignores_non_yaml(tmp_path):
    _write(tmp_path, "a.yaml", "name: a\nform: F\ndata: {k: v}\n")
    (tmp_path / "notes.txt").write_text("not a task")
    assert len(load_suite(str(tmp_path))) == 1


def test_load_suite_empty_dir_raises(tmp_path):
    with pytest.raises(Exception) as exc:
        load_suite(str(tmp_path))
    assert "no task" in str(exc.value).lower()
