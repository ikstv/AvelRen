"""Ізольована 12-тижнева перевірка плану seasonal-quality SQL."""

import asyncio
import os
from datetime import timedelta

import psycopg
import pytest
from psycopg.rows import dict_row

from avelren import forecast
from avelren.config import settings

pytestmark = pytest.mark.skipif(
    os.environ.get("AVELREN_PERF_REHEARSAL") != "1",
    reason="run once in the isolated API suite, not again in recursive restore",
)

# Заморожений запит до status-aware зміни (commit b153f64). Він виконується
# тільки на синтетичній БД, щоб порівняти план/час на однакових рядках.
OLD_QUALITY_SQL = """
WITH clean_hourly AS (
    SELECT time_bucket(INTERVAL '1 hour', time) AS bucket,
           avg(wait_time_seconds)::integer AS avg_wait_seconds,
           avg(vehicles_in_queue)::integer AS avg_vehicles
    FROM observations
    WHERE checkpoint_id = %s AND time >= %s AND time < %s
      AND NOT (wait_time_seconds = 0 AND vehicles_in_queue > 0)
    GROUP BY bucket
), actual AS (
    SELECT bucket, avg_wait_seconds, avg_vehicles,
           EXTRACT(dow FROM bucket AT TIME ZONE 'Europe/Kyiv')::int AS dow,
           EXTRACT(hour FROM bucket AT TIME ZONE 'Europe/Kyiv')::int AS hour
    FROM clean_hourly
), training AS (
    SELECT * FROM actual WHERE bucket < %s
), validation AS (
    SELECT * FROM actual WHERE bucket >= %s
), predicted AS (
    SELECT dow, hour,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY avg_wait_seconds) AS p50_wait,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY avg_vehicles) AS p50_vehicles
    FROM training GROUP BY dow, hour
)
SELECT count(*) AS n,
       avg(abs(a.avg_wait_seconds - p.p50_wait)) / 3600.0 AS mae_hours,
       avg(abs(a.avg_vehicles - p.p50_vehicles)) AS mae_vehicles
FROM validation a JOIN predicted p ON p.dow = a.dow AND p.hour = a.hour
"""


class _CapturedQuery(Exception):
    def __init__(self, sql, params):
        self.sql = sql
        self.params = params


class _CaptureConnection:
    async def execute(self, sql, params):
        raise _CapturedQuery(sql, params)


def _current_quality_query(checkpoint_id):
    try:
        asyncio.run(forecast.evaluate(_CaptureConnection(), checkpoint_id))
    except _CapturedQuery as captured:
        return captured.sql, captured.params
    raise AssertionError("evaluate did not issue a quality query")


def test_quality_query_fits_api_timeout_on_twelve_week_minute_history(
    database, conn, checkpoint
):
    sql, params = _current_quality_query(checkpoint)
    assert params[2] - params[1] == timedelta(weeks=forecast.LOOKBACK_WEEKS)

    # One observation per minute for the complete bounded window. Status mix
    # keeps the old and new eligibility predicates meaningfully different.
    conn.execute(
        "INSERT INTO observations "
        "(time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused, wait_time_status) "
        "SELECT t, %s, CASE WHEN mod(extract(minute FROM t)::int, 10) IN (0,1) "
        "THEN 0 ELSE 3600 END, "
        "10 + mod(extract(minute FROM t)::int, 50), false, "
        "CASE WHEN mod(extract(minute FROM t)::int, 10) = 0 THEN 'reported' "
        "WHEN mod(extract(minute FROM t)::int, 10) = 1 THEN 'missing' "
        "ELSE 'legacy_unknown' END "
        "FROM generate_series(%s::timestamptz, %s::timestamptz - interval '1 minute', "
        "interval '1 minute') AS t",
        (checkpoint, params[1], params[2]),
    )
    conn.execute("ANALYZE observations")

    with psycopg.connect(database("api"), autocommit=True, row_factory=dict_row) as api:
        for label, query in (("before", OLD_QUALITY_SQL), ("after", sql)):
            # Only the candidate must satisfy the API's 5-second ceiling;
            # the frozen baseline gets room to yield a comparable plan.
            timeout_ms = 30_000 if label == "before" else settings.api_statement_timeout_ms
            api.execute("SELECT set_config('statement_timeout', %s, false)",
                        (str(timeout_ms),))
            plan = api.execute(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, params
            ).fetchone()["QUERY PLAN"][0]
            elapsed = plan["Execution Time"]
            root = plan["Plan"]
            print(
                f"quality {label}: execution_ms={elapsed:.2f} "
                f"shared_hit={root.get('Shared Hit Blocks', 0)} "
                f"shared_read={root.get('Shared Read Blocks', 0)} "
                f"root_node={root['Node Type']}"
            )
            if label == "after":
                assert elapsed < settings.api_statement_timeout_ms
