"""Feature #3: checkpoint workload forecast.

Vehicle counts start from a fresh measurement and use changes in similar
historical situations. Wait-time estimates retain the seasonal median baseline.
The quality endpoint still identifies and evaluates that seasonal baseline;
the candidate count model has a separate rolling backtest (docs/forecast.md).

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

from avelren.queue_model import predict_counts

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

# The collector is scheduled every minute.  A couple of delayed cycles do not
# invalidate weeks of history, but a longer silent interval means that the
# calendar span alone is not enough evidence for a fully-ready forecast.
MAX_READY_COLLECTION_GAP = timedelta(minutes=5)


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

    if status == "ready":
        gap_row = await (
            await conn.execute(
                """
                SELECT max(gap) AS longest_gap
                FROM (
                    SELECT time - lag(time) OVER (ORDER BY time) AS gap
                    FROM collector_runs
                    WHERE time >= %s AND time <= %s
                ) gaps
                """,
                (row["since"], row["until"]),
            )
        ).fetchone()
        # No collector rows is not treated as a synthetic gap: historical or
        # imported observations may predate collector_runs.  A known large
        # gap, however, must keep the forecast explicitly preliminary.
        if (
            gap_row
            and gap_row["longest_gap"]
            and gap_row["longest_gap"] > MAX_READY_COLLECTION_GAP
        ):
            status = "preliminary"

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
        "method": "current_anchored_neighbors_v1",
        "wait_method": "seasonal_naive",
        "points": [],
        "count_points": [],
    }

    if state.status == "collecting":
        # Deliberately return nothing: showing a forecast on a day's worth of
        # data means lying in a confident tone.
        return result

    issued_at = datetime.now(UTC)
    now = issued_at.replace(minute=0, second=0, microsecond=0)
    since = now - timedelta(weeks=LOOKBACK_WEEKS)

    latest = await (
        await conn.execute(
            "SELECT time, vehicles_in_queue FROM observations "
            "WHERE checkpoint_id = %s AND time <= %s ORDER BY time DESC LIMIT 1",
            (checkpoint_id, issued_at),
        )
    ).fetchone()
    if not latest or issued_at - latest["time"] > timedelta(minutes=3):
        result["reason"] = "fresh_measurement_required"
        return result
    hourly = await (
        await conn.execute(
            """
            SELECT time_bucket(INTERVAL '1 hour', time) AS bucket,
                   avg(vehicles_in_queue) AS avg_vehicles
            FROM observations
            WHERE checkpoint_id = %s AND time >= %s AND time < %s
            GROUP BY bucket ORDER BY bucket
            """,
            (checkpoint_id, since, now),
        )
    ).fetchall()
    # A missing wait estimate must not discard a valid vehicle count.
    counts = predict_counts(
        {row["bucket"]: float(row["avg_vehicles"]) for row in hourly},
        issued_at, latest["vehicles_in_queue"],
        [now + timedelta(hours=i) for i in range(1, hours_ahead + 1)],
        current_at=latest["time"],
    )

    rows = await (
        await conn.execute(
            """
            -- clean_hourly is observations_hourly recomputed inline with ONE added
            -- filter: rows where a queue exists yet wait is reported as zero
            -- (wait=0 AND vehicles>0) are physically impossible — a missing source
            -- estimate written as a measured 0 (#111) — and they drag the median
            -- down. Everything else is copied verbatim from the continuous
            -- aggregate's definition (db/migrations/001_init.sql): the same
            -- time_bucket (UTC; Kyiv is applied downstream, not here) and the same
            -- ::integer averages, so on data without contamination this is
            -- byte-identical to reading observations_hourly, and `samples` keeps
            -- meaning weekly hour-repeats (the readiness gate stays intact).
            -- is_paused is deliberately NOT folded in here — that is a separate,
            -- explicit decision (see api.py / eta.py), left open in #111.
            WITH clean_hourly AS (
                SELECT
                    time_bucket(INTERVAL '1 hour', time) AS bucket,
                    avg(wait_time_seconds)::integer AS avg_wait_seconds,
                    avg(vehicles_in_queue)::integer AS avg_vehicles
                FROM observations
                WHERE checkpoint_id = %s AND time >= %s
                  AND NOT (wait_time_seconds = 0 AND vehicles_in_queue > 0)
                GROUP BY bucket
            )
            SELECT
                EXTRACT(dow  FROM bucket AT TIME ZONE 'Europe/Kyiv')::int AS dow,
                EXTRACT(hour FROM bucket AT TIME ZONE 'Europe/Kyiv')::int AS hour,
                percentile_cont(0.25) WITHIN GROUP (ORDER BY avg_wait_seconds) AS p25,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY avg_wait_seconds) AS p50,
                percentile_cont(0.75) WITHIN GROUP (ORDER BY avg_wait_seconds) AS p75,
                percentile_cont(0.25) WITHIN GROUP (ORDER BY avg_vehicles)     AS vehicles_p25,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY avg_vehicles)     AS vehicles_p50,
                percentile_cont(0.75) WITHIN GROUP (ORDER BY avg_vehicles)     AS vehicles_p75,
                count(*) AS samples
            FROM clean_hourly
            GROUP BY dow, hour
            """,
            (checkpoint_id, since),
        )
    ).fetchall()

    by_slot = {(r["dow"], r["hour"]): r for r in rows}
    min_slot_samples = (
        MIN_SAMPLES_READY if state.status == "ready" else MIN_SAMPLES_PRELIMINARY
    )

    for i in range(1, hours_ahead + 1):
        at = now + timedelta(hours=i)
        # We look up the slot by KYIV day/hour to match the history bucketing
        # above (AT TIME ZONE 'Europe/Kyiv'). `at` stays an absolute moment
        # (UTC) for the "time" field.
        at_local = at.astimezone(KYIV)
        if at in counts:
            result["count_points"].append(
                {"time": at, **counts[at], "wait_estimate": None}
            )
        # Python: Monday = 0, Sunday = 6. PostgreSQL: Sunday = 0, Saturday = 6.
        pg_dow = (at_local.weekday() + 1) % 7
        slot = by_slot.get((pg_dow, at_local.hour))
        # A long overall span does not prove that this particular Kyiv weekday
        # and hour has enough observations. Gate every forecast point itself.
        if slot is None or slot["samples"] < min_slot_samples or at not in counts:
            continue

        result["points"].append(
            {
                "time": at,
                "wait_seconds_low": int(slot["p25"]),
                "wait_seconds_expected": int(slot["p50"]),
                "wait_seconds_high": int(slot["p75"]),
                **counts[at],
                "samples": slot["samples"],
            }
        )

    return result


async def evaluate(conn: AsyncConnection, checkpoint_id: int) -> dict:
    """Measure error on the latest full week, excluded from model training."""
    # observations are grouped into UTC clock-hours. Exclude the in-progress
    # hour so repeated quality checks do not score a partial bucket as if it
    # were a complete observation.
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    since = now - timedelta(weeks=LOOKBACK_WEEKS)
    validation_since = now - timedelta(days=7)
    row = await (
        await conn.execute(
            """
            -- Same clean_hourly and #111 contamination filter as forecast().
            -- The latest seven days are validation only; older rows in the bounded
            -- window train the seasonal median, so no observation predicts itself.
            WITH clean_hourly AS (
                SELECT
                    time_bucket(INTERVAL '1 hour', time) AS bucket,
                    avg(wait_time_seconds)::integer AS avg_wait_seconds,
                    avg(vehicles_in_queue)::integer AS avg_vehicles
                FROM observations
                WHERE checkpoint_id = %s AND time >= %s AND time < %s
                  AND NOT (wait_time_seconds = 0 AND vehicles_in_queue > 0)
                GROUP BY bucket
            ),
            actual AS (
                SELECT bucket, avg_wait_seconds, avg_vehicles,
                       EXTRACT(dow  FROM bucket AT TIME ZONE 'Europe/Kyiv')::int AS dow,
                       EXTRACT(hour FROM bucket AT TIME ZONE 'Europe/Kyiv')::int AS hour
                FROM clean_hourly
            ),
            training AS (
                SELECT * FROM actual WHERE bucket < %s
            ),
            validation AS (
                SELECT * FROM actual WHERE bucket >= %s
            ),
            predicted AS (
                SELECT dow, hour,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY avg_wait_seconds) AS p50_wait,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY avg_vehicles) AS p50_vehicles
                FROM training GROUP BY dow, hour
            )
            SELECT count(*) AS n,
                   avg(abs(a.avg_wait_seconds - p.p50_wait)) / 3600.0 AS mae_hours,
                   avg(abs(a.avg_vehicles - p.p50_vehicles)) AS mae_vehicles
            FROM validation a JOIN predicted p ON p.dow = a.dow AND p.hour = a.hour
            """,
            (checkpoint_id, since, now, validation_since, validation_since),
        )
    ).fetchone()

    return {
        "checkpoint_id": checkpoint_id,
        "method": "seasonal_naive",
        "samples": row["n"] if row else 0,
        "mae_hours": round(float(row["mae_hours"]), 2)
        if row and row["mae_hours"] is not None
        else None,
        "mae_vehicles": round(float(row["mae_vehicles"]), 2)
        if row and row.get("mae_vehicles") is not None
        else None,
        "validation_days": 7,
        "note": "latest 7 days held out; trained only on earlier observations",
    }
