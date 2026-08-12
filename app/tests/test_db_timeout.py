"""#16: API-конекшени мусять мати обмежений час виконання запиту.

Без statement_timeout один дорогий/патологічний запит тримав би конекшен із
пулу нескінченно й вичерпав би пул. Перевіряємо саме поведінку — повільний
запит скасовується, — а не наявність рядка в конфізі. Потрібна реальна БД.
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
    """Спільний код db.py лишається нейтральним: тільки API вмикає timeout,
    тож collector/notifier/watchdog не отримують його випадково."""
    db._pool = None
    pool = db.get_pool()
    try:
        assert "statement_timeout" not in (pool.kwargs.get("options") or "")
    finally:
        db._pool = None
