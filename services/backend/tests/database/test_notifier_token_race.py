"""FCM-відповідь для старого токена не знищує оновлений токен у PostgreSQL."""

import asyncio
import logging
from contextlib import asynccontextmanager

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from avelren import fcm, notifier
from avelren.config import settings

T1 = "synthetic-token-before-refresh"
T2 = "synthetic-token-after-refresh"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def seed(database, kind, phase, *, aged=False):
    with psycopg.connect(database("admin")) as conn:
        conn.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(17,'fixture',1)")
        device_id = conn.execute(
            "INSERT INTO devices(fcm_token,secret_hash) VALUES(%s,'fixture') RETURNING id",
            (T1,),
        ).fetchone()[0]
        if kind == "threshold":
            subscription_id = conn.execute(
                "INSERT INTO subscriptions(device_id,checkpoint_id,threshold) "
                "VALUES(%s,17,50) RETURNING id",
                (device_id,),
            ).fetchone()[0]
            alert_id = conn.execute(
                "INSERT INTO alerts(subscription_id,checkpoint_id,threshold,vehicles_at_trigger) "
                "VALUES(%s,17,50,80) RETURNING id",
                (subscription_id,),
            ).fetchone()[0]
        else:
            target_id = conn.execute(
                "INSERT INTO eta_targets(device_id,checkpoint_id,target_at) "
                "VALUES(%s,17,now()+INTERVAL '1 hour') RETURNING id",
                (device_id,),
            ).fetchone()[0]
            alert_id = conn.execute(
                "INSERT INTO eta_alerts(target_id,checkpoint_id,eta_at_trigger,"
                "wait_seconds_at_trigger) VALUES(%s,17,now()+INTERVAL '1 hour',3600) RETURNING id",
                (target_id,),
            ).fetchone()[0]
        cancel_id = None
        if phase == "cancel":
            table = "alerts" if kind == "threshold" else "eta_alerts"
            conn.execute(
                f"UPDATE {table} SET status='expired',expired_at=now() WHERE id=%s", (alert_id,)
            )
            age = "2 hours" if aged else "0 seconds"
            cancel_id = conn.execute(
                "INSERT INTO notification_cancels(kind,alert_id,device_id,created_at) "
                "VALUES(%s,%s,%s,now()-%s::interval) RETURNING id",
                (kind, alert_id, device_id, age),
            ).fetchone()[0]
    return device_id, alert_id, cancel_id


@asynccontextmanager
async def sender_pool(database, monkeypatch):
    # Surge має власні тести; тут виконується справжній legacy run_cycle.
    monkeypatch.setattr(settings, "surge_enabled", False)
    async with AsyncConnectionPool(
        database("notifier"), open=False, kwargs={"row_factory": dict_row}
    ) as pool:
        monkeypatch.setattr(notifier, "get_pool", lambda: pool)
        yield


def failure(code="UNREGISTERED"):
    dead = code == "UNREGISTERED"
    return fcm.FcmError(
        http_status=404 if dead else 400,
        canonical_status="NOT_FOUND" if dead else "INVALID_ARGUMENT",
        fcm_error_code=code,
        message="synthetic FCM failure",
        dead_token=dead,
        retryable=False,
    )


def state(database, kind, device_id, alert_id, cancel_id):
    table = "alerts" if kind == "threshold" else "eta_alerts"
    with psycopg.connect(database("admin"), row_factory=dict_row) as conn:
        token = conn.execute("SELECT fcm_token FROM devices WHERE id=%s", (device_id,)).fetchone()[
            "fcm_token"
        ]
        alert = conn.execute(
            f"SELECT status,send_count,last_sent_at FROM {table} WHERE id=%s", (alert_id,)
        ).fetchone()
        cancel = (
            None
            if cancel_id is None
            else conn.execute(
                "SELECT attempt_count,last_attempt_at,accepted_at,abandoned_at "
                "FROM notification_cancels WHERE id=%s",
                (cancel_id,),
            ).fetchone()
        )
    return token, alert, cancel


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["threshold", "eta"])
async def test_notifier_token_race_normal_preserves_committed_refresh(
    database, monkeypatch, kind, caplog
):
    caplog.set_level(logging.INFO, logger="avelren.notifier")
    device_id, alert_id, cancel_id = seed(database, kind, "normal")
    started, release = asyncio.Event(), asyncio.Event()
    sent_tokens = []

    async def blocked_send(client, token, payload, **kwargs):
        sent_tokens.append(token)
        assert token == T1
        assert kwargs["collapse_key"] == f"{kind}:{alert_id}"
        started.set()
        await release.wait()
        raise failure()

    monkeypatch.setattr(fcm, "send", blocked_send)
    async with sender_pool(database, monkeypatch):
        async with asyncio.TaskGroup() as tasks:
            cycle = tasks.create_task(notifier.run_cycle(object()))
            await asyncio.wait_for(started.wait(), timeout=10)
            async with await psycopg.AsyncConnection.connect(database("api")) as api:
                await api.execute("UPDATE devices SET fcm_token=%s WHERE id=%s", (T2, device_id))
            # Друге підключення вже COMMIT T2, FCM ще очікує.
            assert state(database, kind, device_id, alert_id, cancel_id)[0] == T2
            release.set()
        assert cycle.result() == 0

    token, alert, _ = state(database, kind, device_id, alert_id, cancel_id)
    assert token == T2
    assert alert == {"status": "pending", "send_count": 0, "last_sent_at": None}
    assert sent_tokens == [T1]
    assert T1 not in caplog.text and T2 not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["threshold", "eta"])
