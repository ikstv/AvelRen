"""Cancelling already-shown notifications (A-02).

The server is the single source of truth about an alert's activity. When an
alert leaves `pending` not through a local ACK (expire or cascade delete), the
phone must be told that the ongoing notification should be removed. Two layers:

  1. cancel-push via FCM (the fast path, here);
  2. reconciliation on the client at foreground (a convergence guarantee when
     the push was lost — separately, via `active_alert_keys`).

Enqueueing cancels happens IN THE SAME TRANSACTION as the state transition —
done by the CTEs in `alerts.expire_stale`/`eta.expire_passed` and the delete
endpoints. Here — only sending from the outbox, its lifecycle, and the
canonical active state.
"""

import logging

from psycopg import AsyncConnection

log = logging.getLogger("avelren.cancels")

# How long we try to deliver a cancel before giving up. Age-based, not an
# attempt counter: the notifier runs once a minute, so 5 attempts = ~5 min, and
# a short FCM outage would leave the ongoing notification hanging for a long
# time. An hour of retries covers a typical FCM failure; after it, reconciliation
# at the next foreground is the backstop (audit A-02 / B3).
ABANDON_AFTER = "1 hour"


async def fetch_open(conn: AsyncConnection) -> list[dict]:
    """Not-yet-closed cancels together with the device's current token."""
    return await (
        await conn.execute(
            """
            SELECT nc.id, nc.kind, nc.alert_id, nc.attempt_count,
                   nc.device_id, d.fcm_token
            FROM notification_cancels nc
            JOIN devices d ON d.id = nc.device_id
            WHERE nc.accepted_at IS NULL AND nc.abandoned_at IS NULL
            ORDER BY nc.created_at
            """
        )
    ).fetchall()


async def mark_accepted(conn: AsyncConnection, cancel_id: int) -> None:
    await conn.execute(
        "UPDATE notification_cancels SET accepted_at = now() WHERE id = %s",
        (cancel_id,),
    )


async def record_attempt(conn: AsyncConnection, cancel_id: int) -> None:
    """Records a failed attempt; we give up only when the record is older than ABANDON_AFTER.

    attempt_count stays for diagnostics, but the abandon decision is by the age
    of created_at, not by the number of attempts (see ABANDON_AFTER).
    """
    await conn.execute(
        f"""
        UPDATE notification_cancels
        SET attempt_count = attempt_count + 1,
            last_attempt_at = now(),
            abandoned_at = CASE
                WHEN created_at < now() - INTERVAL '{ABANDON_AFTER}' THEN now()
                ELSE NULL
            END
        WHERE id = %s
        """,
        (cancel_id,),
    )


async def mark_abandoned(conn: AsyncConnection, cancel_id: int) -> None:
    """Give up immediately (dead token: there is no one on the device to show it to)."""
    await conn.execute(
        "UPDATE notification_cancels SET abandoned_at = now(), last_attempt_at = now() "
        "WHERE id = %s",
        (cancel_id,),
    )


async def cleanup_closed(conn: AsyncConnection) -> None:
    """Removes closed records older than a day: history is not needed here."""
    await conn.execute(
        """
        DELETE FROM notification_cancels
        WHERE (accepted_at IS NOT NULL OR abandoned_at IS NOT NULL)
          AND created_at < now() - INTERVAL '1 day'
        """
    )


async def active_alert_keys(conn: AsyncConnection, device_id: str) -> dict[str, list[int]]:
    """Canonical list of the device's active (pending) alerts — for
    reconciliation. Deliberately WITHOUT a send_count filter: the truth is the
    status, not the history of a successful counter write. Empty lists — all
    closed.
    """
    threshold = await (
        await conn.execute(
            """
            SELECT a.id
            FROM alerts a
            JOIN subscriptions s ON s.id = a.subscription_id
            WHERE s.device_id = %s AND a.status = 'pending'
            ORDER BY a.id
            """,
            (device_id,),
        )
    ).fetchall()
    eta = await (
        await conn.execute(
            """
            SELECT a.id
            FROM eta_alerts a
            JOIN eta_targets t ON t.id = a.target_id
            WHERE t.device_id = %s AND a.status = 'pending'
            ORDER BY a.id
            """,
            (device_id,),
        )
    ).fetchall()
    return {
        "threshold": [r["id"] for r in threshold],
        "eta": [r["id"] for r in eta],
    }
