"""Перевірка функції «хочу в'їзд о 22:15».

Функція планується платною, тож помилка тут коштує не роздратування, а грошей
і довіри. Найгірші сценарії: сповіщення не прийшло у вікні (людина проґавила
момент) і сповіщення прийшло не в тому вікні (людина зареєструвалась дарма).
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.rows import dict_row

from avelren import eta
from avelren.models import WorkloadItem

DSN = os.environ["DATABASE_URL"]
CHECKPOINT_ID = 5  # Рава-Руська – Хребенне


@pytest.fixture()
def conn():
    with psycopg.connect(DSN, autocommit=True, row_factory=dict_row) as c:
        _clean(c)
        yield c
        _clean(c)


def _clean(c) -> None:
    c.execute("DELETE FROM devices WHERE fcm_token = 'test-eta'")


def _target(conn, target_at: datetime, tolerance: int = 900) -> int:
    device = conn.execute(
        "INSERT INTO devices (fcm_token) VALUES ('test-eta') RETURNING id"
    ).fetchone()["id"]
    return conn.execute(
        """
        INSERT INTO eta_targets (device_id, checkpoint_id, target_at, tolerance_seconds)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        (device, CHECKPOINT_ID, target_at, tolerance),
    ).fetchone()["id"]


def _pending(conn, target_id: int) -> int:
    return conn.execute(
        "SELECT count(*) AS n FROM eta_alerts WHERE target_id = %s AND status = 'pending'",
        (target_id,),
    ).fetchone()["n"]


def _observe(at: datetime, wait_seconds: int, is_paused: bool = False) -> None:
    """Проганяє один замір через ту саму логіку, що й збирач."""

    async def run() -> None:
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as ac:
            ac.row_factory = dict_row
            item = WorkloadItem(
                id=CHECKPOINT_ID,
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


def test_fires_inside_window(conn):
    now = datetime.now(UTC)
    target_at = now + timedelta(hours=10)
    tid = _target(conn, target_at)

    _observe(now, wait_seconds=10 * 3600)  # рівно в ціль
    assert _pending(conn, tid) == 1


def test_fires_at_window_edge(conn):
    """14 хвилин розбіжності при допуску 15 — це ще потрапляння."""
    now = datetime.now(UTC)
    tid = _target(conn, now + timedelta(hours=10))

    _observe(now, wait_seconds=10 * 3600 + 14 * 60)
    assert _pending(conn, tid) == 1


def test_silent_outside_window(conn):
    """16 хвилин — уже повз. Хибне спрацювання гірше за мовчання."""
    now = datetime.now(UTC)
    tid = _target(conn, now + timedelta(hours=10))

    _observe(now, wait_seconds=10 * 3600 + 16 * 60)
    assert _pending(conn, tid) == 0


def test_no_duplicates_while_pending(conn):
    """Вікно триває багато хвилин; щохвилинне сповіщення було б спамом."""
    now = datetime.now(UTC)
    tid = _target(conn, now + timedelta(hours=10))

    for i in range(5):
        _observe(now + timedelta(minutes=i), wait_seconds=10 * 3600)
    assert _pending(conn, tid) == 1


def test_paused_queue_does_not_fire(conn):
    """Пауза з нульовим очікуванням — це відсутність прогнозу, а не «в'їзд зараз»."""
    now = datetime.now(UTC)
    tid = _target(conn, now, tolerance=900)

    _observe(now, wait_seconds=0, is_paused=True)
    assert _pending(conn, tid) == 0


def test_no_refire_after_ack_in_same_window(conn):
    """Регресія на знахідку аудиту R-05: після ОК у тому самому вікні НЕ
    створюється новий алерт. Вимога власника пряма: після ОК сповіщення
    більше не потрібне."""
    now = datetime.now(UTC)
    tid = _target(conn, now + timedelta(hours=10))

    _observe(now, wait_seconds=10 * 3600)
    assert _pending(conn, tid) == 1

    # Підтвердження робить те саме, що ендпоінт /eta-alerts/{id}/ack:
    # закриває алерт і деактивує ціль.
    conn.execute(
        "UPDATE eta_alerts SET status = 'acknowledged', acknowledged_at = now() "
        "WHERE target_id = %s",
        (tid,),
    )
    conn.execute("UPDATE eta_targets SET is_active = false WHERE id = %s", (tid,))

    # Наступні цикли в тому самому вікні — тиша.
    for i in range(1, 4):
        _observe(now + timedelta(minutes=i), wait_seconds=10 * 3600)
    assert _pending(conn, tid) == 0
