"""Перевірка функції №3 — АІ Прогноз.

Найнебезпечніша помилка тут тиха: прогноз візьме дані з чужого дня тижня,
нічого не впаде, а числа виглядатимуть правдоподібно. Саме таку помилку я вже
припустився при написанні — Python рахує понеділок як 0, PostgreSQL неділю як
0. Тому перетворенню присвячено окремий тест.

Друге, що тут захищаємо, — відмова показувати прогноз на недостатніх даних.
Функція планується платною, і «впевнена вигадка» коштувала б довіри.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.rows import dict_row

from avelren import forecast

DSN = os.environ["DATABASE_URL"]


def _run(coro):
    async def wrap():
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as ac:
            ac.row_factory = dict_row
            return await coro(ac)

    return asyncio.run(wrap())


def test_weekday_conversion_matches_postgres():
    """Python: понеділок=0, неділя=6. PostgreSQL: неділя=0, субота=6.

    Помилка тут не падає, а мовчки бере дані з іншого дня тижня.
    """

    async def check(conn):
        bad = []
        for offset in range(7):
            at = datetime(2026, 8, 3, 12, tzinfo=UTC) + timedelta(days=offset)  # 3.08 — понеділок
            ours = (at.weekday() + 1) % 7
            row = await (
                await conn.execute("SELECT EXTRACT(dow FROM %s::timestamptz)::int AS dow", (at,))
            ).fetchone()
            if ours != row["dow"]:
                bad.append((at.date().isoformat(), ours, row["dow"]))
        return bad

    assert _run(check) == []


def test_readiness_reports_progress(checkpoint):
    async def check(conn):
        return await forecast.readiness(conn, checkpoint)

    state = _run(check)
    assert state.status in {"collecting", "preliminary", "ready"}
    assert state.weeks_collected >= 0
    assert state.weeks_needed == forecast.MIN_SAMPLES_READY


def test_no_points_while_collecting(checkpoint):
    """Поки даних замало — жодної точки. Мовчання чесніше за вигадку."""

    async def check(conn):
        return await forecast.forecast(conn, checkpoint, hours_ahead=24)

    result = _run(check)
    if result["status"] == "collecting":
        assert result["points"] == []
    else:
        assert result["points"], "у стані preliminary/ready точки мають бути"


def test_ready_at_is_in_the_future_or_none(checkpoint):
    """Дата готовності — орієнтир для користувача, вона не має бути в минулому,
    поки прогноз ще не готовий."""

    async def check(conn):
        return await forecast.readiness(conn, checkpoint)

    state = _run(check)
    if state.status != "ready" and state.ready_at is not None:
        assert state.ready_at > datetime.now(UTC)


def test_unknown_checkpoint_does_not_crash():
    async def check(conn):
        return await forecast.forecast(conn, 999999, hours_ahead=6)

    result = _run(check)
    assert result["status"] == "collecting"
    assert result["points"] == []


def test_evaluate_returns_honest_note(checkpoint):
    """Похибка, порахована на тих самих даних, завжди оптимістична — і це
    має бути видно тому, хто читає число."""

    async def check(conn):
        return await forecast.evaluate(conn, checkpoint)

    result = _run(check)
    assert result["method"] == "seasonal_naive"
    assert "оптимістична" in result["note"]


@pytest.mark.parametrize(
    "status,expected",
    [("collecting", True), ("preliminary", False), ("ready", False)],
)
def test_status_thresholds(status, expected):
    """Межі станів не мають зʼїхати непомітно при правках."""
    assert (forecast.MIN_SAMPLES_PRELIMINARY < forecast.MIN_SAMPLES_READY) is True
    assert forecast.MIN_SAMPLES_READY == 8
