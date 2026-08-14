"""Сторож: помічає, що система замовкла, і будить адміністратора.

Найнебезпечніший збій — тихий. Збирач може впасти вночі, і про це ніхто не
дізнається до ранку, а прогалину в історії потім не відновиш: єЧерга минулого
не зберігає.

Тривоги йдуть тим самим каналом, що й звичайні сповіщення — FCM на телефон із
позначкою `is_admin`. Окрема система (пошта, Telegram) означала б ще один
сервіс, ще один секрет і ще одну точку відмови.
"""

import asyncio
import json
import logging
import os
import signal
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
# Якщо recovery так і не доставлено за стільки діб — здаємось (напр. адмін-
# пристрій зник). Інакше ретраїли б вічно.
RECOVERY_GIVE_UP_DAYS = 1
# Скільки незавершених secondary-циклів після grace вважати проблемою. Кілька,
# а не один: під час deploy старий колектор устигає записати 1–2 рядки без
# derived-статусу, і це не має піднімати тривогу.
DERIVED_STUCK_THRESHOLD = 3
# Бекап іде щодоби. >36 год без успішного — це вже ≥2 добові прогони поспіль,
# що не завершились (одиночний збій, що сам вилікувався вночі, будити не варто).
# Раніше провал бекапу було видно лише в пасивній адмін-телеметрії — днями
# (аудит M-12).
BACKUP_STALE_HOURS = 36
# backup-stamp і reboot-required факти беремо з host-snapshot (той самий
# /telemetry/host.json, що вже читає API за SEC-1), а не монтуючи весь хостовий
# /run у контейнер (аудит M-1: широкий /run тягнув і docker.sock). Snapshot
# оновлюється щохвилини systemd-таймером і вже містить backups.age_hours та
# system.reboot_pending_days.
SNAPSHOT_PATH = Path(os.environ.get("AVELREN_TELEMETRY_SNAPSHOT", "/telemetry/host.json"))


def _read_snapshot() -> dict | None:
    """Розпарсений host-snapshot, або None якщо його ще/уже немає чи він битий.

    None веде себе як «невідомо» — краще не тривожити на основі відсутніх даних,
    ніж кричати хибно (той самий fail-safe, що був для відсутнього штампа)."""
    try:
        return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

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

    # Вторинний конвеєр (alerts/ETA) — окремо від fetch. Без цієї перевірки
    # observations свіжі, collector_errors чистий, а сповіщення тихо не
    # працюють (аудит OBS-1). Дзеркало перевірки вище, але по derived_error.
    row = await (
        await conn.execute(
            """
            SELECT count(*) AS failed
            FROM collector_runs
            WHERE time > now() - INTERVAL '30 minutes' AND derived_error IS NOT NULL
            """
        )
    ).fetchone()
    if row and row["failed"] >= 10:
        problems["derived_errors"] = (
            f"обробка алертів/ETA впала {row['failed']} разів за півгодини"
        )

    # Hard-crash secondary-фази: SIGKILL/OOM між primary-комітом і кінцем
    # secondary лишає derived_processed_at=NULL і derived_error=NULL — виняток
    # не спрацював, тож попередня перевірка це не ловить. Після grace-періоду
    # (in-flight цикл ще міг не дописати статус) такі рядки — реальний сигнал,
    # що вторинний конвеєр systematically не завершується (аудит OBS-1 / B3).
    row = await (
        await conn.execute(
            """
            SELECT count(*) AS stuck
            FROM collector_runs
            WHERE time > now() - INTERVAL '30 minutes'
              AND time < now() - INTERVAL '2 minutes'
              AND derived_processed_at IS NULL
              AND derived_error IS NULL
            """
        )
    ).fetchone()
    if row and row["stuck"] >= DERIVED_STUCK_THRESHOLD:
        problems["derived_stuck"] = (
            f"обробка алертів/ETA не завершилась {row['stuck']} разів за півгодини "
            "(ймовірно, контейнер падає у вторинній фазі)"
        )

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

    backup_age = _backup_age_hours()
    if backup_age is not None and backup_age > BACKUP_STALE_HOURS:
        problems["backup_stale"] = (
            f"останній успішний бекап був {int(backup_age)} год тому "
            "(≥2 добові прогони поспіль не завершились)"
        )

    return problems


def _backup_age_hours() -> float | None:
    """Скільки годин тому deploy/backup.sh востаннє успішно завершився, або None.

    None — штамп ще не створювався: свіжий деплой до першого бекапу, або хост
    щойно перезавантажився (штамп на /run — tmpfs). І там, і там тривога була б
    хибною, а timer із Persistent=true скоро відновить штамп.
    """
    snapshot = _read_snapshot()
    if snapshot is None:
        return None
    age = snapshot.get("backups", {}).get("age_hours")
    if not isinstance(age, (int, float)):
        return None
    return float(age)


