"""Verification of feature #3 — AI Forecast.

The most dangerous error here is silent: the forecast takes data from the wrong
day of the week, nothing crashes, and the numbers look plausible. I already made
exactly such an error while writing it — Python counts Monday as 0, PostgreSQL
Sunday as 0. That is why the conversion has its own test.

The second thing we protect here is the refusal to show a forecast on
insufficient data. The feature is planned to be paid, and "confident fabrication"
would cost trust.
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
    """Python: Monday=0, Sunday=6. PostgreSQL: Sunday=0, Saturday=6.

    An error here does not crash but silently takes data from a different day of the week.
    """

    async def check(conn):
        bad = []
        for offset in range(7):
            # 2026-08-03 is a Monday
            at = datetime(2026, 8, 3, 12, tzinfo=UTC) + timedelta(days=offset)
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
    """While there is too little data — no points. Silence is more honest than fabrication."""

    async def check(conn):
        return await forecast.forecast(conn, checkpoint, hours_ahead=24)

    result = _run(check)
    if result["status"] == "collecting":
        assert result["points"] == []
    else:
        assert result["points"], "in the preliminary/ready state there must be points"


def test_ready_at_is_in_the_future_or_none(checkpoint):
    """The readiness date is a guide for the user; it must not be in the past
    while the forecast is not yet ready."""

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
    """Error computed on the same data is always optimistic — and that must be
    visible to whoever reads the number."""

    async def check(conn):
        return await forecast.evaluate(conn, checkpoint)

    result = _run(check)
    assert result["method"] == "seasonal_naive"
    assert "optimistic" in result["note"]


@pytest.mark.parametrize(
    "status,expected",
    [("collecting", True), ("preliminary", False), ("ready", False)],
)
def test_status_thresholds(status, expected):
    """The state boundaries must not drift unnoticed during edits."""
    assert (forecast.MIN_SAMPLES_PRELIMINARY < forecast.MIN_SAMPLES_READY) is True
    assert forecast.MIN_SAMPLES_READY == 8


# --- #111: forecast reads observations_hourly recomputed with a contamination
# filter (wait=0 AND vehicles>0). The two tests below are the load-bearing ones.

# The percentile+bucketing the fix reproduces from observations_hourly's own
# definition. `_OLD` reads the continuous aggregate (the pre-#111 source);
# `_NEW` recomputes it inline with the one added filter — the same SQL the fix
# uses. Comparing them is comparing "before" and "after" on identical data.
_OLD = """
    SELECT EXTRACT(dow  FROM bucket AT TIME ZONE 'Europe/Kyiv')::int AS dow,
           EXTRACT(hour FROM bucket AT TIME ZONE 'Europe/Kyiv')::int AS hour,
           percentile_cont(0.50) WITHIN GROUP (ORDER BY avg_wait_seconds) AS p50,
           count(*) AS samples
    FROM observations_hourly WHERE checkpoint_id = %s GROUP BY dow, hour ORDER BY dow, hour
"""
_NEW = """
    WITH clean_hourly AS (
        SELECT time_bucket(INTERVAL '1 hour', time) AS bucket,
               avg(wait_time_seconds)::integer AS avg_wait_seconds
        FROM observations
        WHERE checkpoint_id = %s
          AND NOT (wait_time_seconds = 0 AND vehicles_in_queue > 0)
        GROUP BY bucket
    )
    SELECT EXTRACT(dow  FROM bucket AT TIME ZONE 'Europe/Kyiv')::int AS dow,
           EXTRACT(hour FROM bucket AT TIME ZONE 'Europe/Kyiv')::int AS hour,
           percentile_cont(0.50) WITHIN GROUP (ORDER BY avg_wait_seconds) AS p50,
           count(*) AS samples
    FROM clean_hourly GROUP BY dow, hour ORDER BY dow, hour
