"""The evaluation set itself: unique ids, verified gold SQL, consistent metadata."""

from __future__ import annotations

import pytest

from tsqleval import questions


def test_question_ids_are_unique():
    ids = [q.id for q in questions.QUESTIONS]
    assert len(ids) == len(set(ids))


def test_every_question_has_required_metadata():
    for question in questions.QUESTIONS:
        assert question.question.strip()
        assert question.gold_sql.strip().lower().startswith(("select", "with"))
        assert question.difficulty in ("easy", "medium", "hard")
        assert question.qtype


def test_order_sensitive_matches_sql():
    for question in questions.QUESTIONS:
        has_order = "order by" in question.gold_sql.lower()
        assert has_order == question.order_sensitive, question.id


def test_all_gold_queries_execute_and_return_rows(guard):
    for question in questions.QUESTIONS:
        result = guard.execute(question.gold_sql)
        assert result.executed, (question.id, result.error)
        assert result.rows, question.id
        assert not result.truncated, question.id


def test_gold_queries_are_read_only(guard):
    for question in questions.QUESTIONS:
        result = guard.execute(question.gold_sql)
        assert result.error_type is None, (question.id, result.error)


def test_difficulty_distribution_is_balanced():
    counts = questions.questions_by_difficulty()
    assert counts.get("easy", 0) >= 5
    assert counts.get("medium", 0) >= 8
    assert counts.get("hard", 0) >= 4
    assert sum(counts.values()) == len(questions.QUESTIONS)
