"""Replay against disposable TimescaleDB under the collector role."""

import asyncio
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from avelren import collector
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


def test_time_collision_does_not_mutate_observations(database, tmp_path):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    seq = store.begin(AT)
    store.finish(seq, _result(), 1)
    dsn = database("collector")
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO collector_runs(time,http_status,duration_ms,rows_written,error) "
            "VALUES (%s,429,4,0,'HTTP 429')", (AT,)
        )
    with pytest.raises(ReplayConflict):
        _run(dsn, store, AT + timedelta(minutes=3))
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM checkpoints").fetchone()[0] == 0
        assert conn.execute("SELECT http_status FROM collector_runs").fetchone()[0] == 429
    assert store.next_pending().seq == seq


def test_spool_outage_restart_and_replay(database, tmp_path):
    path = tmp_path / "cycles.sqlite3"
    # A separate process captures five synthetic cycles without opening PostgreSQL.
    subprocess.run(
        [sys.executable, "-c", """
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
from avelren.collector_spool import SpoolStore
from avelren.echerha import FetchResult
from avelren.models import WorkloadResponse
store = SpoolStore(Path(sys.argv[1]))
for minute in range(5):
    at = datetime(2026, 10, 1, 12, 0, tzinfo=UTC) + timedelta(minutes=minute)
    response = WorkloadResponse.model_validate({
        'filters': {'countries': [{'id': 1, 'name': 'Poland'}]},
        'data': [{'id': 7, 'title': 'Truck', 'country_id': 1,
                  'for_vehicle_type': 1, 'wait_time': minute * 60,
                  'vehicle_in_active_queues_counts': minute}],
    })
    seq = store.begin(at)
    store.finish(seq, FetchResult(response, 200, 9, 'a' * 64, None), 1)
store.close()
""", str(path)],
        check=True,
    )
    store = SpoolStore(path)
    assert store.status().pending_count == 5
    for _ in range(5):
        assert _run(database("collector"), store, AT + timedelta(minutes=10))
    with psycopg.connect(database("collector")) as conn:
        rows = conn.execute(
            "SELECT time,wait_time_seconds,vehicles_in_queue FROM observations ORDER BY time"
        ).fetchall()
        derived = conn.execute(
            "SELECT derived_error FROM collector_runs ORDER BY time"
        ).fetchall()
    assert rows == [
        (AT + timedelta(minutes=minute), minute * 60, minute) for minute in range(5)
    ]
    assert all("delayed_replay" in row[0] for row in derived)
    assert store.status().pending_count == 0


def test_producer_continues_while_writer_database_unavailable(database, tmp_path, monkeypatch):
    """One fake upstream request per explicit cycle while writer fails independently."""
    from unittest.mock import AsyncMock

    store = SpoolStore(tmp_path / "cycles.sqlite3")
    fetch = AsyncMock(return_value=_result())
    monkeypatch.setattr(collector, "fetch_workload", fetch)

    class Clock:
        at = datetime.now(UTC) - timedelta(minutes=10)

        @classmethod
        def now(cls, tz):
            value = cls.at
            cls.at += timedelta(minutes=1)
            return value

    monkeypatch.setattr(collector, "datetime", Clock)

    class UnavailablePool:
        async def open(self, **kwargs):
            raise RuntimeError("DB unavailable")

        async def close(self):
            pass

    monkeypatch.setattr(collector, "_new_writer_pool", UnavailablePool)

    async def capture():
        stop = asyncio.Event()
        writer = asyncio.create_task(collector.writer_supervisor(store, stop))
        await asyncio.sleep(0)
        for _ in range(5):
            await collector.run_cycle(object(), store)
        stop.set()
        await writer

    asyncio.run(capture())
    assert fetch.await_count == 5
    assert store.status().pending_count == 5
    store.close()
    restored = SpoolStore(tmp_path / "cycles.sqlite3")
    for _ in range(5):
        assert _run(database("collector"), restored, datetime.now(UTC) + timedelta(minutes=3))
    with psycopg.connect(database("collector")) as conn:
        assert conn.execute("SELECT count(*) FROM collector_runs").fetchone()[0] == 5
        assert conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 5
    assert restored.status().pending_count == 0


def test_safe_dns_diagnostic_replays_to_primary(database, tmp_path):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    reason = "ConnectError: reason=dns errno=-2"
    store.finish(store.begin(AT), FetchResult(None, None, 4125, None, reason), 1)
    assert _run(database("collector"), store, AT + timedelta(minutes=1))
    with psycopg.connect(database("collector")) as c:
        assert c.execute(
            "SELECT error,duration_ms,http_status,rows_written FROM collector_runs"
        ).fetchone() == (reason, 4125, None, 0)
    assert store.status().pending_count == 0
    store.close()
