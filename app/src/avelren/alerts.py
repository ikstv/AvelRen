"""Detecting a queue crossing a threshold.

Fires only on growth: "the queue grew to 50" is news, "fell to 50" is not.

The state lives on the server, not the phone, so a notification survives a
device reboot and the app being killed.
"""

import logging

from psycopg import AsyncConnection

from .config import settings
from .models import WorkloadItem

log = logging.getLogger("avelren.alerts")

THRESHOLDS = [50, 100, 150, 200, 250, 300, 350, 400, 450, 500]


async def evaluate(conn: AsyncConnection, items: list[WorkloadItem]) -> int:
    """Create alerts for subscriptions whose threshold was just crossed upward.

    Called right after observations are written: the values are already in
    memory. Returns the number of alerts created.
    """
    if not items:
        return 0

    current = {i.id: i.vehicles_in_queue for i in items}

    rows = await (
        await conn.execute(
            """
            SELECT s.id, s.checkpoint_id, s.threshold,
                   COALESCE(st.is_armed, true) AS is_armed
            FROM subscriptions s
            LEFT JOIN subscription_state st ON st.subscription_id = s.id
            WHERE s.is_active AND s.checkpoint_id = ANY(%s)
            """,
            (list(current.keys()),),
        )
    ).fetchall()

    created = 0
    for sub in rows:
        vehicles = current[sub["checkpoint_id"]]
        threshold = sub["threshold"]

        if vehicles < threshold:
            # Queue below the threshold — re-arm, but only with a margin,
            # otherwise small fluctuations at the edge would wake every minute.
            if not sub["is_armed"] and vehicles < threshold * settings.rearm_factor:
                await _rearm(conn, sub["id"])
            continue

        if not sub["is_armed"]:
            continue

        created += await _fire(conn, sub["id"], sub["checkpoint_id"], threshold, vehicles)

    if created:
        log.info("alerts created: %s", created)
    return created


async def _fire(
    conn: AsyncConnection, subscription_id: int, checkpoint_id: int, threshold: int, vehicles: int
) -> int:
    # Partial unique indexes do not work with ON CONFLICT without an explicit
    # predicate, so we check for an open alert directly.
    cur = await conn.execute(
        """
        INSERT INTO alerts
            (subscription_id, checkpoint_id, threshold, vehicles_at_trigger)
        SELECT %s, %s, %s, %s
        WHERE NOT EXISTS (
            SELECT 1 FROM alerts
            WHERE subscription_id = %s AND status = 'pending'
        )
        RETURNING id
        """,
        (subscription_id, checkpoint_id, threshold, vehicles, subscription_id),
    )
    row = await cur.fetchone()
    if row is None:
        return 0

    await conn.execute(
        """
        INSERT INTO subscription_state (subscription_id, is_armed, disarmed_at)
        VALUES (%s, false, now())
        ON CONFLICT (subscription_id) DO UPDATE SET
            is_armed = false, disarmed_at = now()
        """,
        (subscription_id,),
    )
    log.info(
        "threshold %s crossed at checkpoint %s: %s vehicles, alert %s",
        threshold,
        checkpoint_id,
        vehicles,
        row["id"],
    )
    return 1


async def _rearm(conn: AsyncConnection, subscription_id: int) -> None:
    await conn.execute(
        """
        UPDATE subscription_state
        SET is_armed = true, rearmed_at = now()
        WHERE subscription_id = %s AND NOT is_armed
        """,
        (subscription_id,),
    )


async def expire_stale(conn: AsyncConnection) -> int:
    """Close unacknowledged alerts whose queue has already fallen below the threshold.

    Waking a user with news of a queue that no longer exists is harm, not help.

    The pending → expired transition and the cancel enqueue go in one
    transaction (CTE): otherwise a process crash between them would leave the
    phone with an ongoing notification the server has already closed (audit
    A-02). The cancel is enqueued regardless of send_count — see cancels /
    migration 008.
    """
    cur = await conn.execute(
        """
        WITH expired AS (
            UPDATE alerts a
            SET status = 'expired', expired_at = now()
            FROM (
                SELECT DISTINCT ON (checkpoint_id) checkpoint_id, vehicles_in_queue
                FROM observations
                WHERE time > now() - INTERVAL '10 minutes'
                ORDER BY checkpoint_id, time DESC
            ) o
            WHERE a.status = 'pending'
              AND a.checkpoint_id = o.checkpoint_id
              AND o.vehicles_in_queue < a.threshold
            RETURNING a.id, a.subscription_id
        ),
        enqueued AS (
            INSERT INTO notification_cancels (kind, alert_id, device_id)
            SELECT 'threshold', e.id, s.device_id
            FROM expired e
            JOIN subscriptions s ON s.id = e.subscription_id
            ON CONFLICT (kind, alert_id) DO NOTHING
        )
        SELECT id FROM expired
        """
    )
    rows = await cur.fetchall()
    if rows:
        log.info("alerts closed because the queue fell: %s", len(rows))
    return len(rows)
