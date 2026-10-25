"""Result-set comparison with explicit semantics.

Three things are deliberately separated:

* **same SQL text** — irrelevant for correctness (two different queries can agree);
* **executes** — a query that errors is not a result;
* **same result** — compared as a multiset (or an ordered sequence when the gold query
  has a meaningful ``ORDER BY``), with NULLs equal only to NULLs, numeric values
  compared within a tolerance, and duplicate rows preserved.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .config import FLOAT_TOLERANCE


@dataclass
class ComparisonResult:
    match: bool
    reason: str
    detail: str = ""


_NULL = ("null",)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _cell_key(value: Any) -> tuple:
    if value is None:
        return _NULL
    if _is_number(value):
        return ("num", round(float(value), 6))
    if isinstance(value, bytes):
        return ("bytes", value)
    return ("str", str(value))


def _row_key(row: list) -> tuple:
    return tuple(_cell_key(value) for value in row)


def _cells_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if _is_number(left) and _is_number(right):
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=FLOAT_TOLERANCE)
    return left == right


def _rows_equal(left: list, right: list) -> bool:
    return len(left) == len(right) and all(_cells_equal(a, b) for a, b in zip(left, right))


def compare_results(
    gold_rows: list[list],
    candidate_rows: list[list],
    order_sensitive: bool,
) -> ComparisonResult:
    if len(gold_rows) == 0 and len(candidate_rows) > 0:
        return ComparisonResult(False, "unexpected_rows", f"gold empty, candidate returned {len(candidate_rows)} rows")
    if len(gold_rows) > 0 and len(candidate_rows) == 0:
        return ComparisonResult(False, "empty_result", f"gold has {len(gold_rows)} rows, candidate returned none")

    gold_sorted = sorted(gold_rows, key=_row_key)
    cand_sorted = sorted(candidate_rows, key=_row_key)

    if order_sensitive:
        if len(gold_rows) == len(candidate_rows) and all(
            _rows_equal(a, b) for a, b in zip(gold_rows, candidate_rows)
        ):
            return ComparisonResult(True, "match")
        if len(gold_sorted) == len(cand_sorted) and all(
            _rows_equal(a, b) for a, b in zip(gold_sorted, cand_sorted)
        ):
            return ComparisonResult(False, "order_mismatch", "same rows, different order")
    else:
        if len(gold_sorted) == len(cand_sorted) and all(
            _rows_equal(a, b) for a, b in zip(gold_sorted, cand_sorted)
        ):
            return ComparisonResult(True, "match")

    if len(gold_rows) != len(candidate_rows):
        return ComparisonResult(
            False, "wrong_row_count", f"gold {len(gold_rows)} rows, candidate {len(candidate_rows)} rows"
        )
    return ComparisonResult(False, "wrong_values", "same row count, different values")


def compare_column_counts(gold_columns: list[str], candidate_columns: list[str]) -> ComparisonResult | None:
    """Column-count mismatch is reported before looking at values."""
    if len(gold_columns) != len(candidate_columns):
        return ComparisonResult(
            False, "wrong_columns", f"gold {len(gold_columns)} columns, candidate {len(candidate_columns)}"
        )
    return None
