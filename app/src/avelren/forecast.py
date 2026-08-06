"""Функція №3: прогноз завантаженості КПП.

Базова модель — **сезонний наївний прогноз**: очікування о вівторок 09:00
беремо як середнє по вівторках 09:00 за попередні тижні. На таких рядах вона
несподівано сильна, і будь-яка складніша модель мусить її побити на тих самих
даних, інакше не впроваджуємо (див. `docs/forecast.md`).

Головне тут не якість моделі, а **чесність про достатність даних**. Тижнева
сезонність — головний сигнал, і оцінити її можна лише маючи достатньо повторів
кожного дня тижня. На двох тижнях будь-яка модель вивчить шум і показуватиме
впевнені дурниці — а на них люди планують рейси.

Тому прогноз має три стани, і користувач завжди бачить, у якому він:
  collecting   — даних замало, прогнозу немає взагалі;
  preliminary  — прогноз є, але попередній, з широким діапазоном;
  ready        — даних достатньо.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from psycopg import AsyncConnection

log = logging.getLogger("avelren.forecast")

# Мінімум повторів кожного слоту (день тижня + година), щоб узагалі щось
# показувати, і скільки треба для повноцінного прогнозу.
MIN_SAMPLES_PRELIMINARY = 2
MIN_SAMPLES_READY = 8

# Скільки тижнів історії враховуємо. Далекі тижні гірше описують сьогодення:
# змінюються правила, пропускна спроможність, потоки.
LOOKBACK_WEEKS = 12


@dataclass
class Readiness:
    status: str  # collecting | preliminary | ready
    weeks_collected: float
    weeks_needed: int
    ready_at: datetime | None


async def readiness(conn: AsyncConnection, checkpoint_id: int) -> Readiness:
    row = await (
        await conn.execute(
            """
            SELECT min(time) AS since, max(time) AS until
            FROM observations WHERE checkpoint_id = %s
            """,
            (checkpoint_id,),
        )
    ).fetchone()

    if not row or row["since"] is None:
        return Readiness("collecting", 0.0, MIN_SAMPLES_READY, None)

    span_days = (row["until"] - row["since"]).total_seconds() / 86400
    weeks = span_days / 7

    if weeks >= MIN_SAMPLES_READY:
        status = "ready"
    elif weeks >= MIN_SAMPLES_PRELIMINARY:
        status = "preliminary"
    else:
        status = "collecting"

    ready_at = row["since"] + timedelta(weeks=MIN_SAMPLES_READY)
    return Readiness(status, round(weeks, 2), MIN_SAMPLES_READY, ready_at)


async def forecast(
    conn: AsyncConnection, checkpoint_id: int, hours_ahead: int = 24
) -> dict:
    """Прогноз на найближчі години з розрізом по годинах.

    Повертає діапазон, а не одне число: «2–4 дні» чесніше за «3 дні 14 годин».
    Друге створює хибну точність.
    """
    state = await readiness(conn, checkpoint_id)

    result: dict = {
        "checkpoint_id": checkpoint_id,
        "status": state.status,
        "weeks_collected": state.weeks_collected,
        "weeks_needed": state.weeks_needed,
        "ready_at": state.ready_at,
        "method": "seasonal_naive",
        "points": [],
    }

    if state.status == "collecting":
        # Свідомо не повертаємо нічого: показати прогноз на добі даних —
        # означає збрехати впевненим тоном.
        return result

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    since = now - timedelta(weeks=LOOKBACK_WEEKS)

    rows = await (
        await conn.execute(
            """
            SELECT
                EXTRACT(dow  FROM bucket)::int AS dow,
                EXTRACT(hour FROM bucket)::int AS hour,
                percentile_cont(0.25) WITHIN GROUP (ORDER BY avg_wait_seconds) AS p25,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY avg_wait_seconds) AS p50,
                percentile_cont(0.75) WITHIN GROUP (ORDER BY avg_wait_seconds) AS p75,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY avg_vehicles)     AS vehicles,
                count(*) AS samples
            FROM observations_hourly
            WHERE checkpoint_id = %s AND bucket >= %s
            GROUP BY dow, hour
            """,
            (checkpoint_id, since),
        )
    ).fetchall()

    by_slot = {(r["dow"], r["hour"]): r for r in rows}

    for i in range(1, hours_ahead + 1):
        at = now + timedelta(hours=i)
        # Python: понеділок = 0, неділя = 6. PostgreSQL: неділя = 0, субота = 6.
        pg_dow = (at.weekday() + 1) % 7
        slot = by_slot.get((pg_dow, at.hour))
        if slot is None or slot["samples"] < MIN_SAMPLES_PRELIMINARY:
            continue

        result["points"].append(
            {
                "time": at,
                "wait_seconds_low": int(slot["p25"]),
                "wait_seconds_expected": int(slot["p50"]),
                "wait_seconds_high": int(slot["p75"]),
                "vehicles_expected": int(slot["vehicles"]),
                "samples": slot["samples"],
            }
        )

    return result


async def evaluate(conn: AsyncConnection, checkpoint_id: int) -> dict:
    """Похибка базової моделі на наявній історії.

    Без цього числа неможливо сказати, чи майбутня складніша модель узагалі
    щось покращила. Міряємо середню абсолютну похибку в годинах.
    """
    row = await (
        await conn.execute(
            """
            WITH actual AS (
                SELECT bucket, avg_wait_seconds,
                       EXTRACT(dow  FROM bucket)::int AS dow,
                       EXTRACT(hour FROM bucket)::int AS hour
                FROM observations_hourly
                WHERE checkpoint_id = %s
            ),
            predicted AS (
                SELECT dow, hour,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY avg_wait_seconds) AS p50
                FROM actual GROUP BY dow, hour
            )
            SELECT count(*) AS n,
                   avg(abs(a.avg_wait_seconds - p.p50)) / 3600.0 AS mae_hours
            FROM actual a JOIN predicted p ON p.dow = a.dow AND p.hour = a.hour
            """,
            (checkpoint_id,),
        )
    ).fetchone()

    return {
        "checkpoint_id": checkpoint_id,
        "method": "seasonal_naive",
        "samples": row["n"] if row else 0,
        "mae_hours": round(float(row["mae_hours"]), 2) if row and row["mae_hours"] else None,
        # Похибка, порахована на тих самих даних, на яких будувалась модель,
        # завжди оптимістична. Чесна оцінка зʼявиться, коли вистачить історії
        # на розділення навчання й перевірки.
        "note": "оцінка на тих самих даних, оптимістична",
    }
