"""#117 gap 4: the server had no signal that a device is silent.

`send_count` says FCM accepted the message. It does not say a driver saw it —
between the two sit a revoked POST_NOTIFICATIONS and, for this app's actual
audience, a MIUI/Xiaomi device that kills the background with the permission
granted. In both the server sees unbroken success while the app is a no-op.

The issue planned to detect this with a delivery ack in a new `devices.last_ack_at`,
which means a migration, which is blocked behind #15 (prod is pinned at 009 and
the startup gate derives its requirement from the schema contract). It is not
needed: `alerts.acknowledged_at` already records the driver tapping "OK".

Every assertion here is on the DELTA, not the absolute count: the suite shares a
database, and a test that assumed it was alone would pass or fail depending on
what ran before it.
"""

import asyncio
import os
import random
from datetime import UTC, datetime

import psycopg
from psycopg.rows import dict_row

from avelren import telemetry

DSN = os.environ["DATABASE_URL"]

ENOUGH = telemetry.SILENT_DEVICE_MIN_PUSHES
OLD_ENOUGH = telemetry.SILENT_DEVICE_MIN_AGE_DAYS + 1


def _count() -> int:
    async def run() -> int:
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as ac:
            ac.row_factory = dict_row
            return await telemetry.silent_devices(ac)

    return asyncio.run(run())


def _device(conn, *, age_days: int, token: str | None) -> str:  # noqa: ANN001
    # Randomised like the conftest fixture: fcm_token is UNIQUE, and a fixed
    # literal would collide with a row a killed earlier run left behind.
    if token is not None:
        token = f"{token}-{random.randrange(10**12):012d}"
    row = conn.execute(
        "INSERT INTO devices (fcm_token, created_at) "
        "VALUES (%s, now() - %s * INTERVAL '1 day') RETURNING id",
        (token, age_days),
    ).fetchone()
    return str(row["id"])


def _threshold_alert(conn, device_id, checkpoint, *, sends, acked) -> None:  # noqa: ANN001
    sub = conn.execute(
        "INSERT INTO subscriptions (device_id, checkpoint_id, threshold) "
        "VALUES (%s, %s, 50) RETURNING id",
        (device_id, checkpoint),
    ).fetchone()["id"]
    # status='expired', not 'pending': alerts_one_pending_per_subscription allows
    # only one open alert per subscription, and the detector deliberately looks at
    # every alert ever sent, not only the open ones.
    conn.execute(
        "INSERT INTO alerts (subscription_id, checkpoint_id, threshold, "
        "vehicles_at_trigger, send_count, status, acknowledged_at) "
        "VALUES (%s, %s, 50, 75, %s, %s, %s)",
        (
            sub,
            checkpoint,
            sends,
            "acknowledged" if acked else "expired",
            datetime.now(UTC) if acked else None,
        ),
    )


def _drop(conn, device_id) -> None:  # noqa: ANN001
    conn.execute("DELETE FROM devices WHERE id = %s", (device_id,))


def test_counts_a_device_that_never_acknowledged_anything(conn, checkpoint) -> None:  # noqa: ANN001
    before = _count()
    dev = _device(conn, age_days=OLD_ENOUGH, token="tok-silent")
    try:
        _threshold_alert(conn, dev, checkpoint, sends=ENOUGH, acked=False)
        assert _count() == before + 1
    finally:
        _drop(conn, dev)


def test_one_acknowledgement_clears_the_device(conn, checkpoint) -> None:  # noqa: ANN001
    """A single tap is proof a human saw a notification on this phone."""
    before = _count()
    dev = _device(conn, age_days=OLD_ENOUGH, token="tok-heard")
    try:
        _threshold_alert(conn, dev, checkpoint, sends=ENOUGH, acked=False)
        _threshold_alert(conn, dev, checkpoint, sends=1, acked=True)
        assert _count() == before
    finally:
        _drop(conn, dev)


def test_below_the_push_threshold_is_not_silence(conn, checkpoint) -> None:  # noqa: ANN001
    """One ignored alert is a driver who was busy, not a deaf phone."""
    before = _count()
    dev = _device(conn, age_days=OLD_ENOUGH, token="tok-few")
    try:
        _threshold_alert(conn, dev, checkpoint, sends=ENOUGH - 1, acked=False)
        assert _count() == before
    finally:
        _drop(conn, dev)


def test_a_new_installation_is_not_silent(conn, checkpoint) -> None:  # noqa: ANN001
    """The third condition. Without it the detector fires on newcomers: a fresh
    row has acknowledged nothing because it is new, not because it is deaf."""
    before = _count()
    dev = _device(conn, age_days=0, token="tok-new")
    try:
        _threshold_alert(conn, dev, checkpoint, sends=ENOUGH * 2, acked=False)
        assert _count() == before
    finally:
        _drop(conn, dev)


def test_a_device_without_a_token_is_abandoned_not_silent(conn, checkpoint) -> None:  # noqa: ANN001
    """We are not trying to reach it at all, so it cannot be failing to hear us.
    Those rows are retention (#19), and counting them here would double-report
    every orphaned installation as a delivery fault."""
    before = _count()
    dev = _device(conn, age_days=OLD_ENOUGH, token=None)
    try:
        _threshold_alert(conn, dev, checkpoint, sends=ENOUGH, acked=False)
        assert _count() == before
    finally:
        _drop(conn, dev)


def test_eta_alerts_count_towards_silence_too(conn, checkpoint) -> None:  # noqa: ANN001
    """The second delivery path. A device whose only alerts are ETA ones is just
    as silent, and reading only `alerts` would have missed it."""
    before = _count()
    dev = _device(conn, age_days=OLD_ENOUGH, token="tok-eta")
    try:
        target = conn.execute(
            "INSERT INTO eta_targets (device_id, checkpoint_id, target_at) "
            "VALUES (%s, %s, now() + INTERVAL '1 hour') RETURNING id",
            (dev, checkpoint),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO eta_alerts (target_id, checkpoint_id, eta_at_trigger, "
            "wait_seconds_at_trigger, send_count, status) "
            "VALUES (%s, %s, now() + INTERVAL '1 hour', 3600, %s, 'expired')",
            (target, checkpoint, ENOUGH),
        )
        assert _count() == before + 1
    finally:
        _drop(conn, dev)


def test_pipeline_exposes_the_count_for_admin_telemetry(conn) -> None:  # noqa: ANN001
    """The exact number stays admin-only, like admins_with_token: /health carries
    words, not counts, so curling it cannot reveal the size of the fleet."""

    async def run() -> dict:
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as ac:
            ac.row_factory = dict_row
            return await telemetry.pipeline(ac)

    data = asyncio.run(run())
    assert isinstance(data["devices_silent"], int)
    assert data["devices_silent"] <= data["devices"]
