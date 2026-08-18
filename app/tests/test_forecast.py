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
