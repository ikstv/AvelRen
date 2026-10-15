"""Notification sender.

A separate service, not part of the collector: history must keep accumulating
even if FCM is down. The collector never waits on pushes.

A notification repeats every 5 minutes until the user removes its subscription
or target. The server, not the app, makes it "endless" — so it survives a
phone reboot and the app being killed.
"""

import asyncio
import logging
import signal
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
from psycopg import AsyncConnection

from . import cancels, fcm
from .config import settings
from .db import get_pool
from .schema_gate import assert_schema_at_least

log = logging.getLogger("avelren.notifier")

KYIV = ZoneInfo("Europe/Kyiv")

_stop = asyncio.Event()


def _request_stop(*_: object) -> None:
    log.info("stop signal received")
    _stop.set()


# Both alert types behave the same, differing only in source and text.
_QUERY = """
    SELECT a.id, a.send_count, d.id AS device_id, d.fcm_token,
           c.title, a.threshold, a.vehicles_at_trigger,
           NULL::timestamptz AS eta, 'threshold' AS kind
    FROM alerts a
    JOIN subscriptions s ON s.id = a.subscription_id
    JOIN devices d ON d.id = s.device_id
    JOIN checkpoints c ON c.id = a.checkpoint_id
    WHERE a.status = 'pending' AND d.fcm_token IS NOT NULL
      AND (a.last_sent_at IS NULL OR a.last_sent_at < now() - %(gap)s::interval)

    UNION ALL

    SELECT a.id, a.send_count, d.id, d.fcm_token,
           c.title, NULL, NULL,
           a.eta_at_trigger, 'eta'
    FROM eta_alerts a
    JOIN eta_targets t ON t.id = a.target_id
    JOIN devices d ON d.id = t.device_id
    JOIN checkpoints c ON c.id = a.checkpoint_id
    WHERE a.status = 'pending' AND d.fcm_token IS NOT NULL
      AND (a.last_sent_at IS NULL OR a.last_sent_at < now() - %(gap)s::interval)
"""


async def _mark_sent(conn: AsyncConnection, kind: str, alert_id: int) -> None:
    table = "alerts" if kind == "threshold" else "eta_alerts"
    # `AND status = 'pending'`: if between SELECT and UPDATE the owner deleted
    # the subscription or target, do not record a successful send for an
    # inactive alert. A same-cycle cancel then supersedes the normal push with
    # the same collapse key (audit A-02, race normal↔delete↔cancel).
    await conn.execute(
        f"UPDATE {table} SET last_sent_at = now(), send_count = send_count + 1 "
        "WHERE id = %s AND status = 'pending'",
        (alert_id,),
    )


async def _disable_device(conn: AsyncConnection, device_id: str, sent_token: str) -> bool:
    """Гасимо лише відправлений токен: під час FCM-запиту він міг оновитися."""
    cursor = await conn.execute(
        "UPDATE devices SET fcm_token = NULL WHERE id = %s AND fcm_token = %s",
        (device_id, sent_token),
    )
    changed = cursor.rowcount > 0
    if changed:
        log.info("device %s disabled: token is dead", device_id)
    return changed


async def run_cycle(client: httpx.AsyncClient) -> int:
    gap = f"{settings.alert_resend_seconds} seconds"

    async with get_pool().connection() as conn:
        rows = await (await conn.execute(_QUERY, {"gap": gap})).fetchall()

        sent = 0
        for r in rows:
            if r["kind"] == "threshold":
                payload = fcm.threshold_payload(
                    r["id"], r["title"], r["threshold"], r["vehicles_at_trigger"]
                )
            else:
                eta_local = r["eta"].astimezone(KYIV).strftime("%d.%m о %H:%M")
                payload = fcm.eta_payload(r["id"], r["title"], eta_local)

            try:
                # collapse_key: repeats of the same alert collapse in FCM,
                # ttl a bit larger than the resend interval — stale ones are not delivered.
                await fcm.send(
                    client,
                    r["fcm_token"],
                    payload,
                    collapse_key=f"{r['kind']}:{r['id']}",
                    ttl_seconds=settings.alert_resend_seconds + 60,
                )
            except fcm.FcmError as exc:
                if exc.dead_token:
                    await _disable_device(conn, r["device_id"], r["fcm_token"])
                else:
                    # Temporary error: the alert stays pending, we will retry.
                    log.warning("alert %s not sent: %s", r["id"], exc)
                continue
            except Exception as exc:
                log.error("failed to send alert %s: %s", r["id"], exc)
                continue

            await _mark_sent(conn, r["kind"], r["id"])
            sent += 1
            log.info("sent %s alert %s (attempt %s)", r["kind"], r["id"], r["send_count"] + 1)

    # Commit legacy writes before taking a second pool connection. In particular,
    # legacy dead-token UPDATE must not hold a device lock across surge delivery.
    from .surge_delivery import send_due

    try:
        async with asyncio.timeout(30):
            sent += await send_due(client, datetime.now(UTC))
    except Exception as exc:
        log.warning("surge phase failed: %s", type(exc).__name__)
    async with get_pool().connection() as conn:
        # Cancels follow normal pushes. A deletion during the normal phase is
        # therefore delivered last with the same collapse key, so the phone's
        # final state is the cancel (audit A-02).
        await _send_cancels(client, conn)
        await cancels.cleanup_closed(conn)

    return sent


async def _send_cancels(client: httpx.AsyncClient, conn: AsyncConnection) -> None:
    for c in await cancels.fetch_open(conn):
        if not c["fcm_token"]:
            # The token is already cleared (dead/logged out) — no one to show it to.
            await cancels.mark_abandoned(conn, c["id"])
            continue
        try:
            await fcm.send(
                client,
                c["fcm_token"],
                fcm.cancel_payload(c["kind"], c["alert_id"]),
                collapse_key=f"{c['kind']}:{c['alert_id']}",
                ttl_seconds=600,
            )
        except fcm.FcmError as exc:
            if exc.dead_token:
                if await _disable_device(conn, c["device_id"], c["fcm_token"]):
                    await cancels.mark_abandoned(conn, c["id"])
                else:
                    # Старий токен більше не поточний; повторюємо за чинною політикою віку.
                    await cancels.record_attempt(conn, c["id"])
            else:
                await cancels.record_attempt(conn, c["id"])
            continue
        except Exception as exc:
            log.error("failed to send cancel %s: %s", c["id"], exc)
            await cancels.record_attempt(conn, c["id"])
            continue

        await cancels.mark_accepted(conn, c["id"])
        log.info("sent cancel %s:%s", c["kind"], c["alert_id"])


async def main() -> None:
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _request_stop)

    pool = get_pool()
    await pool.open(wait=True, timeout=30)
    # Fail-closed schema check (issue #88): the service does not start if the
    # recorded schema version is LOWER than the code's requirement. Placed right
    # after the pool opens — before the first useful work.
    await assert_schema_at_least(pool)
    log.info("sender started, resend every %s s", settings.alert_resend_seconds)

    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        while not _stop.is_set():
            try:
                await run_cycle(client)
            except Exception as exc:
                # No error may stop the sender: otherwise unacknowledged
                # notifications would go silent forever.
                log.error("send cycle failed: %s", exc)

            try:
                await asyncio.wait_for(_stop.wait(), timeout=60)
            except TimeoutError:
                pass

    await pool.close()
    log.info("sender stopped")


if __name__ == "__main__":
    asyncio.run(main())
