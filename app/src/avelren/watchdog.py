"""Сторож: помічає, що система замовкла, і будить адміністратора.

Найнебезпечніший збій — тихий. Збирач може впасти вночі, і про це ніхто не
дізнається до ранку, а прогалину в історії потім не відновиш: єЧерга минулого
не зберігає.

Тривоги йдуть тим самим каналом, що й звичайні сповіщення — FCM на телефон із
позначкою `is_admin`. Окрема система (пошта, Telegram) означала б ще один
сервіс, ще один секрет і ще одну точку відмови.
"""

import asyncio
import logging
import signal
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from psycopg import AsyncConnection

from . import fcm
from .config import settings
from .db import get_pool

log = logging.getLogger("avelren.watchdog")

CHECK_INTERVAL = 300
# Ребут — справа планова, а не термінова: даємо кілька діб на зручний момент.
REBOOT_GRACE_DAYS = 3
RESEND_INTERVAL = 3600  # тривогу повторюємо раз на годину, а не щоп'ять хвилин

_stop = asyncio.Event()


def _request_stop(*_: object) -> None:
    _stop.set()


async def _checks(conn: AsyncConnection) -> dict[str, str]:
    """Повертає {тип_проблеми: опис}. Порожньо — все гаразд."""
    problems: dict[str, str] = {}

    row = await (
        await conn.execute("SELECT max(time) AS last FROM observations")
    ).fetchone()
    last = row["last"] if row else None

    if last is None:
        problems["no_data"] = "у базі немає спостережень"
    else:
        age = (datetime.now(UTC) - last).total_seconds()
        # Три пропущені цикли поспіль — це вже не мережева ікавка.
        if age > settings.poll_interval_seconds * 3:
            problems["collector_silent"] = f"збирач мовчить {int(age // 60)} хв"

    row = await (
        await conn.execute(
            """
            SELECT count(*) AS failed
            FROM collector_runs
            WHERE time > now() - INTERVAL '30 minutes' AND error IS NOT NULL
            """
        )
    ).fetchone()
    if row and row["failed"] >= 10:
        problems["collector_errors"] = f"{row['failed']} помилок за півгодини"

    row = await (
        await conn.execute(
            "SELECT pg_database_size(current_database()) AS bytes"
        )
    ).fetchone()
    gb = (row["bytes"] if row else 0) / 1024**3
    if gb > 20:
        problems["db_size"] = f"база розрослась до {gb:.1f} ГБ"

    reboot = _reboot_pending()
    if reboot is not None and reboot >= REBOOT_GRACE_DAYS:
        problems["reboot_required"] = (
            f"оновлення чекає перезавантаження {reboot} дн. "
            "Ядро з виправленням встановлене, але працює старе"
        )

    return problems


def _reboot_pending() -> int | None:
    """Скільки діб сервер просить перезавантаження, або None.

    Автоматичний ребут ми свідомо не вмикаємо: сервіс лягав би вночі без
    попередження. Але тоді хтось має помічати цей файл — інакше ядро з
    відомою вразливістю встановлене, а працює старе, і так місяцями.
    """
    flag = Path("/host/run/reboot-required")
    if not flag.exists():
        return None
    age = time.time() - flag.stat().st_mtime
    return int(age // 86400)


async def _open_alerts(conn: AsyncConnection) -> dict[str, dict]:
    rows = await (
        await conn.execute(
            "SELECT id, kind, last_sent_at, send_count FROM health_alerts WHERE resolved_at IS NULL"
        )
    ).fetchall()
    return {r["kind"]: r for r in rows}


async def _admin_tokens(conn: AsyncConnection) -> list[str]:
    rows = await (
        await conn.execute(
            "SELECT fcm_token FROM devices WHERE is_admin AND fcm_token IS NOT NULL"
        )
    ).fetchall()
    return [r["fcm_token"] for r in rows]


async def run_cycle(client: httpx.AsyncClient) -> None:
    async with get_pool().connection() as conn:
        problems = await _checks(conn)
        open_alerts = await _open_alerts(conn)

        # Проблема зникла — закриваємо тривогу й повідомляємо про відновлення.
        for kind, alert in open_alerts.items():
            if kind not in problems:
                await conn.execute(
                    "UPDATE health_alerts SET resolved_at = now() WHERE id = %s", (alert["id"],)
                )
                log.info("проблема %s зникла", kind)
                await _notify(conn, client, "AvelRen відновився", f"{kind}: усе гаразд")

        for kind, detail in problems.items():
            alert = open_alerts.get(kind)

            if alert is None:
                await conn.execute(
                    "INSERT INTO health_alerts (kind, detail) VALUES (%s, %s)", (kind, detail)
                )
                log.error("ПРОБЛЕМА %s: %s", kind, detail)
                if await _notify(conn, client, "AvelRen: проблема", detail):
                    await conn.execute(
                        """
                        UPDATE health_alerts SET last_sent_at = now(), send_count = send_count + 1
                        WHERE kind = %s AND resolved_at IS NULL
                        """,
                        (kind,),
                    )
                continue

            sent = alert["last_sent_at"]
            due = sent is None or (datetime.now(UTC) - sent).total_seconds() > RESEND_INTERVAL
            if due:
                log.warning("проблема %s триває: %s", kind, detail)
                if await _notify(conn, client, "AvelRen: проблема триває", detail):
                    await conn.execute(
                        """
                        UPDATE health_alerts SET last_sent_at = now(), send_count = send_count + 1
                        WHERE id = %s
                        """,
                        (alert["id"],),
                    )


async def _notify(
    conn: AsyncConnection, client: httpx.AsyncClient, title: str, body: str
) -> bool:
    tokens = await _admin_tokens(conn)
    if not tokens:
        log.warning("немає адмін-пристроїв, тривога лише в лозі: %s", body)
        return False

    delivered = False
    for token in tokens:
        try:
            await fcm.send(
                client,
                token,
                {"type": "health", "alert_id": "0", "title": title, "body": body},
            )
            delivered = True
        except Exception as exc:
            log.error("не вдалося надіслати тривогу: %s", exc)
    return delivered


async def main() -> None:
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _request_stop)

    pool = get_pool()
    await pool.open(wait=True, timeout=30)
    log.info("сторож стартував, перевірка кожні %s с", CHECK_INTERVAL)

    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        while not _stop.is_set():
            try:
                await run_cycle(client)
            except Exception as exc:
                # Сторож, який падає від власної помилки, гірший за відсутність
                # сторожа: створює хибне відчуття нагляду.
                log.error("цикл перевірки впав: %s", exc)

            try:
                await asyncio.wait_for(_stop.wait(), timeout=CHECK_INTERVAL)
            except TimeoutError:
                pass

    await pool.close()
    log.info("сторож зупинено")


if __name__ == "__main__":
    asyncio.run(main())
