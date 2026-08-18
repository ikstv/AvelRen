"""Verification of the "I want entry at 22:15" feature.

The feature is planned to be paid, so an error here costs not annoyance but money
and trust. The worst scenarios: the notification did not arrive in the window (a
person missed the moment) and the notification arrived in the wrong window (a
person registered for nothing).
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row

from avelren import eta
from avelren.models import WorkloadItem

DSN = os.environ["DATABASE_URL"]


def _target(conn, device_id, checkpoint_id: int, target_at: datetime, tolerance: int = 900) -> int:
    return conn.execute(
        """
        INSERT INTO eta_targets (device_id, checkpoint_id, target_at, tolerance_seconds)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        (device_id, checkpoint_id, target_at, tolerance),
    ).fetchone()["id"]


def _pending(conn, target_id: int) -> int:
    return conn.execute(
        "SELECT count(*) AS n FROM eta_alerts WHERE target_id = %s AND status = 'pending'",
        (target_id,),
    ).fetchone()["n"]


def _observe(checkpoint_id: int, at: datetime, wait_seconds: int, is_paused: bool = False) -> None:
    """Runs a single measurement through the same logic as the collector."""

    async def run() -> None:
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as ac:
            ac.row_factory = dict_row
            item = WorkloadItem(
                id=checkpoint_id,
                title="test",
                for_vehicle_type=1,
                wait_time=wait_seconds,
                is_paused=is_paused,
                vehicle_in_active_queues_counts=100,
            )
            await eta.evaluate(ac, at, [item])

    asyncio.run(run())


def test_eta_formula_matches_source():
    """Check against eCherha: measurement + wait_time = the shown entry time."""
    observed = datetime(2026, 8, 7, 0, 45, 38, tzinfo=UTC)
    result = eta.entry_eta(observed, 336420)  # 3d 21h 27m
    assert result == datetime(2026, 8, 10, 22, 12, 38, tzinfo=UTC)


def test_fires_inside_window(conn, device, checkpoint):
    now = datetime.now(UTC)
    tid = _target(conn, device.device_id, checkpoint, now + timedelta(hours=10))

    _observe(checkpoint, now, wait_seconds=10 * 3600)  # exactly on target
    assert _pending(conn, tid) == 1


def test_fires_at_window_edge(conn, device, checkpoint):
    """14 minutes of divergence with a 15 tolerance is still a hit."""
    now = datetime.now(UTC)
    tid = _target(conn, device.device_id, checkpoint, now + timedelta(hours=10))

    _observe(checkpoint, now, wait_seconds=10 * 3600 + 14 * 60)
    assert _pending(conn, tid) == 1


def test_silent_outside_window(conn, device, checkpoint):
    """16 minutes — already past. A false trigger is worse than silence."""
    now = datetime.now(UTC)
    tid = _target(conn, device.device_id, checkpoint, now + timedelta(hours=10))

    _observe(checkpoint, now, wait_seconds=10 * 3600 + 16 * 60)
    assert _pending(conn, tid) == 0


def test_no_duplicates_while_pending(conn, device, checkpoint):
    """The window lasts many minutes; a per-minute notification would be spam."""
    now = datetime.now(UTC)
    tid = _target(conn, device.device_id, checkpoint, now + timedelta(hours=10))

    for i in range(5):
        _observe(checkpoint, now + timedelta(minutes=i), wait_seconds=10 * 3600)
    assert _pending(conn, tid) == 1


def test_paused_queue_does_not_fire(conn, device, checkpoint):
    """A pause with zero wait is the absence of a forecast, not "entry now"."""
    now = datetime.now(UTC)
    tid = _target(conn, device.device_id, checkpoint, now, tolerance=900)

    _observe(checkpoint, now, wait_seconds=0, is_paused=True)
    assert _pending(conn, tid) == 0


def test_no_refire_after_ack_in_same_window(conn, device, checkpoint, api_client):
    """Regression for the R-05 audit finding.

    Acknowledgement goes through the real endpoint `/eta-alerts/{id}/ack`, not
    through the same two UPDATEs it runs: otherwise the test would check itself
    and would not notice if the endpoint stopped deactivating the target.
    """
    now = datetime.now(UTC)
    tid = _target(conn, device.device_id, checkpoint, now + timedelta(hours=10))

    _observe(checkpoint, now, wait_seconds=10 * 3600)
    assert _pending(conn, tid) == 1

    alert_id = conn.execute(
        "SELECT id FROM eta_alerts WHERE target_id = %s AND status = 'pending'", (tid,)
    ).fetchone()["id"]

    response = api_client.post(
        f"/eta-alerts/{alert_id}/ack", headers=device.headers()
    )
    assert response.status_code == 200
    assert response.json()["status"] == "acknowledged"

    # The endpoint had to both close the alert and take the target off the books.
    assert _pending(conn, tid) == 0
    assert conn.execute(
        "SELECT is_active FROM eta_targets WHERE id = %s", (tid,)
    ).fetchone()["is_active"] is False

    # Subsequent cycles in the same window — silence.
    for i in range(1, 4):
        _observe(checkpoint, now + timedelta(minutes=i), wait_seconds=10 * 3600)
    assert _pending(conn, tid) == 0
