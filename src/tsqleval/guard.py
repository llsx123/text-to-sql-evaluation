"""Read-only SQL execution guard.

Security model (defence in depth, no string blacklists):

1. **Read-only file**: the database is opened with SQLite URI ``mode=ro``; even if a
   write statement slipped through, the file cannot be modified.
2. **Authorizer**: a callback allows only ``SELECT`` / ``READ`` / ``FUNCTION`` (and
   ``RECURSIVE`` for CTEs) and denies everything else — DDL, DML, ``ATTACH``,
   ``PRAGMA``, transactions. Dangerous functions (``load_extension``, ``readfile``,
   ``writefile`` ...) are denied by name.
3. **Single statement**: a quote/comment-aware splitter rejects stacked statements.
4. **Timeout**: a progress handler aborts long-running queries.
5. **Row cap**: the query is wrapped in ``SELECT * FROM (...) LIMIT n+1`` and the
   ``truncated`` flag reports when the cap was hit.

Only layer (1) alone would be fragile (``ATTACH`` can open other files), and only
string matching would be bypassable; the layers are independent.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import MAX_RESULT_ROWS, QUERY_TIMEOUT_SECONDS

FORBIDDEN_FUNCTIONS = {"load_extension", "readfile", "writefile", "fsdir", "edit", "zipfile"}
_FORBIDDEN_PATTERN = re.compile(r"\b(" + "|".join(sorted(FORBIDDEN_FUNCTIONS)) + r")\s*\(", re.IGNORECASE)

_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):
    _ALLOWED_ACTIONS.add(sqlite3.SQLITE_RECURSIVE)


class UnsafeQueryError(Exception):
    """Raised before execution when a statement fails the safety policy."""


@dataclass
class ExecutionResult:
    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    elapsed_ms: float = 0.0
    error: str | None = None
    error_type: str | None = None
    truncated: bool = False

    @property
    def executed(self) -> bool:
        return self.error is None


def split_statements(sql: str) -> list[str]:
    """Split on top-level semicolons, ignoring quotes and comments."""
    statements: list[str] = []
    buffer: list[str] = []
    i = 0
    n = len(sql)
    quote: str | None = None
    while i < n:
        char = sql[i]
        if quote:
            buffer.append(char)
            if char == quote:
                # '' inside a string literal is an escaped quote, not a terminator
                if i + 1 < n and sql[i + 1] == quote:
                    buffer.append(sql[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if char in ("'", '"'):
            quote = char
            buffer.append(char)
            i += 1
            continue
        if char == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue
        if char == "/" and i + 1 < n and sql[i + 1] == "*":
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if char == ";":
            statements.append("".join(buffer))
            buffer = []
            i += 1
            continue
        buffer.append(char)
        i += 1

    statements.append("".join(buffer))
    return [s.strip() for s in statements if s.strip()]


def _strip_string_literals(sql: str) -> str:
    """Remove quoted literals so that function-name checks ignore data values."""
    return re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", "''", sql)


def validate_sql(sql: str) -> str:
    """Return the single normalised statement or raise :class:`UnsafeQueryError`."""
    if not sql or not sql.strip():
        raise UnsafeQueryError("empty statement")
    statements = split_statements(sql)
    if len(statements) != 1:
        raise UnsafeQueryError(f"expected exactly one statement, got {len(statements)}")
    statement = statements[0]
    first_word = statement.lstrip().split(None, 1)[0].lower()
    if first_word not in ("select", "with"):
        raise UnsafeQueryError(f"only SELECT / WITH queries are allowed, got {first_word!r}")
    # Supplementary check: the authorizer also blocks these names, but a function that
    # does not exist in this SQLite build fails before the authorizer is consulted.
    match = _FORBIDDEN_PATTERN.search(_strip_string_literals(statement))
    if match:
        raise UnsafeQueryError(f"forbidden function: {match.group(1)}")
    return statement


def _authorizer(action, arg1, arg2, dbname, trigger):  # noqa: ANN001 - sqlite3 callback signature
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in FORBIDDEN_FUNCTIONS:
        return sqlite3.SQLITE_DENY
    if action in _ALLOWED_ACTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def classify_error(error: str) -> str:
    message = (error or "").lower()
    if "syntax error" in message or "incomplete input" in message or "unrecognized token" in message:
        return "syntax_error"
    if "no such table" in message or "no such column" in message:
        return "unknown_schema"
    if "interrupted" in message:
        return "timeout"
    if "not authorized" in message or "prohibited" in message:
        return "unsafe_query"
    return "runtime_error"


class QueryGuard:
    """Executes one read-only query at a time against a fixed database file."""

    def __init__(self, db_path: Path, timeout_seconds: float = QUERY_TIMEOUT_SECONDS,
                 max_rows: int = MAX_RESULT_ROWS) -> None:
        self.db_path = Path(db_path)
        self.timeout_seconds = timeout_seconds
        self.max_rows = max_rows

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = None
        conn.execute("PRAGMA query_only = ON")
        conn.set_authorizer(_authorizer)
        return conn

    def execute(self, sql: str) -> ExecutionResult:
        try:
            statement = validate_sql(sql)
        except UnsafeQueryError as exc:
            return ExecutionResult(sql=sql, error=str(exc), error_type="unsafe_query")

        wrapped = f"SELECT * FROM (\n{statement}\n) LIMIT {self.max_rows + 1}"
        started = time.perf_counter()
        try:
            conn = self._connect()
        except sqlite3.Error as exc:
            return ExecutionResult(sql=sql, error=str(exc), error_type=classify_error(str(exc)))
        try:
            deadline = started + self.timeout_seconds
            conn.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 1000)
            cursor = conn.execute(wrapped)
            fetch_started = time.perf_counter()
            rows = cursor.fetchall()
            elapsed_ms = (fetch_started - started) * 1000
            columns = [description[0] for description in cursor.description or []]
            truncated = len(rows) > self.max_rows
            if truncated:
                rows = rows[: self.max_rows]
            return ExecutionResult(
                sql=sql,
                columns=columns,
                rows=[list(row) for row in rows],
                elapsed_ms=elapsed_ms,
                truncated=truncated,
            )
        except sqlite3.Error as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return ExecutionResult(
                sql=sql,
                elapsed_ms=elapsed_ms,
                error=str(exc),
                error_type=classify_error(str(exc)),
            )
        finally:
            conn.close()
