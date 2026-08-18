"""Verification of the threshold logic on synthetic data.

The costliest error here is spam: a notification that wakes a person every minute
gets uninstalled along with the app. That is why small fluctuations at the
boundary have their own test.

The test creates the data itself (see `conftest.py`): no ready reference list and
no prior collector runs are needed.

Run (a live test DB is required):
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
    """Runs a sequence of queue values through the same logic as the collector."""

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
    """49->51->49->51->49->51 must yield exactly one alert, not three."""
    sub = _subscription(conn, device.device_id, checkpoint)
    _feed(checkpoint, [49, 51, 49, 51, 49, 51])
    assert _pending(conn, sub) == 1


def test_rearm_requires_margin(conn, device, checkpoint):
    """After acknowledgement, the threshold 50 rearms only below 45."""
    sub = _subscription(conn, device.device_id, checkpoint)
    _feed(checkpoint, [49, 51])
    conn.execute(
        "UPDATE alerts SET status = 'acknowledged', acknowledged_at = now() "
        "WHERE subscription_id = %s",
        (sub,),
    )

    _feed(checkpoint, [46, 60])  # 46 > 45 — no rearm happened
    assert _pending(conn, sub) == 0

    _feed(checkpoint, [44, 51])  # 44 < 45 — rearm and a new trigger
    assert _pending(conn, sub) == 1


def test_no_alert_below_threshold(conn, device, checkpoint):
    sub = _subscription(conn, device.device_id, checkpoint)
    _feed(checkpoint, [10, 20, 49])
    assert _pending(conn, sub) == 0


def test_exact_threshold_fires(conn, device, checkpoint):
    """Exactly 50 is a trigger, not "almost"."""
    sub = _subscription(conn, device.device_id, checkpoint)
    _feed(checkpoint, [49, 50])
    assert _pending(conn, sub) == 1


def test_jump_over_threshold_fires(conn, device, checkpoint):
    """The queue changes by 2 vehicles at a time too, so 49->51 must not slip past."""
    sub = _subscription(conn, device.device_id, checkpoint)
    _feed(checkpoint, [49, 51])
    assert _pending(conn, sub) == 1
