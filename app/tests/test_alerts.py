"""Перевірка логіки порогів на синтетичних даних.

Найдорожча помилка тут — спам: сповіщення, яке будить людину щохвилини,
видаляють разом із застосунком. Тому дрібним коливанням на межі присвячено
окремий тест.

Дані тест створює сам (див. `conftest.py`): ані готового довідника, ані
попередніх запусків збирача не потрібно.

Запуск (потрібна жива тестова БД):
    AVELREN_TEST_DB=1 python -m pytest app/tests -q
"""

import asyncio
import os

import psycopg
from psycopg.rows import dict_row

from avelren import alerts
from avelren.models import WorkloadItem

DSN = os.environ["DATABASE_URL"]


def _subscription(conn, device_id, checkpoint_id: int) -> int:
    return conn.execute(
        """
        INSERT INTO subscriptions (device_id, checkpoint_id, threshold)
        VALUES (%s, %s, 50) RETURNING id
        """,
        (device_id, checkpoint_id),
    ).fetchone()["id"]


def _pending(conn, sub_id: int) -> int:
    return conn.execute(
        "SELECT count(*) AS n FROM alerts WHERE subscription_id = %s AND status = 'pending'",
        (sub_id,),
    ).fetchone()["n"]


def _feed(checkpoint_id: int, values: list[int]) -> None:
    """Проганяє послідовність значень черги через ту саму логіку, що й збирач."""

    async def run() -> None:
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as ac:
            ac.row_factory = dict_row
            for v in values:
                item = WorkloadItem(
                    id=checkpoint_id,
                    title="test",
                    for_vehicle_type=1,
                    vehicle_in_active_queues_counts=v,
                )
                await alerts.evaluate(ac, [item])

    asyncio.run(run())


def test_crossing_upward_creates_one_alert(conn, device, checkpoint):
    sub = _subscription(conn, device.device_id, checkpoint)
    _feed(checkpoint, [49, 51])
    assert _pending(conn, sub) == 1


def test_flapping_does_not_spam(conn, device, checkpoint):
    """49->51->49->51->49->51 має дати рівно один алерт, а не три."""
    sub = _subscription(conn, device.device_id, checkpoint)
    _feed(checkpoint, [49, 51, 49, 51, 49, 51])
    assert _pending(conn, sub) == 1


def test_rearm_requires_margin(conn, device, checkpoint):
    """Після підтвердження поріг 50 перезаряджається лише нижче 45."""
    sub = _subscription(conn, device.device_id, checkpoint)
    _feed(checkpoint, [49, 51])
    conn.execute(
        "UPDATE alerts SET status = 'acknowledged', acknowledged_at = now() "
        "WHERE subscription_id = %s",
        (sub,),
    )

    _feed(checkpoint, [46, 60])  # 46 > 45 — перезарядки не сталося
    assert _pending(conn, sub) == 0

    _feed(checkpoint, [44, 51])  # 44 < 45 — перезарядка й нове спрацювання
    assert _pending(conn, sub) == 1


def test_no_alert_below_threshold(conn, device, checkpoint):
    sub = _subscription(conn, device.device_id, checkpoint)
    _feed(checkpoint, [10, 20, 49])
    assert _pending(conn, sub) == 0


def test_exact_threshold_fires(conn, device, checkpoint):
    """Рівно 50 — це спрацювання, а не «майже»."""
    sub = _subscription(conn, device.device_id, checkpoint)
    _feed(checkpoint, [49, 50])
    assert _pending(conn, sub) == 1


def test_jump_over_threshold_fires(conn, device, checkpoint):
    """Черга змінюється і на 2 авто за раз, тож 49->51 не сміє проскочити повз."""
    sub = _subscription(conn, device.device_id, checkpoint)
    _feed(checkpoint, [49, 51])
    assert _pending(conn, sub) == 1
