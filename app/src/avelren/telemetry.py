"""Телеметрія сервера для застосунку.

**Trust boundary.** Раніше цей модуль читав `/proc`, `/run` та `/secrets`
безпосередньо з файлової системи. Це означало, що public API-контейнер мусив
мати bind-mounts до всього перерахованого — включно з каталогом, де лежить
Firebase service-account. Помилка path-traversal або RCE в API давала доступ
до FCM-ключа, хоча самому API він не потрібен (аудит SEC-1 / A-01).

Тепер збір host-метрик відбувається на самому хості (`deploy/telemetry-snapshot.sh`
під systemd-таймером), API читає лише один JSON-файл — і жодного secrets,
proc чи run у контейнері немає. Свідомо не робимо fallback до старих шляхів:
"тимчасовий compatibility" — це найгірший спосіб протягнути security-fix у
production.

Свідомо **не** монтуємо `/var/run/docker.sock`: доступ до нього рівносильний
root на хості, і віддавати таке заради красивого списку контейнерів — поганий
обмін. Стан сервісів виводимо з того, що вони роблять: збирач живий, якщо
пише спостереження; розсилач живий, якщо надсилає.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from psycopg import AsyncConnection

# Каталог bind-mount snapshot-файлу. Змінна для тестів; у docker-compose
# монтується /var/lib/avelren-telemetry:/telemetry:ro.
SNAPSHOT_PATH = Path(os.environ.get("AVELREN_TELEMETRY_SNAPSHOT", "/telemetry/host.json"))

# Snapshot старший за 5 хв вважається протухлим: timer має інтервал 1 хв, тож
# запас чотирикратний і покриває коротку паузу без хибних тривог.
SNAPSHOT_MAX_AGE_SECONDS = 300


def _snapshot() -> dict:
    """Читає останній host-snapshot. Порожній dict — snapshot відсутній.

    Помилки не роблять exception назовні: API-хендлер має вижити навіть при
    зникненні snapshot pipeline; клієнт побачить `stale: true` замість 500.
    """
    try:
        raw = SNAPSHOT_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _snapshot_age_seconds(snap: dict) -> int | None:
    ts = snap.get("collected_at")
    if not ts:
        return None
    try:
        # Формат від snapshot script: ISO-8601 UTC з "Z".
        collected = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int((datetime.now(UTC) - collected).total_seconds())


def system() -> dict:
    """Стан хоста: load, memory, disk, потреба ребуту.

    `stale=true` означає, що snapshot-файл старіший за
    `SNAPSHOT_MAX_AGE_SECONDS` або відсутній взагалі. Це важливий сигнал:
    інакше протухлі числа виглядають як свіжі й приховують збій telemetry
    pipeline.
    """
    snap = _snapshot()
    data = dict(snap.get("system") or {})
    age = _snapshot_age_seconds(snap)
    data["snapshot_age_seconds"] = age
    data["stale"] = age is None or age > SNAPSHOT_MAX_AGE_SECONDS
    return data


async def pipeline(conn: AsyncConnection) -> dict:
    """Стан конвеєра даних: те, заради чого сервер існує."""
    row = await (
        await conn.execute(
            """
            SELECT
                (SELECT count(*) FROM observations)                       AS observations,
                (SELECT count(*) FROM checkpoints
                  WHERE last_seen > now() - INTERVAL '1 day')             AS checkpoints_active,
                (SELECT max(time) FROM observations)                      AS last_observation,
                (SELECT count(*) FROM collector_runs
                  WHERE time > now() - INTERVAL '1 hour')                 AS runs_last_hour,
                (SELECT count(*) FROM collector_runs
                  WHERE time > now() - INTERVAL '1 hour' AND error IS NOT NULL)
                                                                          AS errors_last_hour,
                (SELECT count(*) FROM devices)                            AS devices,
                (SELECT count(*) FROM subscriptions WHERE is_active)      AS subscriptions,
                (SELECT count(*) FROM eta_targets WHERE is_active)        AS eta_targets,
                (SELECT count(*) FROM alerts WHERE status = 'pending')    AS alerts_pending,
                (SELECT coalesce(sum(send_count), 0) FROM alerts)         AS pushes_sent,
                (SELECT pg_database_size(current_database()))             AS db_bytes,
                (SELECT min(time) FROM observations)                      AS collecting_since
            """
        )
    ).fetchone()

    data = dict(row) if row else {}
    data["db_size_mb"] = round((data.pop("db_bytes", 0) or 0) / 1024**2, 1)

    # Очікуємо 60 циклів на годину. Менше — були прогалини, і це видно одразу.
    runs = data.get("runs_last_hour") or 0
    data["cycles_expected_per_hour"] = 60
    data["completeness_percent"] = min(100, round(runs / 60 * 100))

    return data


def network() -> dict:
    """Трафік сервера від старту системи (з host-snapshot).

    Раніше API читав `/host/proc/1/net/dev` напряму — це вимагало mount-у
    цілого хостового `/proc` у public контейнер. Тепер лічильники беруться зі
    snapshot, зібраного під root на хості.
    """
    data = dict(_snapshot().get("network") or {})
    data.setdefault("rx_total_gb", 0.0)
    data.setdefault("tx_total_gb", 0.0)
    return data


def certificate() -> dict:
    """Термін сертифіката (з host-snapshot).

    Раніше цей виклик робив синхронний ssl-handshake напряму з async
    FastAPI-хендлера — блокував event loop на секунди і давав API мережеву
    поверхню назовні. Тепер cert перевіряє host-таймер, API лише читає число.
    """
    return dict(_snapshot().get("certificate") or {"error": "snapshot missing"})


def backups() -> dict:
    """Свіжість резервних копій (з host-snapshot).

    Копія, про яку ніхто не дивиться, тихо ламається й лишається зламаною
    рівно до дня, коли знадобиться.
    """
    return dict(_snapshot().get("backups") or {"last_run": None, "age_hours": None})


def snapshot_problem(system_data: dict) -> dict | None:
    """Синтетична проблема, коли host-snapshot протух або зник.

    Без цього збій telemetry-таймера виглядав би на телефоні як здоровий
    сервер: поля з відсутнього snapshot стають нулями за замовчуванням, а
    застосунок ще й пише «Проблем немає». Мовчазний збій моніторингу — гірший
    за відсутність моніторингу, тож stale має потрапити саме в той список,
    який користувач читає першим.

    Форма збігається з рядками `health_alerts`, тож клієнту не потрібно нічого
    знати про нове поле — він відмалює це як звичайну проблему.
    """
    if not system_data.get("stale"):
        return None

    age = system_data.get("snapshot_age_seconds")
    if age is None:
        detail = "Host-телеметрія не збирається: snapshot відсутній"
    else:
        detail = f"Host-телеметрія не оновлювалась {age // 60} хв"

    return {
        "kind": "telemetry_snapshot_stale",
        "detail": detail,
        "first_seen": None,
        "send_count": 0,
    }


async def health_alerts(conn: AsyncConnection) -> list[dict]:
    rows = await (
        await conn.execute(
            """
            SELECT kind, detail, first_seen, send_count
            FROM health_alerts
            WHERE resolved_at IS NULL
            ORDER BY first_seen
            """
        )
    ).fetchall()
    return rows
