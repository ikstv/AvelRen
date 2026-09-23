"""Порядок запису циклу без PostgreSQL і запитів до джерела."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from avelren import collector


@pytest.mark.parametrize("source_error", [None, "HTTP 500", "HTTP 429", "timeout"])
def test_cycle_records_once_without_retry(monkeypatch, source_error):
    transactions = []

    @asynccontextmanager
    async def connection():
        transactions.append("begin")
        yield object()
        transactions.append("commit")

    result = SimpleNamespace(
        error=source_error, response=None, http_status=500 if source_error else 200,
        duration_ms=10, body_sha256=None,
    )
    fetch = AsyncMock(return_value=result)
    record = AsyncMock()
    monkeypatch.setattr(collector, "fetch_workload", fetch)
    monkeypatch.setattr(collector, "get_pool", lambda: SimpleNamespace(connection=connection))
    monkeypatch.setattr(collector, "record_run", record)
    monkeypatch.setattr(collector, "record_derived", AsyncMock())
    asyncio.run(collector.run_cycle(object()))
    fetch.assert_awaited_once()
    record.assert_awaited_once()
    assert record.await_args.args[-1] == source_error
    assert transactions == ["begin", "commit", "begin", "commit"]


def test_alert_failure_keeps_primary_commit(monkeypatch):
    events = []

    @asynccontextmanager
    async def connection():
        events.append("begin")
        try:
            yield object()
        except Exception:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    result = SimpleNamespace(
        error=None, http_status=200, duration_ms=10, body_sha256=None,
        response=SimpleNamespace(
            data=[SimpleNamespace(for_vehicle_type=1)],
            filters=SimpleNamespace(countries=[]),
        ),
    )
    monkeypatch.setattr(collector, "get_pool", lambda: SimpleNamespace(connection=connection))
    monkeypatch.setattr(collector, "fetch_workload", AsyncMock(return_value=result))
    for name in ("upsert_countries", "upsert_checkpoints", "record_run"):
        monkeypatch.setattr(collector, name, AsyncMock())
    insert = AsyncMock(return_value=1)
    monkeypatch.setattr(collector, "insert_observations", insert)
    monkeypatch.setattr(
        collector.alerts, "evaluate", AsyncMock(side_effect=RuntimeError("alert failure"))
    )
    derived = AsyncMock()
    monkeypatch.setattr(collector, "record_derived", derived)
    asyncio.run(collector.run_cycle(object()))
    insert.assert_awaited_once()
    assert events == ["begin", "commit", "begin", "rollback", "begin", "commit"]
    assert "alert failure" in derived.await_args.kwargs["error"]
