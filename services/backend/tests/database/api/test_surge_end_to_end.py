"""Синтетична історія → реальна модель/worker → FCM stub → API ACK/cancel.

Немає мережевих викликів. Нове підключення worker після кожного циклу
моделює втрату всього процесного стану, але збережену БД.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from avelren import fcm, notifier, surge_api, surge_delivery, surge_worker
from avelren.config import settings

T = datetime(2026, 10, 2, 10, tzinfo=UTC)


def test_frozen_model_to_fact_ack_and_cancel_after_restart(
    database, conn, device, api_client, monkeypatch
):
    monkeypatch.setattr(settings, "surge_enabled", True)
    clock = [T]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr(surge_api, "datetime", Clock)
    monkeypatch.setattr(surge_delivery, "utc_now", lambda: clock[0])
    conn.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(17,'Чоп',1)")
    conn.execute(
        "UPDATE devices SET notification_capabilities=ARRAY['surge_v1'] WHERE id=%s",
        (device.device_id,),
    )
    assert (
        api_client.put(
            "/surge-subscriptions/17",
            headers=device.headers(),
            json={"forecast_enabled": True, "fact_enabled": True},
        ).status_code
        == 200
    )
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO observations(time,checkpoint_id,wait_time_seconds,"
            "vehicles_in_queue,is_paused) "
            "VALUES(%s,17,0,0,false)",
            [(T - timedelta(minutes=240 - i),) for i in range(241)],
        )

    async def cycle():
        # Акаунт адміністратора потрібний лише для SET ROLE у disposable suite.
        # Фактичні SQL worker виконуються під тією ж обмеженою роллю production.
        async with AsyncConnectionPool(
            database("admin"), open=False, kwargs={"options": "-c role=avelren_surge"}
        ) as pool:
            monkeypatch.setattr(surge_worker, "get_pool", lambda **kw: pool)
            return await surge_worker.run_cycle(clock[0])

    assert asyncio.run(cycle()) == 1
    assert asyncio.run(cycle()) == 1
    prediction = conn.execute("SELECT score,model_version FROM surge_predictions").fetchall()
    assert len(prediction) == 1
    assert 0.889 < prediction[0]["score"] < 0.892
    assert prediction[0]["model_version"] == "surge_24h_v1"
    assert api_client.get("/surge/17").json()["status"] == "risk"
    forecast = conn.execute("SELECT id FROM surge_alerts").fetchone()["id"]

    messages = []

    async def synthetic_fcm(client, token, payload, **kw):
        assert token.startswith("synthetic-")
        if "attempt_id" in payload:
            # Спроба мусить існувати вже в окремому committed з'єднанні до HTTP.
            with psycopg.connect(database("admin")) as check:
                assert check.execute(
                    "SELECT 1 FROM surge_delivery_attempts WHERE attempt_id=%s",
                    (payload["attempt_id"],),
                ).fetchone() == (1,)
        messages.append(payload)

    monkeypatch.setattr(fcm, "send", synthetic_fcm)

    async def send():
        async with AsyncConnectionPool(database("notifier"), open=False) as pool:
            monkeypatch.setattr(surge_delivery, "get_pool", lambda **kw: pool)
            return await surge_delivery.send_due(object(), clock[0])

    assert asyncio.run(send()) == 1
    assert messages[-1]["type"] == "surge_forecast"
    assert messages[-1]["surge_alert_id"] == str(forecast)
    assert messages[-1]["body"] == "Можливий початок масової реєстрації на Чопі"
    first_attempt = messages[-1]["attempt_id"]
    assert asyncio.run(send()) == 0

    clock[0] += timedelta(minutes=1)
    conn.execute(
        "INSERT INTO observations(time,checkpoint_id,wait_time_seconds,"
        "vehicles_in_queue,is_paused) "
        "VALUES(%s,17,0,25,false)",
        (clock[0],),
    )
    assert asyncio.run(cycle()) == 1
    assert api_client.get("/surge/17").json()["status"] == "started"
    fact = conn.execute(
        "SELECT a.id FROM surge_alerts a JOIN surge_events e ON a.event_id=e.id "
        "WHERE e.kind='surge_started'"
    ).fetchone()["id"]
    assert (
        conn.execute("SELECT status FROM surge_alerts WHERE id=%s", (forecast,)).fetchone()[
            "status"
        ]
        == "expired"
    )
    assert asyncio.run(send()) == 1
    assert messages[-1]["body"] == "Почалось зростання черги на Чопі"
    assert messages[-1]["attempt_id"] != first_attempt
    assert api_client.post(f"/surge-alerts/{fact}/ack", headers=device.headers()).status_code == 200
    assert api_client.post(f"/surge-alerts/{fact}/ack", headers=device.headers()).status_code == 200

    async def send_cancels():
        async with await psycopg.AsyncConnection.connect(
            database("notifier"), row_factory=dict_row
        ) as c:
            await notifier._send_cancels(object(), c)

    asyncio.run(send_cancels())
    cancelled = {int(m["cancel_surge_alert_id"]) for m in messages if "cancel_surge_alert_id" in m}
    assert cancelled == {forecast, fact}
    assert (
        conn.execute(
            "SELECT count(*) n FROM notification_cancels WHERE accepted_at IS NULL"
        ).fetchone()["n"]
        == 0
    )
    clock[0] += timedelta(minutes=5)
    assert asyncio.run(cycle()) == 1
    assert asyncio.run(send()) == 0
    assert (
        conn.execute("SELECT status FROM surge_alerts WHERE id=%s", (fact,)).fetchone()["status"]
        == "acknowledged"
    )
