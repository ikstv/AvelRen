"""Дослідний replay проти робочих транзакцій на disposable БД."""

import asyncio
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row

from avelren import notifier, surge_api, surge_delivery, surge_store
from avelren.config import settings

T = datetime(2026, 10, 2, 10, tzinfo=UTC)


def test_replay_matches_database_transitions(database, conn):
    from tools.surge_experiment.contracts import ObservationRow
    from tools.surge_experiment.events import HistoryIndex
    from tools.surge_experiment.frozen import FrozenCandidate
    from tools.surge_experiment.replay import ReplayEngine

    conn.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(17,'synthetic',1)")
    rows = [ObservationRow(17, T + timedelta(minutes=i), 0, False) for i in range(-239, 1)]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO observations(time,checkpoint_id,vehicles_in_queue,is_paused,"
            "wait_time_seconds) VALUES(%s,17,%s,false,0)",
            [(r.time, r.count) for r in rows],
        )
    engine = ReplayEngine(17, FrozenCandidate(), T)

    async def cycle(now):
        async with await psycopg.AsyncConnection.connect(
            database("admin"), autocommit=True, options="-c role=avelren_surge"
        ) as connection:
            await surge_store.process_checkpoint(connection, 17, now)

    for minute, count in ((0, None), (1, 0), (2, 25), (7, None)):
        now = T + timedelta(minutes=minute)
        if count is not None:
            rows.append(ObservationRow(17, now, count, False))
            conn.execute(
                "INSERT INTO observations(time,checkpoint_id,vehicles_in_queue,is_paused,"
                "wait_time_seconds) VALUES(%s,17,%s,false,0)",
                (now, count),
            )
        asyncio.run(cycle(now))
        engine.step(HistoryIndex(rows), now, 0)
        stored = conn.execute(
            "SELECT * FROM surge_checkpoint_state WHERE checkpoint_id=17"
        ).fetchone()
        assert stored["last_forecast_hour"] == engine.last_hour
        assert stored["last_observation_at"] == engine.state.last_observation_at
        assert stored["forecast_armed"] == engine.state.forecast_armed
        active = conn.execute(
            "SELECT kind,started_at,updated_at,expires_at FROM surge_events WHERE closed_at IS NULL"
        ).fetchall()
        expected = [
            (kind, ep.started_at, ep.updated_at, ep.expires_at)
            for kind, ep in (
                ("surge_forecast", engine.state.forecast),
                ("surge_started", engine.state.fact),
            )
            if ep is not None
        ]
        assert sorted(tuple(r.values()) for r in active) == sorted(expected)
    scores = conn.execute("SELECT score FROM surge_predictions ORDER BY issued_at").fetchall()
    assert [r["score"] for r in scores] == [
        r["score"] for r in engine.decisions if r["prediction_attempt"]
    ]
    closed = conn.execute(
        "SELECT kind,closed_at,close_reason FROM surge_events ORDER BY id"
    ).fetchall()
    assert [(r["kind"], r["closed_at"], r["close_reason"]) for r in closed] == [
        (r["kind"], r["closed_at"], r["close_reason"]) for r in engine.alerts
    ]


def setup_alerts(conn, device, api_client, monkeypatch, queues=(17,)):
    monkeypatch.setattr(settings, "surge_enabled", True)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return T

    monkeypatch.setattr(surge_api, "datetime", Clock)
    conn.execute(
        "UPDATE devices SET notification_capabilities=ARRAY['surge_v1'] WHERE id=%s",
        (device.device_id,),
    )
    ids = {}
    for queue in queues:
        conn.execute(
            "INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(%s,'synthetic',1)", (queue,)
        )
        conn.execute(
            "INSERT INTO surge_events(checkpoint_id,kind,started_at,updated_at,expires_at) "
            "VALUES(%s,'surge_started',%s,%s,%s)",
            (queue, T, T, T + timedelta(minutes=30)),
        )
        assert (
            api_client.put(
                f"/surge-subscriptions/{queue}",
                headers=device.headers(),
                json={"forecast_enabled": False, "fact_enabled": True},
            ).status_code
            == 200
        )
        ids[queue] = conn.execute(
            "SELECT a.id FROM surge_alerts a JOIN surge_events e ON e.id=a.event_id "
            "WHERE e.checkpoint_id=%s",
            (queue,),
        ).fetchone()["id"]
    return ids


