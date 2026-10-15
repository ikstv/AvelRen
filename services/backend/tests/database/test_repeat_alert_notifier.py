"""Повтор legacy-alert після OK відбувається лише після успішної доставки."""

import asyncio
from contextlib import asynccontextmanager

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from avelren import cancels, fcm, notifier
from avelren.config import settings


def _seed_acknowledged_alert(database, kind):
    with psycopg.connect(database("admin"), row_factory=dict_row) as conn:
        conn.execute(
            "INSERT INTO checkpoints(id, title, for_vehicle_type) VALUES(17, 'fixture', 1)"
        )
        device_id = conn.execute(
            "INSERT INTO devices(fcm_token, secret_hash) "
            "VALUES('repeat-token', 'fixture') RETURNING id"
        ).fetchone()["id"]
        if kind == "threshold":
            parent_id = conn.execute(
                "INSERT INTO subscriptions(device_id, checkpoint_id, threshold) "
                "VALUES(%s, 17, 50) RETURNING id",
                (device_id,),
            ).fetchone()["id"]
            alert_id = conn.execute(
                "INSERT INTO alerts(subscription_id, checkpoint_id, threshold, "
                "vehicles_at_trigger, "
                "acknowledged_at, last_sent_at, send_count) "
                "VALUES(%s, 17, 50, 80, now(), now() - interval '10 minutes', 1) RETURNING id",
                (parent_id,),
            ).fetchone()["id"]
        else:
            parent_id = conn.execute(
                "INSERT INTO eta_targets(device_id, checkpoint_id, target_at) "
                "VALUES(%s, 17, now() + interval '1 hour') RETURNING id",
                (device_id,),
            ).fetchone()["id"]
            alert_id = conn.execute(
                "INSERT INTO eta_alerts(target_id, checkpoint_id, eta_at_trigger, "
                "wait_seconds_at_trigger, acknowledged_at, last_sent_at, send_count) "
                "VALUES(%s, 17, now() + interval '1 hour', 3600, now(), "
                "now() - interval '10 minutes', 1) RETURNING id",
                (parent_id,),
            ).fetchone()["id"]
    return device_id, alert_id


@asynccontextmanager
async def _sender_pool(database, monkeypatch):
    monkeypatch.setattr(settings, "surge_enabled", False)
    async with AsyncConnectionPool(
        database("notifier"), open=False, kwargs={"row_factory": dict_row}
    ) as pool:
        monkeypatch.setattr(notifier, "get_pool", lambda: pool)
        yield


async def _active_ids(database, device_id, kind):
    async with await psycopg.AsyncConnection.connect(database("api"), row_factory=dict_row) as conn:
        return (await cancels.active_alert_keys(conn, device_id))[kind]


def _alert_state(database, kind, alert_id):
    table = "alerts" if kind == "threshold" else "eta_alerts"
    with psycopg.connect(database("admin"), row_factory=dict_row) as conn:
        return conn.execute(
            f"SELECT acknowledged_at, last_sent_at, send_count FROM {table} "
            "WHERE id=%s",
            (alert_id,),
        ).fetchone()


@pytest.mark.parametrize("kind", ["threshold", "eta"])
def test_successful_resend_reactivates_same_acknowledged_alert(database, monkeypatch, kind):
    device_id, alert_id = _seed_acknowledged_alert(database, kind)
    sent = []

    async def delivered(_client, token, payload, **kwargs):
        sent.append((token, payload, kwargs))

    monkeypatch.setattr(fcm, "send", delivered)

    async def run():
        async with _sender_pool(database, monkeypatch):
            assert await notifier.run_cycle(object()) == 1

    asyncio.run(run())

    state = _alert_state(database, kind, alert_id)
    assert state["send_count"] == 2
    assert state["last_sent_at"] > state["acknowledged_at"]
    assert asyncio.run(_active_ids(database, device_id, kind)) == [alert_id]
    assert sent[0][0] == "repeat-token"
    assert sent[0][2]["collapse_key"] == f"{kind}:{alert_id}"
    assert sent[0][2]["ttl_seconds"] == settings.alert_resend_seconds + 60


@pytest.mark.parametrize("kind", ["threshold", "eta"])
def test_ack_during_send_does_not_hide_later_successful_resend(database, monkeypatch, kind):
    device_id, alert_id = _seed_acknowledged_alert(database, kind)
    table = "alerts" if kind == "threshold" else "eta_alerts"

    async def delivered(_client, _token, _payload, **_kwargs):
        # The notifier transaction has already started. Commit an independent
        # ACK before FCM accepts the next delivery, without sleeps or wall-clock
        # mocking: this deterministically orders transaction start < ACK < send.
        async with await psycopg.AsyncConnection.connect(database("api")) as conn:
            await conn.execute(
                f"UPDATE {table} SET acknowledged_at = clock_timestamp() WHERE id=%s",
                (alert_id,),
            )

    monkeypatch.setattr(fcm, "send", delivered)

    async def run():
        async with _sender_pool(database, monkeypatch):
            assert await notifier.run_cycle(object()) == 1

    asyncio.run(run())

    state = _alert_state(database, kind, alert_id)
    assert state["send_count"] == 2
    assert state["last_sent_at"] > state["acknowledged_at"]
    assert asyncio.run(_active_ids(database, device_id, kind)) == [alert_id]


@pytest.mark.parametrize("kind", ["threshold", "eta"])
def test_failed_resend_keeps_acknowledged_alert_hidden(database, monkeypatch, kind):
    device_id, alert_id = _seed_acknowledged_alert(database, kind)

    async def unavailable(*_args, **_kwargs):
        raise fcm.FcmError(
            http_status=503,
            canonical_status="UNAVAILABLE",
            fcm_error_code="UNAVAILABLE",
            message="synthetic outage",
            dead_token=False,
            retryable=True,
        )

    monkeypatch.setattr(fcm, "send", unavailable)

    async def run():
        async with _sender_pool(database, monkeypatch):
            assert await notifier.run_cycle(object()) == 0

    asyncio.run(run())

    state = _alert_state(database, kind, alert_id)
    assert state["send_count"] == 1
    assert state["last_sent_at"] < state["acknowledged_at"]
    assert asyncio.run(_active_ids(database, device_id, kind)) == []
