"""Скасування показаних сповіщень і reconciliation (A-02).

Ключові інваріанти, які тут захищаємо:
  * перехід pending → expired/deleted завжди enqueue-ить cancel, НЕЗАЛЕЖНО від
    send_count (бо notifier робить fcm.send() до _mark_sent(), і є crash-window);
  * ACK не enqueue-ить cancel (телефон гасить локально);
  * /active-alerts віддає canonical pending-стан, окремо за kind;
  * threshold:N і eta:N — незалежні;
  * notifier шле cancel'и ПІСЛЯ normal pushes у тому ж циклі;
  * race normal↔expire↔cancel: протухлий normal не фіксується як успішний,
    cancel обробляється в тому ж циклі.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row

from avelren import alerts, cancels, eta, fcm, notifier
from avelren.models import WorkloadItem

DSN = os.environ["DATABASE_URL"]


def _run(coro_factory):
    async def wrap():
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as ac:
            ac.row_factory = dict_row
            return await coro_factory(ac)

    return asyncio.run(wrap())


def _run_notifier_cycle() -> None:
    """Прогін повного notifier.run_cycle через справжній пул (він бере
    з'єднання сам). Свіжий пул на виклик — без спільного стану між тестами."""
    from avelren import db

    async def run():
        db._pool = None
        pool = db.get_pool()
        await pool.open(wait=True, timeout=10)
        try:
            await notifier.run_cycle(client=None)
        finally:
            await pool.close()
            db._pool = None

    asyncio.run(run())


def _subscription(conn, device_id, checkpoint_id: int, threshold: int = 50) -> int:
    return conn.execute(
        "INSERT INTO subscriptions (device_id, checkpoint_id, threshold) "
        "VALUES (%s, %s, %s) RETURNING id",
        (device_id, checkpoint_id, threshold),
    ).fetchone()["id"]


def _fire_threshold(checkpoint_id: int, values: list[int]) -> None:
    async def run(ac):
        for v in values:
            item = WorkloadItem(
                id=checkpoint_id, title="t", for_vehicle_type=1,
                vehicle_in_active_queues_counts=v,
            )
            await alerts.evaluate(ac, [item])

    _run(run)


def _observe_low(conn, checkpoint_id: int, vehicles: int) -> None:
    """Свіже спостереження нижче порога — щоб expire_stale мав що читати."""
    conn.execute(
        "INSERT INTO observations (time, checkpoint_id, wait_time_seconds, "
        "vehicles_in_queue, is_paused) VALUES (now(), %s, 0, %s, false)",
        (checkpoint_id, vehicles),
    )


def _cancels(conn, kind: str, alert_id: int) -> int:
    return conn.execute(
        "SELECT count(*) AS n FROM notification_cancels WHERE kind = %s AND alert_id = %s",
        (kind, alert_id),
    ).fetchone()["n"]


def _alert_id(conn, sub_id: int) -> int:
    return conn.execute(
        "SELECT id FROM alerts WHERE subscription_id = %s ORDER BY id DESC LIMIT 1",
        (sub_id,),
    ).fetchone()["id"]


# --- enqueue при expire ----------------------------------------------------


def test_threshold_expire_enqueues_cancel(conn, device, checkpoint):
    sub = _subscription(conn, device.device_id, checkpoint)
    _fire_threshold(checkpoint, [49, 51])
    aid = _alert_id(conn, sub)

    _observe_low(conn, checkpoint, 10)
    _run(alerts.expire_stale)

    assert conn.execute(
        "SELECT status FROM alerts WHERE id = %s", (aid,)
    ).fetchone()["status"] == "expired"
    assert _cancels(conn, "threshold", aid) == 1
    # device_id прив'язаний правильно (БД віддає uuid.UUID — звіряємо як str).
    assert str(conn.execute(
        "SELECT device_id FROM notification_cancels WHERE kind='threshold' AND alert_id=%s",
        (aid,),
    ).fetchone()["device_id"]) == device.device_id


def test_expire_enqueues_cancel_even_when_send_count_zero(conn, device, checkpoint):
    """Найважливіший інваріант: send_count=0 (notifier упав до _mark_sent), а
    телефон міг показати нотифікацію — cancel усе одно потрібен."""
    sub = _subscription(conn, device.device_id, checkpoint)
    _fire_threshold(checkpoint, [49, 51])
    aid = _alert_id(conn, sub)
    assert conn.execute(
        "SELECT send_count FROM alerts WHERE id = %s", (aid,)
    ).fetchone()["send_count"] == 0

    _observe_low(conn, checkpoint, 10)
    _run(alerts.expire_stale)
    assert _cancels(conn, "threshold", aid) == 1


def test_eta_expire_enqueues_cancel(conn, device, checkpoint):
    now = datetime.now(UTC)
    tid = conn.execute(
        "INSERT INTO eta_targets (device_id, checkpoint_id, target_at, tolerance_seconds) "
        "VALUES (%s, %s, %s, 900) RETURNING id",
        (device.device_id, checkpoint, now + timedelta(hours=10)),
    ).fetchone()["id"]

    async def fire(ac):
        item = WorkloadItem(
            id=checkpoint, title="t", for_vehicle_type=1,
            wait_time=10 * 3600, vehicle_in_active_queues_counts=100,
        )
        await eta.evaluate(ac, now, [item])

    _run(fire)
    aid = conn.execute(
        "SELECT id FROM eta_alerts WHERE target_id = %s", (tid,)
    ).fetchone()["id"]

    # Зсуваємо ціль у минуле, щоб expire_passed її закрив.
    conn.execute("UPDATE eta_targets SET target_at = %s WHERE id = %s",
                 (now - timedelta(minutes=1), tid))
    _run(eta.expire_passed)

    assert _cancels(conn, "eta", aid) == 1


def test_ack_does_not_enqueue_cancel(conn, device, checkpoint):
    """ACK гасить локально — cancel не потрібен, тож і не enqueue-иться."""
    sub = _subscription(conn, device.device_id, checkpoint)
    _fire_threshold(checkpoint, [49, 51])
    aid = _alert_id(conn, sub)

    conn.execute(
        "UPDATE alerts SET status='acknowledged', acknowledged_at=now() WHERE id=%s", (aid,)
    )
    # Навіть якщо потім прийде низьке спостереження — expire чіпає лише pending.
    _observe_low(conn, checkpoint, 10)
    _run(alerts.expire_stale)
    assert _cancels(conn, "threshold", aid) == 0


# --- enqueue при delete (через API) ----------------------------------------


def test_delete_subscription_enqueues_cancel(conn, device, checkpoint, api_client):
    sub = _subscription(conn, device.device_id, checkpoint)
    _fire_threshold(checkpoint, [49, 51])
    aid = _alert_id(conn, sub)

    r = api_client.delete(f"/subscriptions/{sub}", headers=device.headers())
    assert r.status_code == 204
    assert _cancels(conn, "threshold", aid) == 1


def test_delete_foreign_subscription_enqueues_nothing(conn, device, checkpoint, api_client):
    """Чужий subscription_id не має enqueue-ити cancel від імені зловмисника."""
    # Підписка іншого пристрою.
    other = conn.execute(
        "INSERT INTO devices (fcm_token, secret_hash) VALUES ('other-tok', 'x') RETURNING id"
    ).fetchone()["id"]
    sub = _subscription(conn, other, checkpoint)
    _fire_threshold(checkpoint, [49, 51])
    aid = _alert_id(conn, sub)

    # device (не власник) намагається видалити.
    r = api_client.delete(f"/subscriptions/{sub}", headers=device.headers())
    assert r.status_code == 404
    assert _cancels(conn, "threshold", aid) == 0
    conn.execute("DELETE FROM devices WHERE id = %s", (other,))


# --- /active-alerts --------------------------------------------------------


def test_active_alerts_returns_pending_by_kind(conn, device, checkpoint, api_client):
    sub = _subscription(conn, device.device_id, checkpoint)
    _fire_threshold(checkpoint, [49, 51])
    aid = _alert_id(conn, sub)

    r = api_client.get("/active-alerts", headers=device.headers())
    assert r.status_code == 200
    body = r.json()
    assert body["threshold"] == [aid]
    assert body["eta"] == []

    # Після ACK — зникає з canonical-стану.
    conn.execute(
        "UPDATE alerts SET status='acknowledged', acknowledged_at=now() WHERE id=%s", (aid,)
    )
    body2 = api_client.get("/active-alerts", headers=device.headers()).json()
    assert body2["threshold"] == []


def test_active_alerts_ignores_send_count(conn, device, checkpoint, api_client):
    """Істина — статус, не send_count: pending із send_count=0 має бути в списку."""
    sub = _subscription(conn, device.device_id, checkpoint)
    _fire_threshold(checkpoint, [49, 51])
    aid = _alert_id(conn, sub)
    assert conn.execute(
        "SELECT send_count FROM alerts WHERE id=%s", (aid,)
    ).fetchone()["send_count"] == 0
    body = api_client.get("/active-alerts", headers=device.headers()).json()
    assert body["threshold"] == [aid]


# --- namespace threshold vs eta --------------------------------------------


def test_threshold_and_eta_same_alert_id_are_distinct(conn, device):
    """UNIQUE(kind, alert_id): однаковий числовий id для threshold і eta —
    два різні cancel-рядки, не конфлікт."""
    conn.execute(
        "INSERT INTO notification_cancels (kind, alert_id, device_id) VALUES "
        "('threshold', 777, %s), ('eta', 777, %s)",
        (device.device_id, device.device_id),
    )
    assert _cancels(conn, "threshold", 777) == 1
    assert _cancels(conn, "eta", 777) == 1


# --- notifier відправка cancel'ів ------------------------------------------


def test_notifier_sends_cancel_and_marks_accepted(conn, device, checkpoint, monkeypatch):
    conn.execute("UPDATE devices SET fcm_token='tok-cancel' WHERE id=%s", (device.device_id,))
    row = conn.execute(
        "INSERT INTO notification_cancels (kind, alert_id, device_id) "
        "VALUES ('threshold', 42, %s) RETURNING id",
        (device.device_id,),
    ).fetchone()

    calls = []

    async def fake_send(client, token, data, collapse_key=None, ttl_seconds=600):
        calls.append((token, data, collapse_key))

    monkeypatch.setattr("avelren.fcm.send", fake_send)

    async def run(ac):
        await notifier._send_cancels(client=None, conn=ac)

    _run(run)

    assert len(calls) == 1
    token, data, collapse = calls[0]
    assert token == "tok-cancel"
    assert data == {"type": "cancel", "kind": "threshold", "cancel_alert_id": "42"}
    assert collapse == "threshold:42"
    assert conn.execute(
        "SELECT accepted_at IS NOT NULL AS ok FROM notification_cancels WHERE id=%s",
        (row["id"],),
    ).fetchone()["ok"] is True


def test_notifier_abandons_cancel_for_dead_token(conn, device):
    conn.execute("UPDATE devices SET fcm_token=NULL WHERE id=%s", (device.device_id,))
    row = conn.execute(
        "INSERT INTO notification_cancels (kind, alert_id, device_id) "
        "VALUES ('eta', 99, %s) RETURNING id",
        (device.device_id,),
    ).fetchone()

    async def run(ac):
        await notifier._send_cancels(client=None, conn=ac)

    _run(run)

    assert conn.execute(
        "SELECT abandoned_at IS NOT NULL AS ok FROM notification_cancels WHERE id=%s",
        (row["id"],),
    ).fetchone()["ok"] is True


def _fcm_error(*, dead_token: bool) -> fcm.FcmError:
    return fcm.FcmError(
        http_status=404 if dead_token else 400,
        canonical_status="NOT_FOUND" if dead_token else "INVALID_ARGUMENT",
        fcm_error_code="UNREGISTERED" if dead_token else None,
        message="test failure",
        dead_token=dead_token,
        retryable=False,
    )


def test_normal_payload_error_keeps_device_token(conn, device, checkpoint, monkeypatch):
    conn.execute("UPDATE devices SET fcm_token='tok-valid' WHERE id=%s", (device.device_id,))
    sub = _subscription(conn, device.device_id, checkpoint)
    _fire_threshold(checkpoint, [49, 51])
    alert_id = _alert_id(conn, sub)

    async def fail_send(*args, **kwargs):
        raise _fcm_error(dead_token=False)

    monkeypatch.setattr("avelren.fcm.send", fail_send)
    _run_notifier_cycle()

    row = conn.execute(
        "SELECT fcm_token FROM devices WHERE id=%s", (device.device_id,)
    ).fetchone()
    assert row["fcm_token"] == "tok-valid"
    assert conn.execute(
        "SELECT send_count FROM alerts WHERE id=%s", (alert_id,)
    ).fetchone()["send_count"] == 0


def test_normal_confirmed_unregistered_disables_device(conn, device, checkpoint, monkeypatch):
    conn.execute("UPDATE devices SET fcm_token='tok-dead' WHERE id=%s", (device.device_id,))
    sub = _subscription(conn, device.device_id, checkpoint)
    _fire_threshold(checkpoint, [49, 51])

    async def fail_send(*args, **kwargs):
        raise _fcm_error(dead_token=True)

    monkeypatch.setattr("avelren.fcm.send", fail_send)
    _run_notifier_cycle()

    assert conn.execute(
        "SELECT fcm_token FROM devices WHERE id=%s", (device.device_id,)
    ).fetchone()["fcm_token"] is None
    assert _alert_id(conn, sub) is not None


def test_cancel_payload_error_keeps_device_token_and_retries(conn, device, monkeypatch):
    conn.execute("UPDATE devices SET fcm_token='tok-valid' WHERE id=%s", (device.device_id,))
    row = conn.execute(
        "INSERT INTO notification_cancels (kind, alert_id, device_id) "
        "VALUES ('threshold', 100, %s) RETURNING id",
        (device.device_id,),
    ).fetchone()

    async def fail_send(*args, **kwargs):
        raise _fcm_error(dead_token=False)

    monkeypatch.setattr("avelren.fcm.send", fail_send)
    _run(lambda ac: notifier._send_cancels(client=None, conn=ac))

    assert conn.execute(
        "SELECT fcm_token FROM devices WHERE id=%s", (device.device_id,)
    ).fetchone()["fcm_token"] == "tok-valid"
    cancel = conn.execute(
        "SELECT attempt_count, abandoned_at FROM notification_cancels WHERE id=%s",
        (row["id"],),
    ).fetchone()
    assert cancel["attempt_count"] == 1
    assert cancel["abandoned_at"] is None


def test_cancel_confirmed_unregistered_disables_and_abandons(conn, device, monkeypatch):
    conn.execute("UPDATE devices SET fcm_token='tok-dead' WHERE id=%s", (device.device_id,))
    row = conn.execute(
        "INSERT INTO notification_cancels (kind, alert_id, device_id) "
        "VALUES ('eta', 101, %s) RETURNING id",
        (device.device_id,),
    ).fetchone()

    async def fail_send(*args, **kwargs):
        raise _fcm_error(dead_token=True)

    monkeypatch.setattr("avelren.fcm.send", fail_send)
    _run(lambda ac: notifier._send_cancels(client=None, conn=ac))

    assert conn.execute(
        "SELECT fcm_token FROM devices WHERE id=%s", (device.device_id,)
    ).fetchone()["fcm_token"] is None
    assert conn.execute(
        "SELECT abandoned_at IS NOT NULL AS abandoned "
        "FROM notification_cancels WHERE id=%s",
        (row["id"],),
    ).fetchone()["abandoned"] is True


def test_cancel_not_abandoned_while_young(conn, device):
    """Свіжий cancel після невдалої спроби НЕ здається — ретраїмо далі (B3)."""
    row = conn.execute(
        "INSERT INTO notification_cancels (kind, alert_id, device_id) "
        "VALUES ('threshold', 55, %s) RETURNING id",
        (device.device_id,),
    ).fetchone()

    _run(lambda ac: cancels.record_attempt(ac, row["id"]))

    r = conn.execute(
        "SELECT abandoned_at, attempt_count FROM notification_cancels WHERE id=%s",
        (row["id"],),
    ).fetchone()
    assert r["abandoned_at"] is None
    assert r["attempt_count"] == 1


def test_cancel_abandoned_after_age_window(conn, device):
    """Cancel, старший за ABANDON_AFTER, здається — далі підстрахує
    reconciliation (B3). Час старіння емулюємо зсувом created_at."""
    row = conn.execute(
        "INSERT INTO notification_cancels (kind, alert_id, device_id, created_at) "
        "VALUES ('threshold', 56, %s, now() - INTERVAL '61 minutes') RETURNING id",
        (device.device_id,),
    ).fetchone()

    _run(lambda ac: cancels.record_attempt(ac, row["id"]))

    assert conn.execute(
        "SELECT abandoned_at IS NOT NULL AS ok FROM notification_cancels WHERE id=%s",
        (row["id"],),
    ).fetchone()["ok"] is True


def test_cancel_payload_uses_cancel_alert_id_not_legacy():
    """B1: cancel НЕ містить legacy-поля alert_id — старий APK (baseline
    c7d2e1f) на такому повідомленні нічого не показує, бо доходить до
    `data["alert_id"] ?: return`."""
    from avelren import fcm

    p = fcm.cancel_payload("eta", 42)
    assert p == {"type": "cancel", "kind": "eta", "cancel_alert_id": "42"}
    assert "alert_id" not in p


# --- race normal ↔ expire ↔ cancel -----------------------------------------


def test_race_expire_during_normal_push_still_cancels(conn, device, checkpoint, monkeypatch):
    """Найцінніший тест: alert expire-иться ПОСЕРЕД normal-фази циклу.

    Сервер уже вибрав його як pending для normal push. Під час fcm.send()
    (тут — у фейку) черга падає і expire_stale закриває alert + enqueue-ить
    cancel. Той самий run_cycle має:
      * НЕ зафіксувати normal push як успішний (send_count лишається 0,
        бо _mark_sent conditional на status='pending');
      * відправити cancel після normal push у тому ж циклі.
    """
    conn.execute("UPDATE devices SET fcm_token='tok-race' WHERE id=%s", (device.device_id,))
    sub = _subscription(conn, device.device_id, checkpoint)
    _fire_threshold(checkpoint, [49, 51])
    aid = _alert_id(conn, sub)

    sent = []

    async def fake_send(client, token, data, collapse_key=None, ttl_seconds=600):
        sent.append(data["type"])
        if data["type"] == "threshold":
            # Симулюємо expire саме під час normal push, окремим з'єднанням.
            async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as ac2:
                ac2.row_factory = dict_row
                await ac2.execute(
                    "INSERT INTO observations (time, checkpoint_id, wait_time_seconds, "
                    "vehicles_in_queue, is_paused) VALUES (now(), %s, 0, 10, false)",
                    (checkpoint,),
                )
                await alerts.expire_stale(ac2)

    monkeypatch.setattr("avelren.fcm.send", fake_send)

    _run_notifier_cycle()

    # normal push НЕ зафіксований як успішний (alert уже expired).
    assert conn.execute(
        "SELECT send_count FROM alerts WHERE id=%s", (aid,)
    ).fetchone()["send_count"] == 0
    # cancel відправлено після normal push у тому ж циклі.
    assert sent == ["threshold", "cancel"]
    assert conn.execute(
        "SELECT accepted_at IS NOT NULL AS ok FROM notification_cancels "
        "WHERE kind='threshold' AND alert_id=%s",
        (aid,),
    ).fetchone()["ok"] is True