def _reboot_pending() -> int | None:
    """Скільки діб сервер просить перезавантаження, або None.

    Автоматичний ребут ми свідомо не вмикаємо: сервіс лягав би вночі без
    попередження. Але тоді хтось має помічати цей файл — інакше ядро з
    відомою вразливістю встановлене, а працює старе, і так місяцями.
    """
    snapshot = _read_snapshot()
    if snapshot is None:
        return None
    system = snapshot.get("system", {})
    if not system.get("reboot_required"):
        return None
    days = system.get("reboot_pending_days")
    if not isinstance(days, int):
        return None
    return days


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

        # Проблема зникла — закриваємо тривогу ОДРАЗУ (стан системи не має
        # брехати). Recovery-повідомлення НЕ шлемо тут: раніше resolved_at
        # ставився незалежно від результату _notify, і якщо push падав, адмін
        # не дізнавався про відновлення, а повтору не було (аудит OBS-2).
        # Доставку recovery веде окрема фаза нижче.
        for kind, alert in open_alerts.items():
            if kind not in problems:
                await conn.execute(
                    "UPDATE health_alerts SET resolved_at = now() WHERE id = %s", (alert["id"],)
                )
                log.info("проблема %s зникла", kind)

        await _deliver_recoveries(conn, client)

        for kind, detail in problems.items():
            alert = open_alerts.get(kind)

            if alert is None:
                await conn.execute(
                    "INSERT INTO health_alerts (kind, detail) VALUES (%s, %s)", (kind, detail)
                )
                log.error("ПРОБЛЕМА %s: %s", kind, detail)
                if await _notify(conn, client, "AvelRen: проблема", detail, kind):
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
                if await _notify(conn, client, "AvelRen: проблема триває", detail, kind):
                    await conn.execute(
                        """
                        UPDATE health_alerts SET last_sent_at = now(), send_count = send_count + 1
                        WHERE id = %s
                        """,
                        (alert["id"],),
                    )


async def _deliver_recoveries(conn: AsyncConnection, client: httpx.AsyncClient) -> None:
    """Доставляє recovery-повідомлення для вже закритих проблем (OBS-2).

    resolved_at ставиться одразу, коли проблема зникла, а recovery_notified_at
    — лише після фактичної доставки. Ретраїмо щоциклу, поки не вийде; якщо за
    RECOVERY_GIVE_UP_DAYS так і не доставили (напр. немає адмін-пристрою),
    здаємось, щоб не намагатися вічно.
    """
    rows = await (
        await conn.execute(
            """
            SELECT id, kind, resolved_at
            FROM health_alerts
            WHERE resolved_at IS NOT NULL
              AND recovery_notified_at IS NULL
              AND recovery_abandoned_at IS NULL
            ORDER BY resolved_at
            """
        )
    ).fetchall()

    for r in rows:
        age_days = (datetime.now(UTC) - r["resolved_at"]).total_seconds() / 86400
        if await _notify(
            conn, client, "AvelRen відновився", f"{r['kind']}: усе гаразд", r["kind"]
        ):
            # notified — ЛИШЕ по факту доставки. Give-up іде в окреме поле,
            # щоб по БД можна було відрізнити «доставлено» від «здалися» (B2).
            await conn.execute(
                "UPDATE health_alerts SET recovery_notified_at = now() WHERE id = %s",
                (r["id"],),
            )
            log.info("доставлено recovery %s", r["kind"])
        elif age_days > RECOVERY_GIVE_UP_DAYS:
            await conn.execute(
                "UPDATE health_alerts SET recovery_abandoned_at = now() WHERE id = %s",
                (r["id"],),
            )
            log.warning(
                "здаюся з recovery %s: не доставлено за %d дн", r["kind"], RECOVERY_GIVE_UP_DAYS
            )


async def _notify(
    conn: AsyncConnection, client: httpx.AsyncClient, title: str, body: str, kind: str
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
                {"type": "health", "title": title, "body": body},
                # Окремий ключ на кожен тип проблеми, інакше на офлайн-пристрої
                # новіша тривога (напр. db_size) мовчки витісняє ще не показану
                # (напр. collector_silent) — аудит M-10.
                collapse_key=f"health:{kind}",
                ttl_seconds=1800,
            )
            delivered = True
        except fcm.FcmError as exc:
            # Мертвий адмін-токен інакше ретраїться щоциклу вічно; гасимо його
            # так само, як notifier гасить мертві клієнтські токени.
            if exc.dead_token:
                await conn.execute(
                    "UPDATE devices SET fcm_token = NULL WHERE fcm_token = %s", (token,)
                )
                log.warning("вимкнув мертвий адмін-токен")
            else:
                log.error("не вдалося надіслати тривогу: %s", exc)
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
