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
LONG_ENOUGH = telemetry.SILENT_DEVICE_MIN_HISTORY_DAYS + 1


def _count() -> int:
    async def run() -> int:
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as ac:
            ac.row_factory = dict_row
            return await telemetry.silent_devices(ac)

    return asyncio.run(run())


def _device(conn, token: str | None) -> str:  # noqa: ANN001
    # Randomised like the conftest fixture: fcm_token is UNIQUE, and a fixed
    # literal would collide with a row a killed earlier run left behind.
    if token is not None:
        token = f"{token}-{random.randrange(10**12):012d}"
    row = conn.execute(
        "INSERT INTO devices (fcm_token) VALUES (%s) RETURNING id", (token,)
    ).fetchone()
    return str(row["id"])


def _threshold_alert(  # noqa: ANN001
    conn, device_id, checkpoint, *, sends, days_ago, acked=False, threshold=50
) -> None:
    """One subscription plus one alert on it.

    `threshold` has to vary between calls for the same device and checkpoint:
    subscriptions carry UNIQUE (device_id, checkpoint_id, threshold), so a second
    alert reusing 50 would collide rather than test anything.
    """
    sub = conn.execute(
        "INSERT INTO subscriptions (device_id, checkpoint_id, threshold) "
        "VALUES (%s, %s, %s) RETURNING id",
        (device_id, checkpoint, threshold),
    ).fetchone()["id"]
    # status='expired', not 'pending': alerts_one_pending_per_subscription allows
    # only one open alert per subscription, and the detector deliberately looks at
    # every alert ever sent, not only the open ones.
    conn.execute(
        "INSERT INTO alerts (subscription_id, checkpoint_id, threshold, "
        "vehicles_at_trigger, send_count, status, acknowledged_at, triggered_at) "
        "VALUES (%s, %s, %s, 75, %s, %s, %s, now() - %s * INTERVAL '1 day')",
        (
            sub,
            checkpoint,
            threshold,
            sends,
            "acknowledged" if acked else "expired",
            datetime.now(UTC) if acked else None,
            days_ago,
        ),
    )


def _drop(conn, device_id) -> None:  # noqa: ANN001
    conn.execute("DELETE FROM devices WHERE id = %s", (device_id,))


def test_counts_a_device_that_never_acknowledged_anything(conn, checkpoint) -> None:  # noqa: ANN001
    before = _count()
    dev = _device(conn, "tok-silent")
    try:
        _threshold_alert(conn, dev, checkpoint, sends=ENOUGH, days_ago=LONG_ENOUGH)
        assert _count() == before + 1
    finally:
        _drop(conn, dev)


def test_one_acknowledgement_clears_the_device(conn, checkpoint) -> None:  # noqa: ANN001
    """A single tap is proof a human saw a notification on this phone."""
    before = _count()
    dev = _device(conn, "tok-heard")
    try:
        _threshold_alert(conn, dev, checkpoint, sends=ENOUGH, days_ago=LONG_ENOUGH)
        _threshold_alert(
            conn, dev, checkpoint, sends=1, days_ago=LONG_ENOUGH, acked=True, threshold=60
        )
        assert _count() == before
    finally:
        _drop(conn, dev)


def test_below_the_push_threshold_is_not_silence(conn, checkpoint) -> None:  # noqa: ANN001
    """One ignored alert is a driver who was busy, not a deaf phone."""
    before = _count()
    dev = _device(conn, "tok-few")
    try:
        _threshold_alert(conn, dev, checkpoint, sends=ENOUGH - 1, days_ago=LONG_ENOUGH)
        assert _count() == before
    finally:
        _drop(conn, dev)


def test_a_short_delivery_history_is_not_silence(conn, checkpoint) -> None:  # noqa: ANN001
    """The third condition. Measured from the first alert, not the device row: a
    device we only started trying to reach today has had no chance to answer,
    however old its installation is."""
    before = _count()
    dev = _device(conn, "tok-new")
    try:
        _threshold_alert(conn, dev, checkpoint, sends=ENOUGH * 2, days_ago=0)
        assert _count() == before
    finally:
        _drop(conn, dev)


def test_a_device_without_a_token_is_abandoned_not_silent(conn, checkpoint) -> None:  # noqa: ANN001
    """We are not trying to reach it at all, so it cannot be failing to hear us.
    Those rows are retention (#19), and counting them here would double-report
    every orphaned installation as a delivery fault."""
    before = _count()
    dev = _device(conn, None)
    try:
        _threshold_alert(conn, dev, checkpoint, sends=ENOUGH, days_ago=LONG_ENOUGH)
        assert _count() == before
    finally:
        _drop(conn, dev)


def test_eta_alerts_count_towards_silence_too(conn, checkpoint) -> None:  # noqa: ANN001
    """The second delivery path. A device whose only alerts are ETA ones is just
    as silent, and reading only `alerts` would have missed it."""
    before = _count()
    dev = _device(conn, "tok-eta")
    try:
        target = conn.execute(
            "INSERT INTO eta_targets (device_id, checkpoint_id, target_at) "
            "VALUES (%s, %s, now() + INTERVAL '1 hour') RETURNING id",
            (dev, checkpoint),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO eta_alerts (target_id, checkpoint_id, eta_at_trigger, "
            "wait_seconds_at_trigger, send_count, status, triggered_at) "
            "VALUES (%s, %s, now() + INTERVAL '1 hour', 3600, %s, 'expired', "
            "now() - %s * INTERVAL '1 day')",
            (target, checkpoint, ENOUGH, LONG_ENOUGH),
        )
        assert _count() == before + 1
    finally:
        _drop(conn, dev)


def test_the_query_stays_inside_the_api_roles_column_grants(conn, checkpoint) -> None:  # noqa: ANN001
    """The detector must be runnable by the role that actually serves
    /admin/telemetry.

    `avelren_api` holds COLUMN-level SELECT on `devices` — (id, fcm_token,
    platform, secret_hash, is_admin, last_seen) — so an innocent-looking
    `d.created_at` turns the whole endpoint into 42501 and takes every other
    telemetry block down with it. That is exactly how the first version of this
    failed, and running only as `avelren_admin` would never have shown it.
    """
    dev = _device(conn, "tok-grants")
    try:
        _threshold_alert(conn, dev, checkpoint, sends=ENOUGH, days_ago=LONG_ENOUGH)

        # os.environ[...] deliberately, not .get(): if the role DSN ever stops
        # being provided this must fail loudly rather than skip. A check that
        # silently stops running is the failure mode it exists to catch.
        api_dsn = os.environ["API_DATABASE_URL"]

        async def run() -> int:
            async with await psycopg.AsyncConnection.connect(api_dsn, autocommit=True) as ac:
                ac.row_factory = dict_row
                return await telemetry.silent_devices(ac)

        assert asyncio.run(run()) >= 1
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
