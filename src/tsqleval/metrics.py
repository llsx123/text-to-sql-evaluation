"""Aggregate metrics and uncertainty for the evaluation runs."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .evaluator import QueryRun
from .questions import Question


def to_frame(runs: list[QueryRun]) -> pd.DataFrame:
    return pd.DataFrame([run.__dict__ for run in runs])


def summarize(runs: list[QueryRun]) -> dict[str, float]:
    frame = to_frame(runs)
    n = len(frame)
    executed = int(frame["executed"].sum())
    correct = int(frame["correct"].sum())
    latencies = frame.loc[frame["executed"], "elapsed_ms"]
    return {
        "questions": n,
        "executed": executed,
        "execution_rate": executed / n if n else float("nan"),
        "correct": correct,
        "accuracy": correct / n if n else float("nan"),
        "accuracy_given_executed": correct / executed if executed else float("nan"),
        "syntax_errors": int((frame["reason"] == "syntax_error").sum()),
        "unknown_schema_errors": int((frame["reason"] == "unknown_schema").sum()),
        "timeouts": int((frame["reason"] == "timeout").sum()),
        "unsafe_blocked": int((frame["reason"] == "unsafe_query").sum()),
        "truncated": int(frame["truncated"].sum()),
        "latency_p50_ms": float(np.percentile(latencies, 50)) if len(latencies) else float("nan"),
        "latency_p95_ms": float(np.percentile(latencies, 95)) if len(latencies) else float("nan"),
    }


def by_difficulty(runs: list[QueryRun], questions: tuple[Question, ...]) -> pd.DataFrame:
    difficulty = {q.id: q.difficulty for q in questions}
    frame = to_frame(runs)
    frame["difficulty"] = frame["question_id"].map(difficulty)
    grouped = frame.groupby("difficulty").agg(
        questions=("question_id", "count"),
        executed=("executed", "sum"),
        correct=("correct", "sum"),
    )
    grouped["accuracy"] = (grouped["correct"] / grouped["questions"]).round(4)
    grouped["execution_rate"] = (grouped["executed"] / grouped["questions"]).round(4)
    order = ["easy", "medium", "hard"]
    return grouped.reindex([level for level in order if level in grouped.index]).reset_index()


def error_breakdown(runs: list[QueryRun]) -> pd.DataFrame:
    frame = to_frame(runs)
    failed = frame[~frame["correct"]]
    counts = failed["reason"].value_counts()
    table = counts.rename_axis("reason").reset_index(name="count")
    table["share"] = (table["count"] / len(frame)).round(4)
    return table


def bootstrap_accuracy_diff(
    runs_a: list[QueryRun],
    runs_b: list[QueryRun],
    n_boot: int = 2000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict[str, float]:
    """Paired bootstrap over questions for ``accuracy_b - accuracy_a``."""
    a = {run.question_id: int(run.correct) for run in runs_a}
    b = {run.question_id: int(run.correct) for run in runs_b}
    ids = sorted(set(a) & set(b))
    if not ids:
        raise ValueError("no overlapping questions")
    a_values = np.array([a[qid] for qid in ids], dtype=float)
    b_values = np.array([b[qid] for qid in ids], dtype=float)
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        sample = rng.integers(0, len(ids), size=len(ids))
        diffs[i] = b_values[sample].mean() - a_values[sample].mean()
    point = float(b_values.mean() - a_values.mean())
    return {
        "estimate": point,
        "ci_low": float(np.quantile(diffs, alpha / 2)),
        "ci_high": float(np.quantile(diffs, 1 - alpha / 2)),
        "p_value": float(min(1.0, 2 * min(np.mean(diffs <= 0), np.mean(diffs >= 0))) or 1.0 / (n_boot + 1)),
        "n_boot": int(n_boot),
    }
