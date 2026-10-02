"""Два однакові вимірювання, помилка джерела та доставка через тестовий FCM."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from avelren import collector, fcm, notifier
from avelren.collector_replay import replay_once
from avelren.collector_spool import SpoolStore
from avelren.models import WorkloadItem, WorkloadResponse
from avelren.schema_gate import assert_schema_at_least


def test_missing_wait_pipeline_keeps_count_and_run(database, monkeypatch, tmp_path):
    item = WorkloadItem(
        id=900000002,
        title="Оцінка відсутня",
        for_vehicle_type=1,
        vehicle_in_active_queues_counts=80,
    )
    monkeypatch.setattr(
        collector,
        "fetch_workload",
        AsyncMock(
            return_value=SimpleNamespace(
                error=None,
                http_status=200,
                duration_ms=10,
                body_sha256="missing-fixture",
                response=WorkloadResponse(data=[item]),
            )
        ),
    )

    store = SpoolStore(tmp_path / "missing.sqlite3")

    async def run():
        async with AsyncConnectionPool(
            database("collector"), open=False, kwargs={"row_factory": dict_row}
        ) as pool:
            await assert_schema_at_least(pool)
            await collector.run_cycle(object(), store)
            cycle = store.next_pending()
            assert await replay_once(store, pool, cycle.at)

    asyncio.run(run())
    store.close()
    with psycopg.connect(database("admin")) as conn:
        assert conn.execute(
            "SELECT vehicles_in_queue,wait_time_seconds,wait_time_status FROM observations"
        ).fetchall() == [(80, 0, "missing")]
        assert conn.execute("SELECT rows_written,error FROM collector_runs").fetchall() == [
            (1, None)
        ]
        processed, error = conn.execute(
            "SELECT derived_processed_at,derived_error FROM collector_runs"
        ).fetchone()
        assert processed is not None
        assert error is None


def test_observations_and_notification_under_service_roles(database, monkeypatch, tmp_path):
    instant = datetime.now(UTC).replace(microsecond=0)

    class Clock:
        @staticmethod
        def now(tz):
            return instant

    item = WorkloadItem(
        id=900000001,
        title="Тестова черга",
        for_vehicle_type=1,
        wait_time=3600,
        vehicle_in_active_queues_counts=80,
    )
    result = SimpleNamespace(
        error=None,
        http_status=200,
        duration_ms=10,
        body_sha256="fixture",
        response=WorkloadResponse(data=[item]),
    )
    fetch = AsyncMock(return_value=result)
    send = AsyncMock()
    monkeypatch.setattr(collector, "datetime", Clock)
    monkeypatch.setattr(collector, "fetch_workload", fetch)
    monkeypatch.setattr(fcm, "send", send)
    store = SpoolStore(tmp_path / "cycles.sqlite3")

    async def run():
        nonlocal instant
        async with AsyncConnectionPool(
            database("collector"), open=False, kwargs={"row_factory": dict_row}
        ) as pool:
            await assert_schema_at_least(pool)
            await collector.run_cycle(object(), store)
            assert await replay_once(store, pool, instant)
            with psycopg.connect(database("admin")) as admin:
                device = admin.execute(
                    "INSERT INTO devices(fcm_token,secret_hash) "
                    "VALUES ('synthetic-token','test') RETURNING id"
                ).fetchone()[0]
                admin.execute(
                    "INSERT INTO subscriptions(device_id,checkpoint_id,threshold) "
                    "VALUES (%s,%s,50)",
                    (device, item.id),
                )
            instant += timedelta(seconds=60)
            await collector.run_cycle(object(), store)
            assert await replay_once(store, pool, instant)
            instant += timedelta(seconds=60)
            fetch.return_value = SimpleNamespace(
                error="HTTP 500",
                http_status=500,
                duration_ms=10,
                body_sha256="fixture-error",
                response=None,
            )
            await collector.run_cycle(object(), store)
            assert await replay_once(store, pool, instant)
        async with AsyncConnectionPool(
            database("notifier"), open=False, kwargs={"row_factory": dict_row}
        ) as pool:
            monkeypatch.setattr(notifier, "get_pool", lambda: pool)
            await assert_schema_at_least(pool)
            assert await notifier.run_cycle(object()) == 1

    asyncio.run(run())
    store.close()
    assert fetch.await_count == 3
    send.assert_awaited_once()
    assert send.await_args.args[1] == "synthetic-token"
    with psycopg.connect(database("admin")) as conn:
        observations = conn.execute(
            "SELECT time,vehicles_in_queue FROM observations ORDER BY time"
        ).fetchall()
        assert len(observations) == 2
        assert observations[1][0] - observations[0][0] == timedelta(seconds=60)
        assert [r[1] for r in observations] == [80, 80]
        assert conn.execute(
            "SELECT rows_written,error FROM collector_runs ORDER BY time"
        ).fetchall() == [(1, None), (1, None), (0, "HTTP 500")]
        assert conn.execute("SELECT send_count FROM alerts").fetchall() == [(1,)]
