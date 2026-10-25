"""Evaluator behaviour: classification of execution errors and result mismatches."""

from __future__ import annotations

from tsqleval import candidates, evaluator
from tsqleval.config import CandidateConfig
from tsqleval.questions import get_question


def _run(guard, question_id: str, sql: str):
    question = get_question(question_id)
    gold = guard.execute(question.gold_sql)
    result = guard.execute(sql)
    candidate = candidates.Candidate(question_id=question_id, version="test", sql=sql, mutation="manual")
    return evaluator.evaluate_candidate(question, candidate, gold, result)


def test_perfect_candidate_is_correct(guard):
    question = get_question("q08")
    run = _run(guard, "q08", question.gold_sql)
    assert run.executed and run.correct
    assert run.reason == "match"


def test_missing_where_is_wrong_values(guard):
    run = _run(guard, "q02", "SELECT COUNT(*) AS canceled_orders FROM orders")
    assert run.executed
    assert not run.correct
    assert run.reason in ("wrong_values", "wrong_row_count")


def test_syntax_error_is_classified(guard):
    run = _run(guard, "q01", "SELECT COUNT(*) FROM orders WHERE")
    assert not run.executed
    assert run.reason == "syntax_error"
    assert run.error_type == "syntax_error"


def test_unknown_column_is_classified(guard):
    run = _run(guard, "q01", "SELECT COUNT(*) FROM orders WHERE missing_column = '2024-01-01'")
    assert not run.executed
    assert run.reason == "unknown_schema"


def test_wrong_order_is_classified(guard):
    question = get_question("q06")
    run = _run(guard, "q06", question.gold_sql.replace("DESC", "ASC"))
    assert run.executed
    assert not run.correct
    assert run.reason == "order_mismatch"


def test_extra_column_is_wrong_columns(guard):
    question = get_question("q03")
    run = _run(guard, "q03", "SELECT COUNT(DISTINCT category) AS n, COUNT(*) AS m FROM products")
    assert run.executed
    assert not run.correct
    assert run.reason == "wrong_columns"


def test_run_is_json_serialisable(guard):
    question = get_question("q09")
    run = _run(guard, "q09", question.gold_sql)
    payload = evaluator.run_to_dict(run)
    assert payload["question_id"] == "q09"
    assert payload["correct"] is True
    assert isinstance(payload["elapsed_ms"], float)


def test_exact_gold_candidate_set_scores_100_percent(guard):
    cfg = CandidateConfig(name="perfect", mutation_rate=0.0, seed=1)
    generated = candidates.generate_candidates(
        (get_question("q01"), get_question("q08"), get_question("q15")), cfg
    )
    runs = []
    for candidate in generated:
        question = get_question(candidate.question_id)
        gold = guard.execute(question.gold_sql)
        result = guard.execute(candidate.sql)
        runs.append(evaluator.evaluate_candidate(question, candidate, gold, result))
    assert all(run.correct for run in runs)
