"""Estimated entry time and user targets.

`entry_eta = observation moment + wait_time` — verified against eCherha:
Rava-Ruska, observed 07.08 00:45, wait_time 3d 21h 27m → 10.08 22:12,
exactly what the site shows.

Function #2 is the inverse problem: the user says "I want to enter at 22:15",
and the server watches for when registering right now would yield that result.
"""

import logging
from datetime import datetime, timedelta

from psycopg import AsyncConnection

from .models import WorkloadItem

log = logging.getLogger("avelren.eta")


def entry_eta(observed_at: datetime, wait_time_seconds: int) -> datetime:
    return observed_at + timedelta(seconds=wait_time_seconds)


async def evaluate(conn: AsyncConnection, at: datetime, items: list[WorkloadItem]) -> int:
    """Create alerts for targets whose window the current entry time falls into."""
    if not items:
        return 0

    # A paused queue with zero wait does not mean "entry right now" — it means
    # there is no forecast. Do not wake the user over missing data.
    eta_by_checkpoint = {
        i.id: entry_eta(at, i.wait_time)
        for i in items
        if not (i.is_paused and i.wait_time == 0)
    }
    if not eta_by_checkpoint:
        return 0

    rows = await (
        await conn.execute(
            """
            SELECT t.id, t.checkpoint_id, t.target_at, t.tolerance_seconds
            FROM eta_targets t
            WHERE t.is_active AND t.checkpoint_id = ANY(%s)
            """,
            (list(eta_by_checkpoint.keys()),),
        )
    ).fetchall()

    created = 0
    for target in rows:
        eta = eta_by_checkpoint[target["checkpoint_id"]]
        drift = abs((eta - target["target_at"]).total_seconds())
        if drift > target["tolerance_seconds"]:
            continue

        wait = next(i.wait_time for i in items if i.id == target["checkpoint_id"])
        created += await _fire(conn, target["id"], target["checkpoint_id"], eta, wait)

    if created:
        log.info("ETA alerts created: %s", created)
    return created


async def _fire(
    conn: AsyncConnection, target_id: int, checkpoint_id: int, eta: datetime, wait: int
) -> int:
    cur = await conn.execute(
        """
        INSERT INTO eta_alerts
            (target_id, checkpoint_id, eta_at_trigger, wait_seconds_at_trigger)
        SELECT %s, %s, %s, %s
        WHERE NOT EXISTS (
            SELECT 1 FROM eta_alerts WHERE target_id = %s AND status = 'pending'
        )
        RETURNING id
        """,
        (target_id, checkpoint_id, eta, wait, target_id),
    )
    row = await cur.fetchone()
    if row is None:
        return 0

    log.info("target %s reached: entry %s, alert %s", target_id, eta.isoformat(), row["id"])
    return 1


async def expire_passed(conn: AsyncConnection) -> int:
    """Close targets whose moment has already passed, together with their alerts.

    Notifying "register to enter yesterday" is worse than staying silent.
    """
    cur = await conn.execute(
        """
        WITH stale AS (
            UPDATE eta_targets
            SET is_active = false
            WHERE is_active AND target_at < now()
            RETURNING id
        ),
        expired AS (
            UPDATE eta_alerts a
            SET status = 'expired', expired_at = now()
            WHERE a.status = 'pending' AND a.target_id IN (SELECT id FROM stale)
            RETURNING a.id, a.target_id
        ),
        enqueued AS (
            INSERT INTO notification_cancels (kind, alert_id, device_id)
            SELECT 'eta', e.id, t.device_id
            FROM expired e
            JOIN eta_targets t ON t.id = e.target_id
            ON CONFLICT (kind, alert_id) DO NOTHING
        )
        SELECT id FROM expired
        """
    )
    rows = await cur.fetchall()
    if rows:
        log.info("ETA alerts closed due to passed time: %s", len(rows))
    return len(rows)
