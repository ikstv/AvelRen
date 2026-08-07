"""Перевірка функції «хочу в'їзд о 22:15».

Функція планується платною, тож помилка тут коштує не роздратування, а грошей
і довіри. Найгірші сценарії: сповіщення не прийшло у вікні (людина проґавила
момент) і сповіщення прийшло не в тому вікні (людина зареєструвалась дарма).
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row

from avelren import eta
from avelren.models import WorkloadItem

DSN = os.environ["DATABASE_URL"]


def _target(conn, device_id, checkpoint_id: int, target_at: datetime, tolerance: int = 900) -> int:
    return conn.execute(
        """
        INSERT INTO eta_targets (device_id, checkpoint_id, target_at, tolerance_seconds)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        (device_id, checkpoint_id, target_at, tolerance),
    ).fetchone()["id"]


def _pending(conn, target_id: int) -> int:
    return conn.execute(
        "SELECT count(*) AS n FROM eta_alerts WHERE target_id = %s AND status = 'pending'",
        (target_id,),
    ).fetchone()["n"]


def _observe(checkpoint_id: int, at: datetime, wait_seconds: int, is_paused: bool = False) -> None:
    """Проганяє один замір через ту саму логіку, що й збирач."""

    async def run() -> None:
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as ac:
            ac.row_factory = dict_row
            item = WorkloadItem(
                id=checkpoint_id,
                title="test",
                for_vehicle_type=1,
                wait_time=wait_seconds,
                is_paused=is_paused,
                vehicle_in_active_queues_counts=100,
            )
            await eta.evaluate(ac, at, [item])

    asyncio.run(run())


def test_eta_formula_matches_source():
    """Звірка з єЧергою: замір + wait_time = показаний час в'їзду."""
    observed = datetime(2026, 8, 7, 0, 45, 38, tzinfo=UTC)
    result = eta.entry_eta(observed, 336420)  # 3д 21г 27хв
    assert result == datetime(2026, 8, 10, 22, 12, 38, tzinfo=UTC)


def test_fires_inside_window(conn, device, checkpoint):
    now = datetime.now(UTC)
    tid = _target(conn, device.device_id, checkpoint, now + timedelta(hours=10))

    _observe(checkpoint, now, wait_seconds=10 * 3600)  # рівно в ціль
    assert _pending(conn, tid) == 1


def test_fires_at_window_edge(conn, device, checkpoint):
    """14 хвилин розбіжності при допуску 15 — це ще потрапляння."""
    now = datetime.now(UTC)
    tid = _target(conn, device.device_id, checkpoint, now + timedelta(hours=10))

    _observe(checkpoint, now, wait_seconds=10 * 3600 + 14 * 60)
    assert _pending(conn, tid) == 1


def test_silent_outside_window(conn, device, checkpoint):
    """16 хвилин — уже повз. Хибне спрацювання гірше за мовчання."""
    now = datetime.now(UTC)
    tid = _target(conn, device.device_id, checkpoint, now + timedelta(hours=10))

    _observe(checkpoint, now, wait_seconds=10 * 3600 + 16 * 60)
    assert _pending(conn, tid) == 0


def test_no_duplicates_while_pending(conn, device, checkpoint):
    """Вікно триває багато хвилин; щохвилинне сповіщення було б спамом."""
    now = datetime.now(UTC)
    tid = _target(conn, device.device_id, checkpoint, now + timedelta(hours=10))

    for i in range(5):
        _observe(checkpoint, now + timedelta(minutes=i), wait_seconds=10 * 3600)
    assert _pending(conn, tid) == 1


def test_paused_queue_does_not_fire(conn, device, checkpoint):
    """Пауза з нульовим очікуванням — це відсутність прогнозу, а не «в'їзд зараз»."""
    now = datetime.now(UTC)
    tid = _target(conn, device.device_id, checkpoint, now, tolerance=900)

    _observe(checkpoint, now, wait_seconds=0, is_paused=True)
    assert _pending(conn, tid) == 0


def test_no_refire_after_ack_in_same_window(conn, device, checkpoint, api_client):
    """Регресія на знахідку аудиту R-05.

    Підтвердження йде через справжній ендпоінт `/eta-alerts/{id}/ack`, а не
    через ті самі два UPDATE, які він виконує: інакше тест перевіряв би сам
    себе й не помітив би, якби ендпоінт перестав деактивувати ціль.
    """
    now = datetime.now(UTC)
    tid = _target(conn, device.device_id, checkpoint, now + timedelta(hours=10))

    _observe(checkpoint, now, wait_seconds=10 * 3600)
    assert _pending(conn, tid) == 1

    alert_id = conn.execute(
        "SELECT id FROM eta_alerts WHERE target_id = %s AND status = 'pending'", (tid,)
    ).fetchone()["id"]

    response = api_client.post(
        f"/eta-alerts/{alert_id}/ack", headers=device.headers()
    )
    assert response.status_code == 200
    assert response.json()["status"] == "acknowledged"

    # Ендпоінт мусив і закрити алерт, і зняти ціль з обліку.
    assert _pending(conn, tid) == 0
    assert conn.execute(
        "SELECT is_active FROM eta_targets WHERE id = %s", (tid,)
    ).fetchone()["is_active"] is False

    # Наступні цикли в тому самому вікні — тиша.
    for i in range(1, 4):
        _observe(checkpoint, now + timedelta(minutes=i), wait_seconds=10 * 3600)
    assert _pending(conn, tid) == 0
