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
from .wait_estimate import measured_wait

log = logging.getLogger("avelren.eta")


def entry_eta(observed_at: datetime, wait_time_seconds: int) -> datetime:
    return observed_at + timedelta(seconds=wait_time_seconds)


async def evaluate(conn: AsyncConnection, at: datetime, items: list[WorkloadItem]) -> int:
    """Alert inside the target window or on a forward crossing of the target."""
    if not items:
        return 0

    # Use the same measured-wait semantics as /workload. Missing estimates
    # never create alerts; an explicitly reported zero is valid unless paused.
    eta_by_checkpoint = {}
    for item in items:
        if item.wait_time is None:
            continue
        estimate = measured_wait(at, item.wait_time, item.wait_time_status, item.is_paused)
        if estimate["entry_eta"] is not None:
            eta_by_checkpoint[item.id] = (estimate["entry_eta"], estimate["seconds"])
    if not eta_by_checkpoint:
        return 0

    rows = await (
        await conn.execute(
            """
            SELECT t.id, t.checkpoint_id, t.target_at, t.tolerance_seconds, t.created_at
            FROM eta_targets t
            WHERE t.is_active AND t.checkpoint_id = ANY(%s)
            """,
            (list(eta_by_checkpoint.keys()),),
        )
    ).fetchall()

    created = 0
    for target in rows:
        eta, wait = eta_by_checkpoint[target["checkpoint_id"]]
        drift = abs((eta - target["target_at"]).total_seconds())
        if drift > target["tolerance_seconds"]:
            if eta < target["target_at"]:
                continue
            # Replay has already stored the current observation. Use only its
            # immediate predecessor after subscription, never an older valid
            # value across a missing estimate or the current row itself.
            previous = await (
                await conn.execute(
                    """
                    SELECT time, wait_time_seconds, wait_time_status, is_paused
                    FROM observations
                    WHERE checkpoint_id = %s AND time < %s AND time >= %s
                    ORDER BY time DESC LIMIT 1
                    """,
                    (target["checkpoint_id"], at, target["created_at"]),
                )
            ).fetchone()
            if previous is None:
                continue
            previous_eta = measured_wait(
                previous["time"], previous["wait_time_seconds"],
                previous["wait_time_status"], previous["is_paused"],
            )["entry_eta"]
            if previous_eta is None or previous_eta >= target["target_at"]:
                continue

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
