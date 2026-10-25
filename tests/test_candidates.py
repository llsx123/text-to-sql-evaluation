"""Candidate generation: deterministic, reproducible, and genuinely different from gold."""

from __future__ import annotations

import numpy as np

from tsqleval import candidates
from tsqleval.config import BASELINE, IMPROVED, CandidateConfig
from tsqleval.questions import QUESTIONS, get_question


def test_candidates_are_deterministic():
    first = candidates.generate_candidates(QUESTIONS, BASELINE)
    second = candidates.generate_candidates(QUESTIONS, BASELINE)
    assert [c.sql for c in first] == [c.sql for c in second]
    assert [c.mutation for c in first] == [c.mutation for c in second]


def test_improved_applies_fewer_mutations():
    baseline = candidates.generate_candidates(QUESTIONS, BASELINE)
    improved = candidates.generate_candidates(QUESTIONS, IMPROVED)
    baseline_mutations = sum(c.mutation is not None for c in baseline)
    improved_mutations = sum(c.mutation is not None for c in improved)
    assert improved_mutations < baseline_mutations


def test_every_candidate_is_a_select_statement():
    for cfg in (BASELINE, IMPROVED):
        for candidate in candidates.generate_candidates(QUESTIONS, cfg):
            assert candidate.sql.lstrip().lower().startswith(("select", "with"))


def test_mutation_is_recorded_only_when_sql_changes():
    for candidate in candidates.generate_candidates(QUESTIONS, BASELINE):
        gold = get_question(candidate.question_id).gold_sql
        if candidate.mutation is None:
            assert candidate.sql == gold
        else:
            assert candidate.sql != gold


def test_forced_syntax_errors_are_broken(guard):
    for candidate in candidates.generate_candidates(QUESTIONS, BASELINE):
        if candidate.question_id in BASELINE.syntax_error_questions:
            result = guard.execute(candidate.sql)
            assert not result.executed
            assert result.error_type == "syntax_error"


def test_each_operator_changes_the_result(guard):
    """Spot-check that mutations are semantically meaningful, not cosmetic."""
    from tsqleval.compare import compare_results

    cases = {
        "drop_where": "q02",
        "drop_groupby": "q10",
        "sum_to_count": "q04",
        "flip_order": "q08",
        "drop_limit": "q08",
        "drop_distinct": "q03",
        "bad_column": "q11",
        "shift_date": "q18",
    }
    for mutation, question_id in cases.items():
        question = get_question(question_id)
        mutated = candidates._OPERATORS[mutation](question.gold_sql)
        assert mutated is not None, mutation
        gold = guard.execute(question.gold_sql)
        candidate = guard.execute(mutated)
        if candidate.executed:
            assert not compare_results(gold.rows, candidate.rows, question.order_sensitive).match, mutation
        else:
            assert candidate.error_type in ("unknown_schema", "syntax_error", "runtime_error")


def test_empty_configuration_returns_gold(guard):
    cfg = CandidateConfig(name="perfect", mutation_rate=0.0, seed=1)
    generated = candidates.generate_candidates(QUESTIONS, cfg)
    assert all(c.mutation is None for c in generated)
    for candidate in generated:
        question = get_question(candidate.question_id)
        assert candidate.sql == question.gold_sql


def test_rng_state_does_not_leak_between_versions():
    baseline = candidates.generate_candidates(QUESTIONS, BASELINE)
    improved = candidates.generate_candidates(QUESTIONS, IMPROVED)
    assert len(baseline) == len(improved) == len(QUESTIONS)
    assert [c.question_id for c in baseline] == [q.id for q in QUESTIONS]
    assert isinstance(np.random.default_rng(0), np.random.Generator)