def simulator(ids):
    from tools.surge_experiment.delivery import DeliveryReplay

    result = DeliveryReplay()
    for queue, key in ids.items():
        result.attach(
            {
                "queue_id": queue,
                "alert_id": str(key),
                "kind": "surge_started",
                "alert_created_at": T,
                "expires_at": T + timedelta(minutes=30),
                "closed_at": None,
            }
        )
    return result


def reserve(database, key, now):
    async def call():
        async with await psycopg.AsyncConnection.connect(
            database("notifier"), autocommit=True
        ) as connection:
            return await surge_delivery.reserve_attempt(connection, key, now)

    return asyncio.run(call())


def accept(database, attempt, now):
    async def call():
        async with await psycopg.AsyncConnection.connect(
            database("notifier"), autocommit=True
        ) as connection:
            await surge_delivery.accept_attempt(connection, attempt, now)

    asyncio.run(call())


def test_unknown_transport_retry_same_attempt(database, conn, device, api_client, monkeypatch):
    ids = setup_alerts(conn, device, api_client, monkeypatch)
    sim, key = simulator(ids), ids[17]
    actual_first = reserve(database, key, T)
    virtual_first = sim.reserve(str(key), T)
    assert (
        reserve(database, key, T + timedelta(seconds=59))
        is sim.reserve(str(key), T + timedelta(seconds=59))
        is None
    )
    actual_retry = reserve(database, key, T + timedelta(seconds=60))
    virtual_retry = sim.reserve(str(key), T + timedelta(seconds=60))
    assert actual_first["attempt_id"] == actual_retry["attempt_id"]
    assert virtual_first["attempt_id"] == virtual_retry["attempt_id"]
    assert actual_retry["attempt_count"] == virtual_retry["attempt_count"] == 2
    accept(database, actual_retry, T + timedelta(seconds=60))
    sim.accept(virtual_retry["attempt_id"], T + timedelta(seconds=60))
    assert (
        reserve(database, key, T + timedelta(seconds=359))
        is sim.reserve(str(key), T + timedelta(seconds=359))
        is None
    )
    actual_next = reserve(database, key, T + timedelta(seconds=360))
    virtual_next = sim.reserve(str(key), T + timedelta(seconds=360))
    assert actual_next["ordinal"] == virtual_next["ordinal"] == 2


def test_resubscribe_preserves_ack(database, conn, device, api_client, monkeypatch):
    ids = setup_alerts(conn, device, api_client, monkeypatch)
    sim, key = simulator(ids), ids[17]
    for _ in range(2):
        assert (
            api_client.post(f"/surge-alerts/{key}/ack", headers=device.headers()).status_code == 200
        )
        sim.acknowledge(str(key))
    assert api_client.delete("/surge-subscriptions/17", headers=device.headers()).status_code == 200
    sim.unsubscribe(17)
    assert (
        api_client.put(
            "/surge-subscriptions/17",
            headers=device.headers(),
            json={"forecast_enabled": False, "fact_enabled": True},
        ).status_code
        == 200
    )
    assert (
        conn.execute("SELECT count(*) n FROM surge_alerts").fetchone()["n"] == len(sim.alerts) == 1
    )
    assert (
        conn.execute("SELECT status FROM surge_alerts").fetchone()["status"]
        == sim.alerts[str(key)]["status"]
        == "acknowledged"
    )
    assert reserve(database, key, T) is sim.reserve(str(key), T) is None


def test_five_queues_cancel_isolated(database, conn, device, api_client, monkeypatch):
    from avelren import fcm

    ids = setup_alerts(conn, device, api_client, monkeypatch, queues=(1, 6, 17, 29, 14))
    sim, key = simulator(ids), ids[17]
    assert api_client.post(f"/surge-alerts/{key}/ack", headers=device.headers()).status_code == 200
    sim.acknowledge(str(key))
    messages = []

    async def fake_send(client, token, payload, **kwargs):
        assert token.startswith("synthetic-")
        messages.append(payload)

    monkeypatch.setattr(fcm, "send", fake_send)

    async def cancels():
        async with await psycopg.AsyncConnection.connect(
            database("notifier"), row_factory=dict_row
        ) as connection:
            await notifier._send_cancels(object(), connection)

    asyncio.run(cancels())
    assert [m["cancel_surge_alert_id"] for m in messages] == sim.drain_cancels() == [str(key)]
    for queue, value in ids.items():
        assert (
            (reserve(database, value, T) is None)
            == (sim.reserve(str(value), T) is None)
            == (queue == 17)
        )
