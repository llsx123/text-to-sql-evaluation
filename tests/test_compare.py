"""Result comparison semantics: NULL, floats, duplicates, order, shape."""

from __future__ import annotations

import pytest

from tsqleval.compare import compare_column_counts, compare_results


def test_exact_multiset_match():
    result = compare_results([[1, "a"], [2, "b"]], [[2, "b"], [1, "a"]], order_sensitive=False)
    assert result.match


def test_nulls_equal_only_nulls():
    assert compare_results([[None]], [[None]], False).match
    result = compare_results([[None]], [[0]], False)
    assert not result.match
    assert result.reason == "wrong_values"


def test_float_tolerance():
    assert compare_results([[12.3456789]], [[12.3456791]], False).match
    result = compare_results([[12.3456789]], [[12.346]], False)
    assert not result.match


def test_duplicate_rows_are_preserved():
    assert compare_results([[1], [1], [2]], [[1], [2], [1]], False).match
    result = compare_results([[1], [1], [2]], [[1], [2], [2]], False)
    assert not result.match


def test_order_sensitive_requires_same_sequence():
    gold = [["a", 1], ["b", 2]]
    result = compare_results(gold, [["b", 2], ["a", 1]], order_sensitive=True)
    assert not result.match
    assert result.reason == "order_mismatch"
    assert compare_results(gold, [["a", 1], ["b", 2]], order_sensitive=True).match


def test_order_insensitive_allows_any_order():
    assert compare_results([["a"], ["b"]], [["b"], ["a"]], order_sensitive=False).match


def test_row_count_mismatch():
    result = compare_results([[1], [2], [3]], [[1], [2]], False)
    assert result.reason == "wrong_row_count"


def test_empty_candidate_is_distinguished():
    result = compare_results([[1], [2]], [], False)
    assert result.reason == "empty_result"
    result = compare_results([], [[1]], False)
    assert result.reason == "unexpected_rows"


def test_column_count_mismatch():
    problem = compare_column_counts(["a", "b"], ["a"])
    assert problem is not None and problem.reason == "wrong_columns"
    assert compare_column_counts(["a"], ["x"]) is None  # names are not compared, only shape


def test_strings_are_compared_exactly():
    assert not compare_results([["abc"]], [["ABC"]], False).match


def test_integer_and_float_are_numerically_equal():
    assert compare_results([[1]], [[1.0]], False).match