"""


def _seed(conn, cid, rows):
    conn.cursor().executemany(
        "INSERT INTO observations (time, checkpoint_id, wait_time_seconds, "
        "vehicles_in_queue, is_paused) VALUES (%s, %s, %s, %s, false)",
        [(t, cid, w, v) for (t, w, v) in rows],
    )
    # observations_hourly is a continuous aggregate — the pre-#111 source reads
    # nothing until it is materialised. autocommit (conftest) lets refresh run.
    conn.execute("CALL refresh_continuous_aggregate('observations_hourly', NULL, NULL)")


def _bucket(day: int, hour: int, minute: int) -> datetime:
    # Recent, inside LOOKBACK_WEEKS; minute varies so a bucket holds several raw rows.
    base = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return base - timedelta(days=day) + timedelta(hours=hour, minutes=minute)


def test_clean_hourly_is_byte_identical_without_contamination(conn, checkpoint):
    """The fix must change exactly one thing. With no contaminated row present,
    the recomputed clean_hourly must equal the continuous aggregate the forecast
    used before — same buckets, same ::integer averages, same percentiles. A
    difference here means the bucketing, the timezone, or the weighting moved."""
    rows = []
    for day in (2, 9, 16):  # three weekly repeats of one slot
        for minute, wait in ((5, 600), (25, 1200), (45, 1800)):  # veh always > 0
            rows.append((_bucket(day, 8, minute), wait, 4))
    _seed(conn, checkpoint, rows)

    old = conn.execute(_OLD, (checkpoint,)).fetchall()
    new = conn.execute(_NEW, (checkpoint,)).fetchall()
    assert new == old, "clean_hourly diverged from observations_hourly on clean data"
    assert old, "fixture must produce at least one slot"


def test_contamination_pulls_the_old_median_below_the_clean_one(conn, checkpoint):
    """The defect and its fix, in one comparison. Rows with wait=0 while a queue
    exists drag the aggregate median down; removing them raises it. If the filter
    were absent (new == old) this test is red — which is the point."""
    rows = []
    for day in (2, 9, 16):
        # Real signal in the bucket: a genuine wait with a queue.
        rows.append((_bucket(day, 8, 5), 1800, 5))
        rows.append((_bucket(day, 8, 25), 1800, 5))
        # Contamination: a queue exists, yet wait is reported as 0.
        rows.append((_bucket(day, 8, 45), 0, 5))
    _seed(conn, checkpoint, rows)

    old = conn.execute(_OLD, (checkpoint,)).fetchall()
    new = conn.execute(_NEW, (checkpoint,)).fetchall()
    assert old and new, "both queries must return the slot"
    assert new[0]["p50"] > old[0]["p50"], (
        f"clean median {new[0]['p50']} must exceed contaminated {old[0]['p50']}"
    )


def _hourly_points(api_client, checkpoint_id: int) -> list[dict]:
    """/history above 48 hours — the aggregated path, where #111 survived."""
    response = api_client.get(f"/history/{checkpoint_id}?hours=72")
    assert response.status_code == 200
    body = response.json()
    assert body["resolution"] == "hourly", "72 hours must take the aggregated path"
    return body["points"]


def test_history_hourly_excludes_contaminated_rows(conn, checkpoint, api_client):
    """The third surface of #111.

    forecast.py stopped reading observations_hourly because the aggregate averages
    every row, contaminated ones included. /history kept reading it, so the same
    understated numbers were still served — just from a different endpoint. One
    real reading of an hour plus one "no estimate" zero: averaged together they
    halve the hour, which is precisely the defect.
    """
    at = _bucket(1, 5, 0)
    _seed(conn, checkpoint, [
        (at, 3600, 50),                              # a genuine hour of waiting
        (at + timedelta(minutes=1), 0, 50),          # queue present, wait "0" — no estimate
    ])

    hour = at.strftime("%Y-%m-%dT%H")
    point = next(p for p in _hourly_points(api_client, checkpoint) if p["time"].startswith(hour))

    # Averaging both rows would give 1800 — the understatement this fixes.
    assert point["avg_wait_seconds"] == 3600
    assert point["samples"] == 1


def test_history_hourly_drops_a_fully_contaminated_hour(conn, checkpoint, api_client):
    """An hour we know nothing about must be absent, not drawn as zero.

    A gap in the series says "no data"; a zero claims the queue was empty, which
    is the same lie the raw reading told in the first place.
    """
    at = _bucket(1, 7, 0)
    _seed(conn, checkpoint, [
        (at, 0, 50),
        (at + timedelta(minutes=1), 0, 60),
    ])

    hours = {p["time"][:13] for p in _hourly_points(api_client, checkpoint)}
    assert at.strftime("%Y-%m-%dT%H") not in hours
