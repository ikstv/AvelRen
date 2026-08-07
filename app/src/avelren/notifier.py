"""Розсилач сповіщень.

Окремий сервіс, а не частина збирача: історія має накопичуватись, навіть якщо
FCM лежить. Збирач ніколи не чекає на пуші.

Сповіщення повторюється кожні 5 хвилин, доки користувач не натисне «ОК».
Саме сервер, а не застосунок, робить його «нескінченним» — тому воно переживає
перезавантаження телефона й вбивство застосунку.
"""

import asyncio
import logging
import signal
from zoneinfo import ZoneInfo

import httpx
from psycopg import AsyncConnection

from . import fcm
from .config import settings
from .db import get_pool

log = logging.getLogger("avelren.notifier")

KYIV = ZoneInfo("Europe/Kyiv")

_stop = asyncio.Event()


def _request_stop(*_: object) -> None:
    log.info("отримано сигнал зупинки")
    _stop.set()


# Обидва типи алертів однакові за поведінкою, різняться лише джерелом і текстом.
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
    await conn.execute(
        f"UPDATE {table} SET last_sent_at = now(), send_count = send_count + 1 WHERE id = %s",
        (alert_id,),
    )


async def _disable_device(conn: AsyncConnection, device_id: str) -> None:
    """Мертвий токен: далі слати марно.

    Без цього накопичилися б тисячі мертвих токенів, і ми довбили б FCM
    щоп'ять хвилин за кожен видалений застосунок.
    """
    await conn.execute("UPDATE devices SET fcm_token = NULL WHERE id = %s", (device_id,))
    log.info("пристрій %s відключено: токен мертвий", device_id)


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
                # collapse_key: повтори того самого алерта схлопуються у FCM,
                # ttl трохи більший за інтервал повтору — протухле не доставляється.
                await fcm.send(
                    client,
                    r["fcm_token"],
                    payload,
                    collapse_key=f"{r['kind']}:{r['id']}",
                    ttl_seconds=settings.alert_resend_seconds + 60,
                )
            except fcm.FcmError as exc:
                if exc.dead_token:
                    await _disable_device(conn, r["device_id"])
                else:
                    # Тимчасова помилка: алерт лишається pending, повторимо.
                    log.warning("не надіслано алерт %s: %s", r["id"], exc)
                continue
            except Exception as exc:
                log.error("збій відправки алерта %s: %s", r["id"], exc)
                continue

            await _mark_sent(conn, r["kind"], r["id"])
            sent += 1
            log.info(
                "надіслано %s-алерт %s (спроба %s)", r["kind"], r["id"], r["send_count"] + 1
            )

    return sent


async def main() -> None:
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _request_stop)

    pool = get_pool()
    await pool.open(wait=True, timeout=30)
    log.info("розсилач стартував, повтор кожні %s с", settings.alert_resend_seconds)

    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        while not _stop.is_set():
            try:
                await run_cycle(client)
            except Exception as exc:
                # Жодна помилка не сміє зупинити розсилач: інакше непідтверджені
                # сповіщення замовкнуть назавжди.
                log.error("цикл розсилки впав: %s", exc)

            try:
                await asyncio.wait_for(_stop.wait(), timeout=60)
            except TimeoutError:
                pass

    await pool.close()
    log.info("розсилач зупинено")


if __name__ == "__main__":
    asyncio.run(main())
