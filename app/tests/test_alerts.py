"""Перевірка логіки порогів на синтетичних даних.

Найдорожча помилка тут — спам: сповіщення, яке будить людину щохвилини,
видаляють разом із застосунком. Тому дрібним коливанням на межі присвячено
окремий тест.

Запуск (потрібна жива БД):
    docker compose run --rm -T migrate python -m pytest /app/tests -q
"""

import os

import psycopg
import pytest

DSN = os.environ["DATABASE_URL"]
CHECKPOINT_ID = 1  # Ягодин – Дорогуськ, є в довіднику


@pytest.fixture()
def conn():
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("DELETE FROM alerts WHERE threshold = 50")
        c.execute(
            "DELETE FROM devices WHERE fcm_token = 'test-token'"
        )  # каскадом знімає підписки й стан
        yield c
        c.execute("DELETE FROM alerts WHERE threshold = 50")
        c.execute("DELETE FROM devices WHERE fcm_token = 'test-token'")


def _subscription(conn) -> int:
    device = conn.execute(
        "INSERT INTO devices (fcm_token) VALUES ('test-token') RETURNING id"
    ).fetchone()[0]
    return conn.execute(
        """
        INSERT INTO subscriptions (device_id, checkpoint_id, threshold)
        VALUES (%s, %s, 50) RETURNING id
        """,
        (device, CHECKPOINT_ID),
    ).fetchone()[0]


def _pending(conn, sub_id: int) -> int:
    return conn.execute(
        "SELECT count(*) FROM alerts WHERE subscription_id = %s AND status = 'pending'",
        (sub_id,),
    ).fetchone()[0]


def test_crossing_upward_creates_one_alert(conn):
    sub = _subscription(conn)
    _feed(conn, sub, [49, 51])
    assert _pending(conn, sub) == 1


def test_flapping_does_not_spam(conn):
    """49->51->49->51->49->51 має дати рівно один алерт, а не три."""
    sub = _subscription(conn)
    _feed(conn, sub, [49, 51, 49, 51, 49, 51])
    assert _pending(conn, sub) == 1


def test_rearm_requires_margin(conn):
    """Після підтвердження поріг 50 перезаряджається лише нижче 45."""
    sub = _subscription(conn)
    _feed(conn, sub, [49, 51])
    conn.execute(
        "UPDATE alerts SET status = 'acknowledged', acknowledged_at = now() "
        "WHERE subscription_id = %s",
        (sub,),
    )

    _feed(conn, sub, [46, 60])  # 46 > 45 — перезарядки не сталося
    assert _pending(conn, sub) == 0

    _feed(conn, sub, [44, 51])  # 44 < 45 — перезарядка й нове спрацювання
    assert _pending(conn, sub) == 1


def test_no_alert_below_threshold(conn):
    sub = _subscription(conn)
    _feed(conn, sub, [10, 20, 49])
    assert _pending(conn, sub) == 0


def _feed(conn, sub_id: int, values: list[int]) -> None:
    """Проганяє послідовність значень черги через ту саму логіку, що й збирач."""
    import asyncio

    from avelren import alerts
    from avelren.models import WorkloadItem

    async def run() -> None:
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as ac:
            ac.row_factory = psycopg.rows.dict_row
            for v in values:
                item = WorkloadItem(
                    id=CHECKPOINT_ID,
                    title="test",
                    for_vehicle_type=1,
                    vehicle_in_active_queues_counts=v,
                )
                await alerts.evaluate(ac, [item])

    asyncio.run(run())


def test_exact_threshold_fires(conn):
    """Рівно 50 — це спрацювання, а не «майже»."""
    sub = _subscription(conn)
    _feed(conn, sub, [49, 50])
    assert _pending(conn, sub) == 1


def test_jump_over_threshold_fires(conn):
    """Черга змінюється і на 2 авто за раз, тож 49->51 не сміє проскочити повз."""
    sub = _subscription(conn)
    _feed(conn, sub, [49, 51])
    assert _pending(conn, sub) == 1
