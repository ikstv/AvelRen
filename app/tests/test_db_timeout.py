"""#16: API connections must have a bounded query execution time.

Without statement_timeout, one expensive/pathological query would hold a pool
connection indefinitely and exhaust the pool. We check the behavior itself — a
slow query is cancelled — not the presence of a line in the config. A real DB is
required.
"""

import asyncio

import psycopg
import pytest

from avelren import db


def test_api_pool_aborts_slow_query() -> None:
    db._pool = None
    pool = db.get_pool(statement_timeout_ms=100)

    async def run() -> None:
        await pool.open(wait=True, timeout=10)
        try:
            async with pool.connection() as conn:
                with pytest.raises(psycopg.errors.QueryCanceled):
                    await conn.execute("SELECT pg_sleep(1)")
        finally:
            await pool.close()

    try:
        asyncio.run(run())
    finally:
        db._pool = None


def test_default_pool_has_no_statement_timeout_option() -> None:
    """The shared db.py code stays neutral: only the API enables the timeout,
    so collector/notifier/watchdog do not get it by accident."""
    db._pool = None
    pool = db.get_pool()
    try:
        assert "statement_timeout" not in (pool.kwargs.get("options") or "")
    finally:
        db._pool = None
