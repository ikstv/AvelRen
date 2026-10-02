"""Стійка доставка: reserve/commit перед FCM, idempotent retry та cancel."""

import logging
from datetime import UTC, datetime, timedelta

import httpx
from psycopg.rows import dict_row

from . import fcm
from .config import settings
from .db import get_pool
from .schema_gate import SchemaTooOldError, assert_surge_schema
from .surge_text import surge_body

log = logging.getLogger("avelren.surge_delivery")
RETRY_SECONDS = 60
REMINDER_SECONDS = 300


def utc_now() -> datetime:
    return datetime.now(UTC)


def delivery_payload(row: dict) -> dict[str, str]:
    return {
        "type": row["kind"],
        "surge_alert_id": str(row["alert_id"]),
        "attempt_id": str(row["attempt_id"]),
        "attempt_ordinal": str(row["ordinal"]),
        "attempt_created_at": row["created_at"].isoformat(),
        "expires_at": row["expires_at"].isoformat(),
        "checkpoint_id": str(row["checkpoint_id"]),
        "title": row["title"],
        "body": surge_body(row["kind"], row["checkpoint_id"], row["title"]),
        "experimental": "true",
    }


def delivery_ttl(row: dict, now: datetime) -> int:
    return max(0, min(360, int((row["expires_at"] - now).total_seconds())))


async def reserve_attempt(conn, alert_id: int, now: datetime) -> dict | None:
    async with conn.transaction():
        cur = conn.cursor(row_factory=dict_row)
        await cur.execute(
            """
            SELECT a.id AS alert_id,a.device_id,a.next_attempt_at,e.kind,e.checkpoint_id,
                e.expires_at,c.title,d.fcm_token FROM surge_alerts a
            JOIN surge_events e ON e.id=a.event_id JOIN checkpoints c ON c.id=e.checkpoint_id
            JOIN devices d ON d.id=a.device_id
            WHERE a.id=%s AND a.status='pending' AND e.closed_at IS NULL AND e.expires_at>%s
                AND d.fcm_token IS NOT NULL AND 'surge_v1'=ANY(d.notification_capabilities)
            FOR UPDATE OF a
        """,
            (alert_id, now),
        )
        alert = await cur.fetchone()
        if not alert or delivery_ttl(alert, now) == 0:
            return None
        await cur.execute(
            (
                "SELECT * FROM surge_delivery_attempts WHERE alert_id=%s ORDER BY "
                "ordinal DESC LIMIT 1 FOR UPDATE"
            ),
            (alert_id,),
        )
        last = await cur.fetchone()
        retry = False
        if last and last["accepted_at"] is None and last["abandoned_at"] is None:
            # Unknown response retries SAME ID inside the scheduled interval.
            # At next reminder we supersede unknown, never label it accepted.
            if now < last["created_at"] + timedelta(seconds=REMINDER_SECONDS):
                if last["last_attempt_at"] and now - last["last_attempt_at"] < timedelta(
                    seconds=RETRY_SECONDS
                ):
                    return None
                retry = True
            else:
                await cur.execute(
                    "UPDATE surge_delivery_attempts SET abandoned_at=%s WHERE id=%s",
                    (now, last["id"]),
                )
        elif now < alert["next_attempt_at"]:
            return None
        if retry:
            await cur.execute(
                (
                    "UPDATE surge_delivery_attempts SET last_attempt_at=%s,"
                    "attempt_count=attempt_count+1 WHERE id=%s RETURNING *"
                ),
                (now, last["id"]),
            )
        else:
            ordinal = last["ordinal"] + 1 if last else 1
            await cur.execute(
                """
                INSERT INTO surge_delivery_attempts
                    (alert_id,ordinal,created_at,last_attempt_at,attempt_count)
                VALUES(%s,%s,%s,%s,1) RETURNING *
            """,
                (alert_id, ordinal, now, now),
            )
            await conn.execute(
                "UPDATE surge_alerts SET next_attempt_at=%s WHERE id=%s",
                (now + timedelta(seconds=REMINDER_SECONDS), alert_id),
            )
        attempt = await cur.fetchone()
        return {**alert, **attempt, "alert_id": alert_id}


