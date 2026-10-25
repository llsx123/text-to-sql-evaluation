"""Metrics aggregation and paired bootstrap on synthetic runs."""

from __future__ import annotations

import numpy as np
import pytest

from tsqleval import metrics
from tsqleval.evaluator import QueryRun
from tsqleval.questions import QUESTIONS


def _run(question_id: str, correct: bool, executed: bool = True, reason: str = "match",
         version: str = "v1", elapsed_ms: float = 1.0, truncated: bool = False) -> QueryRun:
    return QueryRun(
        question_id=question_id,
        version=version,
        sql="SELECT 1",
        mutation=None,
        executed=executed,
        correct=correct,
        reason=reason if executed else reason,
        error_type=None if executed else reason,
        elapsed_ms=elapsed_ms,
        rows=1 if executed else 0,
        truncated=truncated,
    )


def test_summary_rates():
    runs = [
        _run("q01", True),
        _run("q02", False, reason="wrong_values"),
        _run("q03", False, executed=False, reason="syntax_error"),
        _run("q04", False, executed=False, reason="timeout"),
    ]
    summary = metrics.summarize(runs)
    assert summary["questions"] == 4
    assert summary["executed"] == 2
    assert summary["execution_rate"] == pytest.approx(0.5)
    assert summary["correct"] == 1
    assert summary["accuracy"] == pytest.approx(0.25)
    assert summary["accuracy_given_executed"] == pytest.approx(0.5)
    assert summary["syntax_errors"] == 1
    assert summary["timeouts"] == 1


def test_error_breakdown_counts_failures():
    runs = [
        _run("q01", True),
        _run("q02", False, reason="wrong_values"),
        _run("q03", False, reason="wrong_values"),
        _run("q04", False, executed=False, reason="syntax_error"),
    ]
    table = metrics.error_breakdown(runs).set_index("reason")
    assert table.loc["wrong_values", "count"] == 2
    assert table.loc["syntax_error", "count"] == 1
    assert "match" not in table.index


def test_difficulty_breakdown_covers_all_questions():
    runs = [_run(q.id, i % 2 == 0) for i, q in enumerate(QUESTIONS)]
    table = metrics.by_difficulty(runs, QUESTIONS)
    assert table["questions"].sum() == len(QUESTIONS)
    assert set(table["difficulty"]) <= {"easy", "medium", "hard"}


def test_bootstrap_is_reproducible():
    runs_a = [_run(q.id, i < 10) for i, q in enumerate(QUESTIONS)]
    runs_b = [_run(q.id, i < 18) for i, q in enumerate(QUESTIONS)]
    first = metrics.bootstrap_accuracy_diff(runs_a, runs_b, n_boot=300, seed=5)
    second = metrics.bootstrap_accuracy_diff(runs_a, runs_b, n_boot=300, seed=5)
    assert first == second


def test_bootstrap_interval_for_clear_improvement():
    runs_a = [_run(q.id, False) for q in QUESTIONS]
    runs_b = [_run(q.id, True) for q in QUESTIONS]
    result = metrics.bootstrap_accuracy_diff(runs_a, runs_b, n_boot=300, seed=7)
    assert result["estimate"] == pytest.approx(1.0)
    assert result["ci_low"] == pytest.approx(1.0)
    assert result["ci_high"] == pytest.approx(1.0)


def test_bootstrap_detects_no_difference():
    runs_a = [_run(q.id, i % 3 == 0) for i, q in enumerate(QUESTIONS)]
    runs_b = [_run(q.id, i % 3 == 1) for i, q in enumerate(QUESTIONS)]
    result = metrics.bootstrap_accuracy_diff(runs_a, runs_b, n_boot=500, seed=9)
    assert result["ci_low"] < 0 < result["ci_high"]


def test_frame_roundtrip():
    runs = [_run("q01", True), _run("q02", False)]
    frame = metrics.to_frame(runs)
    assert list(frame.columns) == list(runs[0].__dict__.keys())
    assert len(frame) == 2
