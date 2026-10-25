"""Shared fixtures for the Text-to-SQL evaluation test-suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tsqleval import data  # noqa: E402
from tsqleval.config import MAX_RESULT_ROWS, QUERY_TIMEOUT_SECONDS  # noqa: E402
from tsqleval.guard import QueryGuard  # noqa: E402


@pytest.fixture(scope="session")
def shop_db(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("tsql") / "shop.db"
    return data.build_database(path)


@pytest.fixture(scope="session")
def guard(shop_db) -> QueryGuard:
    return QueryGuard(shop_db, timeout_seconds=QUERY_TIMEOUT_SECONDS, max_rows=MAX_RESULT_ROWS)
