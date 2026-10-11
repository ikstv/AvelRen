"""Реальні транзакції, повтор worker, cancel та capability."""

import asyncio
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from avelren import surge_store
from avelren.surge_model import SurgePrediction

T = datetime(2026, 10, 2, 10, tzinfo=UTC)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def prepare(database, capabilities=True, growth=False):
    with psycopg.connect(database("admin")) as c:
        c.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(17,'fixture',1)")
        device = c.execute(
            "INSERT INTO devices(notification_capabilities) VALUES(%s) RETURNING id",
            (["surge_v1"] if capabilities else [],),
        ).fetchone()[0]
        c.execute(
            "INSERT INTO surge_subscriptions(device_id,checkpoint_id) VALUES(%s,17)", (device,)
        )
        with c.cursor() as cur:
            cur.executemany(
                (
                    "INSERT INTO "
                    "observations(time,checkpoint_id,wait_time_seconds,"
                    "vehicles_in_queue,is_paused) "
                    "VALUES(%s,17,0,%s,false)"
                ),
                [
                    (T - timedelta(minutes=240 - i), 130 if growth and i == 240 else 100)
                    for i in range(241)
                ],
            )
    return device


def positive(cp, observations, issued):
    return SurgePrediction(
        issued, issued + timedelta(hours=1), issued + timedelta(hours=24), 0.99, None
    )


async def process(database, now):
    async with await psycopg.AsyncConnection.connect(database("admin"), autocommit=True) as c:
        await c.execute("SET ROLE avelren_surge")
        await surge_store.process_checkpoint(c, 17, now)


@pytest.mark.anyio
async def test_failed_prediction_recovers_same_hour_without_duplicate(database, monkeypatch):
    prepare(database)

    def recovering(cp, observations, issued):
        if issued == T:
            return SurgePrediction(
                issued,
                issued + timedelta(hours=1),
                issued + timedelta(hours=24),
                None,
                "insufficient_history",
            )
        return positive(cp, observations, issued)

    monkeypatch.setattr(surge_store, "predict_surge", recovering)
    await process(database, T)
    await process(database, T)  # No fresh measurement, no retry.
    with psycopg.connect(database("admin")) as c:
        assert c.execute("SELECT count(*) FROM surge_predictions").fetchone()[0] == 1
        assert c.execute("SELECT last_forecast_hour FROM surge_checkpoint_state").fetchone()[0] == T
        c.execute(
            "INSERT INTO observations(time,checkpoint_id,wait_time_seconds,"
            "vehicles_in_queue,is_paused) VALUES(%s,17,0,100,false)",
            (T + timedelta(minutes=1),),
        )
    await asyncio.gather(
        process(database, T + timedelta(minutes=1)), process(database, T + timedelta(minutes=1))
    )
    await process(database, T + timedelta(minutes=2))
    with psycopg.connect(database("admin")) as c:
        assert c.execute("SELECT count(*) FROM surge_predictions").fetchone()[0] == 2
        assert (
            c.execute(
                "SELECT score FROM surge_predictions ORDER BY issued_at DESC LIMIT 1"
            ).fetchone()[0]
            == 0.99
        )
        assert c.execute("SELECT count(*) FROM surge_events").fetchone()[0] == 1


@pytest.mark.anyio
async def test_repeated_and_concurrent_cycles_are_idempotent(database, monkeypatch):
    prepare(database)
    monkeypatch.setattr(surge_store, "predict_surge", positive)
    await asyncio.gather(process(database, T), process(database, T))
    await process(database, T)
    with psycopg.connect(database("admin")) as c:
        assert c.execute("SELECT count(*) FROM surge_predictions").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM surge_events").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM surge_alerts").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM surge_delivery_attempts").fetchone()[0] == 0
        assert c.execute("SELECT issued_at,window_end FROM surge_predictions").fetchone() == (
            T,
            T + timedelta(hours=24),
        )
        before = c.execute("SELECT count(*) FROM observations").fetchone()[0]
    await process(database, T + timedelta(minutes=4))
    with psycopg.connect(database("admin")) as c:
        assert c.execute("SELECT status FROM surge_alerts").fetchone() == ("expired",)
        assert c.execute("SELECT kind FROM notification_cancels").fetchone() == ("surge_forecast",)
        assert c.execute("SELECT count(*) FROM observations").fetchone()[0] == before


