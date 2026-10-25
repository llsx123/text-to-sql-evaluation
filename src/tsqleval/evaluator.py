"""Run candidates against the guard and compare with the gold result."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .candidates import Candidate
from .compare import compare_column_counts, compare_results
from .guard import ExecutionResult
from .questions import Question


@dataclass
class QueryRun:
    question_id: str
    version: str
    sql: str
    mutation: str | None
    executed: bool
    correct: bool
    reason: str
    error_type: str | None
    elapsed_ms: float
    rows: int
    truncated: bool


def evaluate_candidate(
    question: Question,
    candidate: Candidate,
    gold: ExecutionResult,
    result: ExecutionResult,
) -> QueryRun:
    if not result.executed:
        return QueryRun(
            question_id=question.id,
            version=candidate.version,
            sql=candidate.sql,
            mutation=candidate.mutation,
            executed=False,
            correct=False,
            reason=result.error_type or "runtime_error",
            error_type=result.error_type,
            elapsed_ms=result.elapsed_ms,
            rows=0,
            truncated=False,
        )

    column_problem = compare_column_counts(gold.columns, result.columns)
    comparison = column_problem or compare_results(
        gold.rows, result.rows, order_sensitive=question.order_sensitive
    )
    return QueryRun(
        question_id=question.id,
        version=candidate.version,
        sql=candidate.sql,
        mutation=candidate.mutation,
        executed=True,
        correct=comparison.match,
        reason=comparison.reason,
        error_type=None,
        elapsed_ms=result.elapsed_ms,
        rows=len(result.rows),
        truncated=result.truncated,
    )


def run_to_dict(run: QueryRun) -> dict:
    return asdict(run)