async def accept_attempt(conn, attempt: dict, now: datetime) -> None:
    async with conn.transaction():
        cur = conn.cursor(row_factory=dict_row)
        await cur.execute(
            """
            SELECT a.id,a.device_id,a.status,e.kind,e.closed_at,e.expires_at
            FROM surge_alerts a JOIN surge_events e ON e.id=a.event_id
            WHERE a.id=%s FOR UPDATE OF a
        """,
            (attempt["alert_id"],),
        )
        alert = await cur.fetchone()
        if not alert:
            return
        await conn.execute(
            """
            UPDATE surge_delivery_attempts SET accepted_at=%s,abandoned_at=NULL
            WHERE attempt_id=%s AND alert_id=%s
        """,
            (now, attempt["attempt_id"], attempt["alert_id"]),
        )
        if (
            alert["status"] == "pending"
            and alert["closed_at"] is None
            and alert["expires_at"] > now
        ):
            # Late callback for superseded ordinal must not delay a newer reminder.
            await conn.execute(
                """
                UPDATE surge_alerts SET next_attempt_at=%s WHERE id=%s
                  AND NOT EXISTS(SELECT 1 FROM surge_delivery_attempts
                                 WHERE alert_id=%s AND ordinal>%s)
            """,
                (
                    now + timedelta(seconds=REMINDER_SECONDS),
                    alert["id"],
                    alert["id"],
                    attempt["ordinal"],
                ),
            )
            return
        await conn.execute(
            "UPDATE surge_alerts SET status='expired' WHERE id=%s AND status='pending'",
            (alert["id"],),
        )
        # An already-delivered cancel can race a slow normal FCM response.
        # Queue it again after that response; Android tombstones also guard ordering.
        await conn.execute(
            """
            INSERT INTO notification_cancels(kind,alert_id,device_id,created_at)
            VALUES(%s,%s,%s,%s) ON CONFLICT(kind,alert_id) DO UPDATE
            SET accepted_at=NULL,abandoned_at=NULL,attempt_count=0,last_attempt_at=NULL
        """,
            (alert["kind"], alert["id"], alert["device_id"], now),
        )


async def _still_active(conn, attempt: dict, now: datetime) -> bool:
    cur = conn.cursor(row_factory=dict_row)
    await cur.execute(
        """
        SELECT 1 FROM surge_alerts a JOIN surge_events e ON e.id=a.event_id
        JOIN devices d ON d.id=a.device_id
        WHERE a.id=%s AND a.status='pending' AND e.closed_at IS NULL AND e.expires_at>%s
          AND d.fcm_token=%s AND 'surge_v1'=ANY(d.notification_capabilities)
    """,
        (attempt["alert_id"], now, attempt["fcm_token"]),
    )
    return await cur.fetchone() is not None


async def send_due(client: httpx.AsyncClient, now: datetime) -> int:
    if not settings.surge_enabled:
        return 0
    pool = get_pool()
    async with pool.connection() as conn:
        try:
            await assert_surge_schema(conn)
        except SchemaTooOldError:
            log.warning("surge schema unavailable; legacy delivery continues")
            return 0
        cur = conn.cursor(row_factory=dict_row)
        await cur.execute(
            """
            SELECT a.id FROM surge_alerts a JOIN surge_events e ON e.id=a.event_id
            JOIN devices d ON d.id=a.device_id
            WHERE a.status='pending' AND e.closed_at IS NULL AND e.expires_at>%s
              AND d.fcm_token IS NOT NULL AND 'surge_v1'=ANY(d.notification_capabilities)
              AND (a.next_attempt_at<=%s OR EXISTS (
                  SELECT 1 FROM surge_delivery_attempts t WHERE t.alert_id=a.id
                    AND t.accepted_at IS NULL AND t.abandoned_at IS NULL
                    AND t.last_attempt_at<=%s))
            ORDER BY a.next_attempt_at,a.id LIMIT 50
        """,
            (now, now, now - timedelta(seconds=RETRY_SECONDS)),
        )
        ids = [r["id"] for r in await cur.fetchall()]
    sent = 0
    for alert_id in ids:
        async with pool.connection() as conn:
            attempt = await reserve_attempt(conn, alert_id, now)
        if attempt is None:
            continue
        current = utc_now()
        async with pool.connection() as conn:
            if not await _still_active(conn, attempt, current):
                continue
        ttl = delivery_ttl(attempt, current)
        if ttl == 0:
            continue
        try:
            await fcm.send(
                client,
                attempt["fcm_token"],
                delivery_payload(attempt),
                collapse_key=f"{attempt['kind']}:{attempt['alert_id']}",
                ttl_seconds=ttl,
            )
        except fcm.FcmError as exc:
            if exc.dead_token:
                async with pool.connection() as conn:
                    await conn.execute(
                        "UPDATE devices SET fcm_token=NULL WHERE id=%s AND fcm_token=%s",
                        (attempt["device_id"], attempt["fcm_token"]),
                    )
                    await conn.execute(
                        "UPDATE surge_delivery_attempts SET abandoned_at=%s WHERE attempt_id=%s",
                        (utc_now(), attempt["attempt_id"]),
                    )
            log.warning("surge alert=%s FCM status=%s", alert_id, exc.status)
            continue
        except Exception as exc:
            log.warning("surge alert=%s error=%s", alert_id, type(exc).__name__)
            continue
        async with pool.connection() as conn:
            await accept_attempt(conn, attempt, utc_now())
        sent += 1
    return sent