@pytest.mark.anyio
@pytest.mark.parametrize("capabilities", [False, True])
async def test_fact_suppresses_forecast_and_only_new_apk_receives_alert(
    database, monkeypatch, capabilities
):
    prepare(database, capabilities, growth=True)
    monkeypatch.setattr(surge_store, "predict_surge", positive)
    await process(database, T)
    with psycopg.connect(database("admin")) as c:
        assert c.execute("SELECT kind FROM surge_events").fetchall() == [("surge_started",)]
        assert c.execute("SELECT count(*) FROM surge_alerts").fetchone()[0] == int(capabilities)
        assert c.execute("SELECT count(*) FROM surge_predictions").fetchone()[0] == 1


@pytest.mark.anyio
async def test_disabled_monitor_closes_events_and_cancels_pending(database, monkeypatch):
    prepare(database)
    monkeypatch.setattr(surge_store, "predict_surge", positive)
    await process(database, T)
    async with await psycopg.AsyncConnection.connect(database("admin"), autocommit=True) as c:
        await c.execute("SET ROLE avelren_surge")
        await surge_store.disable_monitoring(c, T + timedelta(seconds=10))
        await surge_store.disable_monitoring(c, T + timedelta(seconds=20))
    with psycopg.connect(database("admin")) as c:
        assert c.execute("SELECT close_reason FROM surge_events").fetchone() == ("disabled",)
        assert c.execute("SELECT status FROM surge_alerts").fetchone() == ("expired",)
        assert c.execute("SELECT count(*) FROM notification_cancels").fetchone()[0] == 1


@pytest.mark.anyio
async def test_hourly_positive_preserves_ack_and_late_subscription_joins(database, monkeypatch):
    first = prepare(database)
    monkeypatch.setattr(surge_store, "predict_surge", positive)
    await process(database, T)
    with psycopg.connect(database("admin")) as c:
        c.execute(
            "UPDATE surge_alerts SET status='acknowledged',acknowledged_at=%s WHERE device_id=%s",
            (T, first),
        )
        second = c.execute(
            "INSERT INTO devices(notification_capabilities) VALUES(ARRAY['surge_v1']) RETURNING id"
        ).fetchone()[0]
        c.execute(
            "INSERT INTO surge_subscriptions(device_id,checkpoint_id) VALUES(%s,17)", (second,)
        )
        with c.cursor() as cur:
            cur.executemany(
                (
                    "INSERT INTO observations(time,checkpoint_id,wait_time_seconds,"
                    "vehicles_in_queue,is_paused) VALUES(%s,17,0,100,false)"
                ),
                [(T + timedelta(minutes=i),) for i in range(1, 61)],
            )
    await process(database, T + timedelta(hours=1))
    with psycopg.connect(database("admin")) as c:
        assert c.execute("SELECT count(*) FROM surge_events").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM surge_predictions").fetchone()[0] == 2
        assert c.execute("SELECT started_at,expires_at FROM surge_events").fetchone() == (
            T,
            T + timedelta(minutes=125),
        )
        assert dict(c.execute("SELECT device_id,status FROM surge_alerts").fetchall()) == {
            first: "acknowledged",
            second: "pending",
        }
        c.execute("DELETE FROM surge_subscriptions WHERE device_id=%s", (second,))
    await process(database, T + timedelta(minutes=61))
    with psycopg.connect(database("admin")) as c:
        assert c.execute("SELECT device_id FROM notification_cancels").fetchall() == [(second,)]
        assert c.execute(
            "SELECT status FROM surge_alerts WHERE device_id=%s", (first,)
        ).fetchone() == ("acknowledged",)


@pytest.mark.anyio
async def test_reenable_active_episode_gets_new_alert_id_after_cancel(database, monkeypatch):
    device = prepare(database)
    monkeypatch.setattr(surge_store, "predict_surge", positive)
    await process(database, T)
    with psycopg.connect(database("admin")) as c:
        old = c.execute("SELECT id FROM surge_alerts").fetchone()[0]
        c.execute(
            "UPDATE surge_subscriptions SET forecast_enabled=false WHERE device_id=%s", (device,)
        )
    await process(database, T + timedelta(seconds=10))
    with psycopg.connect(database("admin")) as c:
        c.execute(
            "UPDATE surge_subscriptions SET forecast_enabled=true WHERE device_id=%s", (device,)
        )
    await process(database, T + timedelta(seconds=20))
    with psycopg.connect(database("admin")) as c:
        new, status = c.execute("SELECT id,status FROM surge_alerts").fetchone()
        assert new != old
        assert status == "pending"
        assert c.execute("SELECT alert_id FROM notification_cancels").fetchone() == (old,)