@pytest.mark.parametrize("aged", [False, True], ids=["retry", "age-limit"])
async def test_notifier_token_race_cancel_uses_bounded_retry_after_refresh(
    database, monkeypatch, kind, aged, caplog
):
    caplog.set_level(logging.INFO, logger="avelren.notifier")
    device_id, alert_id, cancel_id = seed(database, kind, "cancel", aged=aged)
    started, release = asyncio.Event(), asyncio.Event()
    sent_tokens = []

    async def blocked_send(client, token, payload, **kwargs):
        sent_tokens.append(token)
        assert kwargs["collapse_key"] == f"{kind}:{alert_id}"
        if len(sent_tokens) == 1:
            assert token == T1
            started.set()
            await release.wait()
            raise failure()
        assert token == T2

    monkeypatch.setattr(fcm, "send", blocked_send)
    async with sender_pool(database, monkeypatch):
        async with asyncio.TaskGroup() as tasks:
            cycle = tasks.create_task(notifier.run_cycle(object()))
            await asyncio.wait_for(started.wait(), timeout=10)
            async with await psycopg.AsyncConnection.connect(database("api")) as api:
                await api.execute("UPDATE devices SET fcm_token=%s WHERE id=%s", (T2, device_id))
            assert state(database, kind, device_id, alert_id, cancel_id)[0] == T2
            release.set()
        assert cycle.result() == 0

        token, alert, cancel = state(database, kind, device_id, alert_id, cancel_id)
        assert token == T2
        assert alert == {"status": "expired", "send_count": 0, "last_sent_at": None}
        assert cancel["attempt_count"] == 1
        assert cancel["last_attempt_at"] is not None
        assert cancel["accepted_at"] is None
        assert (cancel["abandoned_at"] is not None) == aged
        assert sent_tokens == [T1]  # T2 буде використано тільки в наступному циклі.
        assert await notifier.run_cycle(object()) == 0

    token, _, cancel = state(database, kind, device_id, alert_id, cancel_id)
    assert token == T2
    assert cancel["attempt_count"] == 1
    assert (cancel["accepted_at"] is not None) == (not aged)
    assert sent_tokens == ([T1] if aged else [T1, T2])
    assert T1 not in caplog.text and T2 not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["threshold", "eta"])
@pytest.mark.parametrize("phase", ["normal", "cancel"])
async def test_notifier_token_race_current_dead_token_is_cleared(
    database, monkeypatch, kind, phase
):
    device_id, alert_id, cancel_id = seed(database, kind, phase)

    async def dead_send(client, token, payload, **kwargs):
        assert token == T1
        raise failure()

    monkeypatch.setattr(fcm, "send", dead_send)
    async with sender_pool(database, monkeypatch):
        assert await notifier.run_cycle(object()) == 0
    token, alert, cancel = state(database, kind, device_id, alert_id, cancel_id)
    assert token is None
    assert alert["send_count"] == 0 and alert["last_sent_at"] is None
    assert alert["status"] == ("pending" if phase == "normal" else "expired")
    if phase == "cancel":
        assert cancel["attempt_count"] == 0
        assert cancel["last_attempt_at"] is not None
        assert cancel["abandoned_at"] is not None
        assert cancel["accepted_at"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["threshold", "eta"])
@pytest.mark.parametrize("phase", ["normal", "cancel"])
async def test_notifier_token_race_non_dead_failure_preserves_token_and_lifecycle(
    database, monkeypatch, kind, phase
):
    device_id, alert_id, cancel_id = seed(database, kind, phase)

    async def invalid_send(client, token, payload, **kwargs):
        assert token == T1
        raise failure("INVALID_ARGUMENT")

    monkeypatch.setattr(fcm, "send", invalid_send)
    async with sender_pool(database, monkeypatch):
        assert await notifier.run_cycle(object()) == 0
    token, alert, cancel = state(database, kind, device_id, alert_id, cancel_id)
    assert token == T1
    assert alert["send_count"] == 0 and alert["last_sent_at"] is None
    assert alert["status"] == ("pending" if phase == "normal" else "expired")
    if phase == "cancel":
        assert cancel["attempt_count"] == 1
        assert cancel["last_attempt_at"] is not None
        assert cancel["abandoned_at"] is None and cancel["accepted_at"] is None
