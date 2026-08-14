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

from . import __version__ as APP_VERSION
from .config import settings

# Whitelist полів, що ми віддаємо для кожного контейнера. Свідомо ВЕЛИКА
# паранойя тут: raw `docker inspect` містить env (може мати креденшіали),
# mounts (розкриває шляхи secrets), cmd, labels. Розширюємо цей набір лише
# явно і з обґрунтуванням у коментарі — не «а давайте додамо всі поля».
_SERVICE_ALLOWED_FIELDS = frozenset(
    {"status", "health", "started_at", "restart_count", "exit_code", "oom_killed", "image"}
)

# Whitelist контейнерів, які ми знаємо і хочемо показувати. Будь-що інше з
# snapshot ігнорується — щоб випадкове поле в JSON не з'явилось на клієнті.
_SERVICE_ALLOWED_NAMES = frozenset(
    {"db", "api", "collector", "notifier", "watchdog", "caddy"}
)

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
                (SELECT count(*) FROM collector_runs
                  WHERE time > now() - INTERVAL '1 hour' AND error IS NULL)
                                                        AS successful_runs_last_hour,
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
    # Completeness рахує УСПІШНІ цикли (error IS NULL), а не просто спроби:
    # коли ЄЧерга щохвилини віддає 502, collector_runs усе одно поповнюється
    # (runs_last_hour → 60), але жодне спостереження не зібране. Рахувати спроби
    # означало б показувати 100% повноти під час повного збою збору даних —
    # рівно те, від чого completeness має захищати.
    successful = data.get("successful_runs_last_hour") or 0
    data["cycles_expected_per_hour"] = 60
    data["completeness_percent"] = min(100, round(successful / 60 * 100))

    return data


async def last_collector_run(conn: AsyncConnection) -> dict | None:
    """Останній цикл збирача — успіх чи ні, включно з HTTP-статусом upstream.

    Потрібно, щоб Server Dashboard не покладався на непрямі сигнали
    (last_observation, errors_last_hour): у режимі «ЄЧерга відповідає 502
    щохвилини» observations стають протухлими, а причину видно лише в цьому
    рядку. Свідомо НЕ віддаємо `body_sha256` — це технічний артефакт для
    порівняння payload'ів, клієнту не потрібен і потенційно пришвидшить
    інференс, чи є на upstream new content.
    """
    row = await (
        await conn.execute(
            """
            SELECT time, http_status, duration_ms, rows_written, error,
                   derived_processed_at, derived_error
            FROM collector_runs
            ORDER BY time DESC
            LIMIT 1
            """
        )
    ).fetchone()
    return dict(row) if row else None


async def last_collector_success(conn: AsyncConnection) -> dict | None:
    """Останній успішний цикл. Окремо від last_run — потрібно розрізняти
    «ЄЧерга щойно повернула 200, збережено N рядків» vs «останній цикл впав,
    попередній успіх був годину тому». Без цього поля дашборд однаково
    показує ⚪ на «щойно почалися проблеми» і на «давно все зламано»."""
    row = await (
        await conn.execute(
            """
            SELECT time, http_status, duration_ms, rows_written
            FROM collector_runs
            WHERE error IS NULL AND http_status = 200 AND rows_written > 0
            ORDER BY time DESC
            LIMIT 1
            """
        )
    ).fetchone()
    return dict(row) if row else None


def upstream() -> dict:
    """Що і куди зараз ходить збирач. Не читає БД: сам endpoint береться з
    settings — джерела правди для того ж collector'а. Клієнт бачить зв'язку
    «ось цей URL, ось з нього ми качаємо» без здогадок."""
    return {
        "base_url": settings.echerha_base_url,
        "workload_url": settings.workload_url,
        "vehicle_type": settings.echerha_vehicle_type,
        "poll_interval_seconds": settings.poll_interval_seconds,
    }


def services() -> list[dict]:
    """Список контейнерів зі snapshot. Whitelist полів застосовується ТУТ, не
    в snapshot-скрипті: навіть якщо host-скрипт випадково запише зайве поле,
    API нічого зайвого не віддасть. Це classic defence-in-depth — один
    неувічний коміт у deploy/ не має відкрити канал для утечки env/mounts."""
    raw = _snapshot().get("services") or []
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or name not in _SERVICE_ALLOWED_NAMES:
            continue
        safe: dict = {"name": name}
        for field in _SERVICE_ALLOWED_FIELDS:
            if field in entry:
                safe[field] = entry[field]
        out.append(safe)
    # Стабільний порядок — щоб UI не «стрибав» між композиціями.
    order = ["db", "api", "collector", "notifier", "watchdog", "caddy"]
    out.sort(key=lambda s: order.index(s["name"]) if s["name"] in order else 999)
    return out


def docker() -> dict:
    """Версії docker daemon і compose зі snapshot. Мета — на дашборді видно,
    коли хост відстає від рекомендованої версії."""
    raw = _snapshot().get("docker") or {}
    if not isinstance(raw, dict):
        return {}
    return {
        "daemon_version": raw.get("daemon_version"),
        "compose_version": raw.get("compose_version"),
    }


def inodes() -> dict:
    """Використання inode. Заповнена filesystem по inode виглядає як «диску
    ще купа», аж поки не спробуєш створити файл. Тому окремо від diskUsage."""
    raw = _snapshot().get("inodes") or {}
    if not isinstance(raw, dict):
        return {"total": None, "used": None, "used_percent": None}
    return {
        "total": raw.get("total"),
        "used": raw.get("used"),
        "used_percent": raw.get("used_percent"),
    }


async def version(conn: AsyncConnection) -> dict:
    """Ідентифікація версії застосунку на сервері.

    - `app_version` беремо з `__version__` пакета (єдине джерело правди).
    - `git_sha` — з env `AVELREN_GIT_SHA`, який docker-build проставляє з
      `SOURCE_COMMIT` (див. Dockerfile). У dev-режимі його може не бути —
      тоді null, а не «unknown»: клієнт має розрізняти «версія відома, це dev»
      від «версія була, але зникла».
    - `migrations_version` — max(version) з `schema_migrations`. Свіжа схема
      і застарілий код (або навпаки) — головний клас deploy-збоїв.
    """
    row = await (
        await conn.execute(
            "SELECT max(version) AS v FROM schema_migrations"
        )
    ).fetchone()
    return {
        "app_version": APP_VERSION,
        "git_sha": os.environ.get("AVELREN_GIT_SHA") or None,
        "migrations_version": (row["v"] if row else None),
    }


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
