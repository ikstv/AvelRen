"""Feature #3: checkpoint workload forecast.

The base model is a **seasonal naive forecast**: the expectation for Tuesday
09:00 is taken as the average over Tuesdays 09:00 in prior weeks. On such series
it is surprisingly strong, and any more complex model must beat it on the same
data, otherwise we do not adopt it (see `docs/forecast.md`).

The key thing here is not the model's quality but **honesty about data
sufficiency**. Weekly seasonality is the main signal, and it can only be
estimated with enough repeats of each day of the week. On two weeks any model
will learn noise and show confident nonsense — and people plan trips on it.

That is why the forecast has three states, and the user always sees which one:
  collecting   — too little data, no forecast at all;
  preliminary  — there is a forecast, but preliminary, with a wide range;
  ready        — enough data.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from psycopg import AsyncConnection

log = logging.getLogger("avelren.forecast")

# Border-traffic seasonality lives in local time: "Tuesday 09:00" means Kyiv
# Tuesday, not UTC. That is why we both bucket history and look up the future
# slot by Kyiv time. Without this, a DST transition would smear one local time
# across different UTC slots within the lookback window (audit M-7).
KYIV = ZoneInfo("Europe/Kyiv")

# Minimum repeats of each slot (day of week + hour) to show anything at all,
# and how many are needed for a full forecast.
MIN_SAMPLES_PRELIMINARY = 2
MIN_SAMPLES_READY = 8

# How many weeks of history we consider. Distant weeks describe today worse:
# rules, throughput, and flows change.
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
    """Forecast for the coming hours, broken down by hour.

    Returns a range, not a single number: "2–4 days" is more honest than "3 days
    14 hours". The latter creates false precision.
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
        # Deliberately return nothing: showing a forecast on a day's worth of
        # data means lying in a confident tone.
        return result

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    since = now - timedelta(weeks=LOOKBACK_WEEKS)

    rows = await (
        await conn.execute(
            """
            SELECT
                EXTRACT(dow  FROM bucket AT TIME ZONE 'Europe/Kyiv')::int AS dow,
                EXTRACT(hour FROM bucket AT TIME ZONE 'Europe/Kyiv')::int AS hour,
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
        # We look up the slot by KYIV day/hour to match the history bucketing
        # above (AT TIME ZONE 'Europe/Kyiv'). `at` stays an absolute moment
        # (UTC) for the "time" field.
        at_local = at.astimezone(KYIV)
        # Python: Monday = 0, Sunday = 6. PostgreSQL: Sunday = 0, Saturday = 6.
        pg_dow = (at_local.weekday() + 1) % 7
        slot = by_slot.get((pg_dow, at_local.hour))
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
    """Error of the base model on the available history.

    Without this number it is impossible to say whether a future more complex
    model improved anything at all. We measure the mean absolute error in hours.
    """
    # Server-owned lower bound: the evaluation takes the same LOOKBACK_WEEKS as
    # the forecast, not the point's entire history. Otherwise every public call
    # to /forecast/{id}/quality would scan a time-unbounded series (with years of
    # data — a DoS vector, audit #16).
    since = datetime.now(UTC) - timedelta(weeks=LOOKBACK_WEEKS)
    row = await (
        await conn.execute(
            """
            WITH actual AS (
                SELECT bucket, avg_wait_seconds,
                       EXTRACT(dow  FROM bucket AT TIME ZONE 'Europe/Kyiv')::int AS dow,
                       EXTRACT(hour FROM bucket AT TIME ZONE 'Europe/Kyiv')::int AS hour
                FROM observations_hourly
                WHERE checkpoint_id = %s AND bucket >= %s
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
            (checkpoint_id, since),
        )
    ).fetchone()

    return {
        "checkpoint_id": checkpoint_id,
        "method": "seasonal_naive",
        "samples": row["n"] if row else 0,
        "mae_hours": round(float(row["mae_hours"]), 2) if row and row["mae_hours"] else None,
        # Error computed on the same data the model was built on is always
        # optimistic. An honest estimate will appear once there is enough history
        # to separate training and validation.
        "note": "estimate on the same data, optimistic",
    }
