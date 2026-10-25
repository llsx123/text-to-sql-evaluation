"""The read-only guard must block every mutation path and keep read queries working."""

from __future__ import annotations

import hashlib

import pytest

from tsqleval.guard import QueryGuard, split_statements, validate_sql, UnsafeQueryError


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO users VALUES ('u9', 'c', 'SP', '2024-01-01')",
        "UPDATE users SET state = 'RJ'",
        "DELETE FROM orders",
        "DROP TABLE orders",
        "CREATE TABLE hack (x INTEGER)",
        "ALTER TABLE users ADD COLUMN hack TEXT",
        "ATTACH DATABASE 'evil.db' AS evil",
        "PRAGMA table_info(users)",
        "VACUUM",
        "SELECT 1; DROP TABLE users",
    ],
)
def test_mutating_statements_are_rejected(guard, sql):
    result = guard.execute(sql)
    assert not result.executed
    assert result.error_type in ("unsafe_query", "syntax_error")


def test_write_through_cte_is_rejected(guard):
    result = guard.execute("WITH x AS (SELECT 1) DELETE FROM orders")
    assert not result.executed
    assert result.error_type in ("unsafe_query", "syntax_error")


def test_dangerous_functions_are_rejected(guard):
    for sql in ("SELECT load_extension('x')", "SELECT readfile('C:/Windows/win.ini')", "SELECT writefile('x', 'y')"):
        result = guard.execute(sql)
        assert not result.executed, sql
        assert result.error_type == "unsafe_query", (sql, result.error)


def test_read_queries_still_work(guard):
    result = guard.execute("SELECT COUNT(*) AS n FROM orders")
    assert result.executed
    assert result.rows[0][0] > 0
    assert result.columns == ["n"]


def test_comments_and_string_literals_do_not_confuse_the_splitter():
    assert split_statements("-- comment; not a terminator\nSELECT 1") == ["SELECT 1"]
    assert split_statements("SELECT ';' AS s") == ["SELECT ';' AS s"]
    assert validate_sql("SELECT 1;") == "SELECT 1"
    with pytest.raises(UnsafeQueryError):
        validate_sql("SELECT 1; SELECT 2")


def test_timeout_interrupts_a_runaway_query(shop_db):
    quick_guard = QueryGuard(shop_db, timeout_seconds=0.2, max_rows=100)
    result = quick_guard.execute(
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 100000000) SELECT COUNT(*) FROM c"
    )
    assert not result.executed
    assert result.error_type == "timeout"


def test_row_limit_flags_truncation(shop_db):
    limited = QueryGuard(shop_db, timeout_seconds=5.0, max_rows=10)
    result = limited.execute("SELECT order_id FROM orders")
    assert result.executed
    assert result.truncated
    assert len(result.rows) == 10


def test_database_file_is_not_modified_by_reads_or_blocked_writes(shop_db):
    before = hashlib.sha256(shop_db.read_bytes()).hexdigest()
    guard = QueryGuard(shop_db)
    guard.execute("SELECT COUNT(*) FROM orders")
    guard.execute("DROP TABLE orders")
    guard.execute("INSERT INTO users VALUES ('x', 'y', 'SP', '2024-01-01')")
    after = hashlib.sha256(shop_db.read_bytes()).hexdigest()
    assert before == after


def test_nonexistent_database_path_fails_loudly(tmp_path):
    guard = QueryGuard(tmp_path / "missing.db")
    result = guard.execute("SELECT 1")
    assert not result.executed
    assert result.error_type == "runtime_error"
