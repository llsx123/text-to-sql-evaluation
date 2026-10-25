"""Deterministic candidate SQL generation by mutating the gold query.

**This is not an LLM.** The repository has no model credentials, so the two simulated
"system versions" are produced by applying SQL-level error operators to the gold query:

* ``baseline`` — 45% of questions get one random mutation (rough approximation of a
  weak model, plus three deliberately truncated queries to exercise syntax errors);
* ``improved`` — 20% of questions get one mutation (rough approximation of a better
  model).

Every generated query is recorded together with the mutation that produced it, so the
evaluator's measurement can be audited. Metrics in the report therefore describe
**these candidate sets**, not any real Text-to-SQL model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from .config import CandidateConfig
from .questions import Question

MUTATIONS = (
    "drop_where",
    "drop_groupby",
    "drop_order",
    "drop_limit",
    "drop_distinct",
    "sum_to_count",
    "shift_date",
    "flip_order",
    "bad_column",
)


@dataclass(frozen=True)
class Candidate:
    question_id: str
    version: str
    sql: str
    mutation: str | None


def _top_level_index(sql: str, keyword: str) -> int:
    """Index of a keyword that appears at parenthesis depth 0, or -1."""
    pattern = re.compile(rf"\b{keyword}\b", re.IGNORECASE)
    depth = 0
    quote: str | None = None
    i = 0
    while i < len(sql):
        char = sql[i]
        if quote:
            if char == quote:
                quote = None
            i += 1
            continue
        if char in ("'", '"'):
            quote = char
            i += 1
            continue
        if char == "(":
            depth += 1
            i += 1
            continue
        if char == ")":
            depth -= 1
            i += 1
            continue
        if depth == 0:
            match = pattern.match(sql, i)
            if match:
                return match.start()
        i += 1
    return -1


def _remove_clause(sql: str, keyword: str, next_keywords: tuple[str, ...]) -> str | None:
    start = _top_level_index(sql, keyword)
    if start == -1:
        return None
    end = len(sql)
    for next_keyword in next_keywords:
        position = _top_level_index(sql[start + len(keyword):], next_keyword)
        if position != -1:
            candidate_end = start + len(keyword) + position
            if candidate_end < end:
                end = candidate_end
    return (sql[:start] + sql[end:]).strip()


def _drop_where(sql: str) -> str | None:
    return _remove_clause(sql, "WHERE", ("GROUP BY", "ORDER BY", "LIMIT", "HAVING"))


def _drop_groupby(sql: str) -> str | None:
    return _remove_clause(sql, "GROUP BY", ("ORDER BY", "LIMIT", "HAVING"))


def _drop_order(sql: str) -> str | None:
    return _remove_clause(sql, "ORDER BY", ("LIMIT",))


def _drop_limit(sql: str) -> str | None:
    return _remove_clause(sql, "LIMIT", ())


def _drop_distinct(sql: str) -> str | None:
    if "DISTINCT " not in sql.upper():
        return None
    return re.sub(r"DISTINCT\s+", "", sql, count=1, flags=re.IGNORECASE)


def _sum_to_count(sql: str) -> str | None:
    if "SUM(" not in sql.upper():
        return None
    return re.sub(r"SUM\(", "COUNT(", sql, count=1, flags=re.IGNORECASE)


def _shift_date(sql: str) -> str | None:
    match = re.search(r"'(2024-\d{2}-\d{2})'", sql)
    if not match:
        return None
    return sql.replace(f"'{match.group(1)}'", f"'2023{match.group(1)[4:]}'", 1)


def _flip_order(sql: str) -> str | None:
    if " DESC" not in sql.upper():
        return None
    index = sql.upper().rfind(" DESC")
    return sql[:index] + " ASC" + sql[index + len(" DESC"):]


def _bad_column(sql: str) -> str | None:
    for column in ("purchase_ts", "order_status", "quantity", "unit_price", "category", "state"):
        match = re.search(rf"\b{column}\b", sql, re.IGNORECASE)
        if match:
            return sql[: match.start()] + "missing_column" + sql[match.end():]
    return None


def _truncate(sql: str) -> str:
    return sql[: max(20, int(len(sql) * 0.6))]


_OPERATORS = {
    "drop_where": _drop_where,
    "drop_groupby": _drop_groupby,
    "drop_order": _drop_order,
    "drop_limit": _drop_limit,
    "drop_distinct": _drop_distinct,
    "sum_to_count": _sum_to_count,
    "shift_date": _shift_date,
    "flip_order": _flip_order,
    "bad_column": _bad_column,
}

_WEIGHTS = {
    "drop_where": 0.14,
    "drop_groupby": 0.12,
    "drop_order": 0.12,
    "drop_limit": 0.10,
    "drop_distinct": 0.08,
    "sum_to_count": 0.14,
    "shift_date": 0.10,
    "flip_order": 0.10,
    "bad_column": 0.10,
}


def mutate(question: Question, rng: np.random.Generator) -> tuple[str, str | None]:
    """Apply one applicable mutation; fall back to the gold query if none applies."""
    names = list(_WEIGHTS)
    probabilities = np.array([_WEIGHTS[name] for name in names], dtype=float)
    probabilities = probabilities / probabilities.sum()
    for name in rng.choice(names, size=len(names), replace=False, p=probabilities):
        # Ordering mutations only matter for questions where the order is part of the answer.
        if name in ("drop_order", "flip_order", "drop_limit") and not question.order_sensitive:
            continue
        result = _OPERATORS[name](question.gold_sql)
        if result and result.strip() != question.gold_sql.strip():
            return result, name
    return question.gold_sql, None


def generate_candidates(questions: tuple[Question, ...], cfg: CandidateConfig) -> list[Candidate]:
    rng = np.random.default_rng(cfg.seed)
    candidates: list[Candidate] = []
    for question in questions:
        if question.id in cfg.syntax_error_questions:
            candidates.append(Candidate(question.id, cfg.name, _truncate(question.gold_sql), "truncate"))
            continue
        if rng.random() < cfg.mutation_rate:
            sql, mutation = mutate(question, rng)
            candidates.append(Candidate(question.id, cfg.name, sql, mutation))
        else:
            candidates.append(Candidate(question.id, cfg.name, question.gold_sql, None))
    return candidates
