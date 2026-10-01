"""Replay against disposable TimescaleDB under the collector role."""

import asyncio
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from avelren.collector_replay import ReplayConflict, replay_once
from avelren.collector_spool import SpoolStore
from avelren.echerha import FetchResult
from avelren.models import WorkloadResponse

AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _result() -> FetchResult:
    return FetchResult(
        WorkloadResponse.model_validate({
            "filters": {"countries": [{"id": 1, "name": "Poland"}]},
            "data": [{
                "id": 7, "title": "Truck", "country_id": 1, "for_vehicle_type": 1,
                "wait_time": 60, "vehicle_in_active_queues_counts": 3,
            }],
        }),
        200, 9, "a" * 64, None,
    )


def _run(pool_dsn, store, now):
    async def go():
        pool = AsyncConnectionPool(pool_dsn, open=False, kwargs={"row_factory": dict_row})
        await pool.open(wait=True)
        try:
            return await replay_once(store, pool, now)
        finally:
            await pool.close()

    return asyncio.run(go())


def test_replay_commits_fifo(database, tmp_path):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    for minute in (0, 1):
        seq = store.begin(AT + timedelta(minutes=minute))
        store.finish(seq, _result(), 1)
    dsn = database("collector")
    assert _run(dsn, store, AT + timedelta(minutes=3))
    assert _run(dsn, store, AT + timedelta(minutes=3))
    with psycopg.connect(dsn) as conn:
        runs = conn.execute("SELECT time,rows_written FROM collector_runs ORDER BY time").fetchall()
        observations = conn.execute(
            "SELECT time,checkpoint_id,wait_time_seconds,vehicles_in_queue "
            "FROM observations ORDER BY time"
        ).fetchall()
    assert runs == [(AT, 1), (AT + timedelta(minutes=1), 1)]
    assert observations == [(AT, 7, 60, 3), (AT + timedelta(minutes=1), 7, 60, 3)]
    assert store.status().pending_count == 0


def test_commit_before_ack_is_idempotent(database, tmp_path, monkeypatch):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    seq = store.begin(AT)
    store.finish(seq, _result(), 1)
    real_ack = store.ack
    monkeypatch.setattr(store, "ack", lambda _: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError, match="crash"):
        _run(database("collector"), store, AT + timedelta(minutes=3))
    monkeypatch.setattr(store, "ack", real_ack)
    assert _run(database("collector"), store, AT + timedelta(minutes=3))
    with psycopg.connect(database("collector")) as conn:
        assert conn.execute("SELECT count(*) FROM collector_runs").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 1


def test_time_collision_retains_pending(database, tmp_path):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    seq = store.begin(AT)
    store.finish(seq, FetchResult(None, 429, 4, None, "HTTP 429"), 1)
    with psycopg.connect(database("collector")) as conn:
        conn.execute(
            "INSERT INTO collector_runs(time,http_status,duration_ms,rows_written,error) "
            "VALUES (%s,500,4,0,'HTTP 500')", (AT,)
        )
    with pytest.raises(ReplayConflict):
        _run(database("collector"), store, AT + timedelta(minutes=3))
    assert store.next_pending().seq == seq
