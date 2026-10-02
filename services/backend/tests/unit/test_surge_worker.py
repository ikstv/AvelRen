"""Worker не опитує джерело й повторює цикл лише раз на хвилину."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from avelren import surge_store, surge_worker


def test_disabled_worker_without_schema_does_not_open_pool(monkeypatch):
    monkeypatch.setattr(surge_worker.settings, "surge_enabled", False)
    denied = AsyncMock(side_effect=AssertionError("pool opened"))
    monkeypatch.setattr(surge_worker, "get_pool", denied)
    assert asyncio.run(surge_worker.run_cycle(datetime(2026, 10, 2, tzinfo=UTC))) == 0
    denied.assert_not_called()


class Connection:
    def __init__(self, locked=True):
        self.cur = Mock()
        self.cur.execute = AsyncMock()
        self.cur.fetchone = AsyncMock(return_value=(locked,))
        self.cur.fetchall = AsyncMock(return_value=[(1,), (17,)])

    def cursor(self, **kwargs):
        return self.cur

    @asynccontextmanager
    async def transaction(self):
        yield

    @asynccontextmanager
    async def connection(self):
        yield self


@pytest.mark.parametrize("locked", [False, True])
def test_cycle_lock_and_checkpoint_failure_isolation(monkeypatch, locked):
    conn = Connection(locked)
    monkeypatch.setattr(surge_worker.settings, "surge_enabled", True)
    pool = Mock(return_value=conn)
    monkeypatch.setattr(surge_worker, "get_pool", pool)
    gate = AsyncMock()
    monkeypatch.setattr(surge_worker, "assert_surge_schema", gate)
    process = AsyncMock(side_effect=[ValueError("fixture"), None])
    monkeypatch.setattr(surge_store, "process_checkpoint", process)
    result = asyncio.run(surge_worker.run_cycle(datetime(2026, 10, 2, tzinfo=UTC)))
    assert result == int(locked)
    assert process.await_count == (2 if locked else 0)
    pool.assert_called_once_with(statement_timeout_ms=5000)
    gate.assert_awaited_once_with(conn)
