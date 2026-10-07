"""Watchdog: notices that the system went silent, and wakes the administrator.

The most dangerous failure is a silent one. The collector may crash at night,
and no one will find out until morning, while the gap in the history cannot be
restored later: eCherha does not keep the past.

Alerts go through the same channel as regular notifications — FCM to a phone
marked `is_admin`. A separate system (email, Telegram) would mean another
service, another secret, and another point of failure.
"""

import asyncio
import json
import logging
import os
import signal
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from psycopg import AsyncConnection

from . import fcm
from .config import settings
from .db import get_pool
from .schema_gate import assert_schema_at_least

log = logging.getLogger("avelren.watchdog")

KYIV = ZoneInfo("Europe/Kyiv")

CHECK_INTERVAL = 300
DAILY_REPORT_HOUR_KYIV = 12
DAILY_REPORT_TTL_SECONDS = 86400
SNAPSHOT_MAX_AGE_SECONDS = 300
SNAPSHOT_FUTURE_TOLERANCE_SECONDS = 60
# Один цикл watchdog на БД; блокування живе до commit/rollback циклу.
WATCHDOG_LOCK_ID = 0x4156454C57415443
# A reboot is a planned matter, not an urgent one: we allow a few days for a
# convenient moment.
REBOOT_GRACE_DAYS = 3
RESEND_INTERVAL = 3600  # we repeat the alert once an hour, not every five minutes
# If a recovery is still not delivered after this many days — we give up (e.g. the
# admin device is gone). Otherwise we would retry forever.
RECOVERY_GIVE_UP_DAYS = 1
# How many unfinished secondary cycles after grace count as a problem. A few, not
# one: during a deploy the old collector manages to write 1–2 rows without a
# derived status, and that must not raise an alert.
DERIVED_STUCK_THRESHOLD = 3
# The backup runs daily. >36 h without a successful one is already ≥2 daily runs
# in a row that did not finish (a single failure that healed itself overnight is
# not worth waking anyone for). Previously a backup failure was visible only in
# passive admin telemetry — for days (audit M-12).
BACKUP_STALE_HOURS = 36
# We take the backup-stamp and reboot-required facts from the host snapshot (the
# same /telemetry/host.json the API already reads under SEC-1), rather than
# mounting the entire host /run into the container (audit M-1: a broad /run
# pulled in docker.sock too). The snapshot is refreshed every minute by a systemd
# timer and already contains backups.age_hours and system.reboot_pending_days.
SNAPSHOT_PATH = Path(os.environ.get("AVELREN_TELEMETRY_SNAPSHOT", "/telemetry/host.json"))


def _read_snapshot() -> dict | None:
    """Parsed host snapshot, or None if it is not yet/no longer there or is corrupt.

    None behaves as "unknown" — better not to alert based on missing data than
    to cry falsely (the same fail-safe that existed for a missing stamp)."""
    try:
        snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        return snapshot if isinstance(snapshot, dict) else None
    except (OSError, ValueError):
        return None

_stop = asyncio.Event()


def _request_stop(*_: object) -> None:
    _stop.set()


async def _checks(conn: AsyncConnection) -> dict[str, str]:
    """Returns {problem_type: description}. Empty — all is well."""
    problems: dict[str, str] = {}

    row = await (
        await conn.execute("SELECT max(time) AS last FROM observations")
    ).fetchone()
    last = row["last"] if row else None

    if last is None:
        problems["no_data"] = "there are no observations in the database"
    else:
        age = (datetime.now(UTC) - last).total_seconds()
        # Three missed cycles in a row is no longer a network hiccup.
        if age > settings.poll_interval_seconds * 3:
            problems["collector_silent"] = f"collector silent for {int(age // 60)} min"

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
        problems["collector_errors"] = f"{row['failed']} errors in the last half hour"

    # The secondary pipeline (alerts/ETA) — separate from fetch. Without this
    # check, observations are fresh, collector_errors is clean, yet notifications
    # quietly do not work (audit OBS-1). A mirror of the check above, but by
    # derived_error.
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
            f"alert/ETA processing failed {row['failed']} times in the last half hour"
        )

    # Hard crash of the secondary phase: a SIGKILL/OOM between the primary commit
    # and the end of secondary leaves derived_processed_at=NULL and
    # derived_error=NULL — the exception did not fire, so the previous check does
    # not catch it. After the grace period (an in-flight cycle might not have
    # written the status yet) such rows are a real signal that the secondary
    # pipeline systematically does not finish (audit OBS-1 / B3).
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
            f"alert/ETA processing did not finish {row['stuck']} times in the last half hour "
            "(the container likely crashes in the secondary phase)"
        )

    row = await (
        await conn.execute(
            "SELECT pg_database_size(current_database()) AS bytes"
        )
    ).fetchone()
    gb = (row["bytes"] if row else 0) / 1024**3
    if gb > 20:
        problems["db_size"] = f"the database has grown to {gb:.1f} GB"

    reboot = _reboot_pending()
    if reboot is not None and reboot >= REBOOT_GRACE_DAYS:
        problems["reboot_required"] = (
            f"an update has been waiting for a reboot for {reboot} days. "
            "The fixed kernel is installed, but the old one is running"
        )

    backup_age = _backup_age_hours()
    if backup_age is not None and backup_age > BACKUP_STALE_HOURS:
        problems["backup_stale"] = (
            f"the last successful backup was {int(backup_age)} hours ago "
            "(≥2 daily runs in a row did not finish)"
        )

    drift = _snapshot_script_drift()
    if drift is not None:
        problems["snapshot_script_drift"] = (
            f"the installed telemetry snapshot script is not the deployed one: {drift}. "
            "Sections it does not know about are absent from the snapshot, and an "
            "absent section reads as an empty dashboard, not as an error (issue #164)"
        )

    if _migrate_pin_lost():
        problems["migrate_pin_lost"] = (
            "the 001-009 migration pin is not mounted: /migrations resolves to "
            "the repository, where 010 already exists. Any profiled `up` would "
            "stamp it out of the 3D order (issue #160)"
        )

    return problems


def _section(snapshot: dict, name: str) -> dict:
    value = snapshot.get(name)
    return value if isinstance(value, dict) else {}


def _backup_age_hours() -> float | None:
    """How many hours ago deploy/backup.sh last finished successfully, or None.

    None — the stamp has not been created yet: a fresh deploy before the first
    backup, or the host just rebooted (the stamp on /run is tmpfs). In both cases
    the alert would be false, and a timer with Persistent=true will soon restore
    the stamp.
    """
    snapshot = _read_snapshot()
    if snapshot is None:
        return None
    age = _section(snapshot, "backups").get("age_hours")
    if not isinstance(age, (int, float)):
        return None
    return float(age)


def _reboot_pending() -> int | None:
    """How many days the server has been asking for a reboot, or None.

    We deliberately do not enable automatic reboot: the service would go down at
    night without warning. But then someone has to notice this file — otherwise
    a kernel with a known vulnerability is installed while the old one runs, and
    so for months.
    """
    snapshot = _read_snapshot()
    if snapshot is None:
        return None
    system = _section(snapshot, "system")
    if not system.get("reboot_required"):
        return None
    days = system.get("reboot_pending_days")
    if not isinstance(days, int):
        return None
    return days


# sha256 of deploy/telemetry-snapshot.sh as it stands in this commit (#164).
# The snapshot script does NOT run from the checkout — systemd executes an
# installed copy — so this constant is how the image states which copy it was
# built against. A CI step keeps it equal to the file; it cannot drift silently
# the way the installed copy did.
EXPECTED_SNAPSHOT_SHA = "40eac808d322935626db3f0e64da9b69d4e13cce4e110d53744682eb9c90d2d2"


def _snapshot_script_drift() -> str | None:
    """Why the running snapshot script is not the one this image expects, or None.

    The installed copy sat 125 lines behind the repository for weeks: the whole
    `docker` section was missing from the live snapshot, and a missing section
    renders as a dash, so the dashboard looked merely empty rather than wrong
    (#164; #93 was the same story for the backup script).

    An ABSENT hash is an alarm here, unlike the nulls elsewhere in the snapshot.
    Those mean "the probe could not look" and have innocent explanations; this one
    means the installed script predates the field itself, which is precisely the
    drift being detected. That is also why the check cannot live in the script.
    """
    snapshot = _read_snapshot()
    if snapshot is None:
        return None
    got = snapshot.get("script_sha256")
    if got == EXPECTED_SNAPSHOT_SHA:
        return None
    if not isinstance(got, str):
        return (
            "the host snapshot does not report a script hash at all — the installed "
            "copy is older than the field itself"
        )
    return f"installed {got[:12]}, this image expects {EXPECTED_SNAPSHOT_SHA[:12]}"


def _migrate_pin_lost() -> bool:
    """True only when the host snapshot says the migration pin is NOT mounted.

    The pin keeps `migrate` seeing 001-009 while the 3D gate (#15) is still
    unauthorised. It lives in the host's compose override — outside git — and it
    fell out silently during the #88 window (#160). The deploy runbook checks it,
    but only during a deploy, so between windows nothing watched the guard.

    Missing or null is deliberately NOT an alarm. The snapshot reports null when
    it could not look at all (no docker, no stack directory), and a watchdog that
    treats "unknown" as "broken" earns exactly one week of being believed.
    """
    snapshot = _read_snapshot()
    if snapshot is None:
        return False
    return _section(snapshot, "docker").get("migrate_pin_active") is False


def _int_or_unknown(value: object) -> str:
    return str(value) if type(value) is int and value >= 0 else "невідомо"


def _bool_or_unknown(value: object) -> str:
    if value is True:
        return "так"
    return "ні" if value is False else "невідомо"


def _snapshot_problem(snapshot: dict | None, now: datetime) -> str | None:
    if not isinstance(snapshot, dict):
        return "телеметрія сервера недоступна"
    value = snapshot.get("collected_at")
    try:
        collected = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        collected = None
    if collected is None or collected.tzinfo is None:
        return "час телеметрії невідомий"
    age = (now - collected).total_seconds()
    if age < -SNAPSHOT_FUTURE_TOLERANCE_SECONDS:
        return "час телеметрії некоректний"
    if age > SNAPSHOT_MAX_AGE_SECONDS:
        return "телеметрія застаріла"
    return None


def _daily_report_body(snapshot: dict | None, *, now: datetime | None = None) -> str:
    problem = _snapshot_problem(snapshot, now or datetime.now(UTC))
    if problem is not None:
        return (
            f"Щоденний звіт AvelRen: {problem}. "
            "Оновлення: невідомо. Перезавантаження: невідомо. "
            "Ресурси: невідомо. Помилки за 24 год: невідомо."
        )

    system = _section(snapshot, "system")

    updates = _int_or_unknown(system.get("updates_upgradable"))
    if updates == "невідомо":
        updates = _int_or_unknown(system.get("updates_pending"))
    security = _int_or_unknown(system.get("updates_security"))
    installed = _int_or_unknown(system.get("updates_installed_24h"))
    update_failures = _int_or_unknown(system.get("update_failures_24h"))
    rebooted = _bool_or_unknown(system.get("rebooted_24h"))
    reboot_required = system.get("reboot_required") is True
    reboot_text = _bool_or_unknown(system.get("reboot_required"))

    pkgs = system.get("reboot_required_pkgs")
    reboot_pkgs = ""
    if reboot_required and isinstance(pkgs, list) and pkgs:
        names = [p for p in pkgs if isinstance(p, str)]
        if names:
            reboot_pkgs = f" ({', '.join(names[:4])}"
            if len(names) > 4:
                reboot_pkgs += f" +{len(names) - 4}"
            reboot_pkgs += ")"

    journal_errors = _int_or_unknown(system.get("journal_errors_24h"))
    compose_errors = _int_or_unknown(system.get("compose_errors_24h"))

    disk_used = system.get("disk_used_percent")
    if type(disk_used) is not int or not 0 <= disk_used <= 100:
        disk_used = None
    memory_total = system.get("memory_total_mb")
    memory_used = system.get("memory_used_mb")
    memory_percent: int | None = None
    if (
        type(memory_total) is int
        and memory_total > 0
        and type(memory_used) is int
        and 0 <= memory_used <= memory_total
    ):
        memory_percent = round(memory_used * 100 / memory_total)

    disk_text = f"{disk_used}%" if isinstance(disk_used, int) else "невідомо"
    memory_text = f"{memory_percent}%" if memory_percent is not None else "невідомо"
    if isinstance(disk_used, int) and disk_used >= 90:
        resource_status = "КРИТИЧНО: диск"
    elif (
        isinstance(disk_used, int)
        and disk_used >= 80
        or memory_percent is not None
        and memory_percent >= 90
    ):
        resource_status = "УВАГА"
    elif disk_used is None or memory_percent is None:
        resource_status = "дані неповні"
    else:
        resource_status = "норма"

    return (
        "Щоденний звіт AvelRen. "
        f"Доступні оновлення: {updates}, безпекові: {security}. "
        f"Автоматично за 24 год: встановлено {installed}, помилок {update_failures}. "
        f"Перезапуск за 24 год: {rebooted}; потрібен зараз: {reboot_text}{reboot_pkgs}. "
        f"Ресурси: диск {disk_text}, пам'ять {memory_text} ({resource_status}). "
        f"Помилки за 24 год: systemd {journal_errors}, сервіси {compose_errors}."
    )


async def _daily_report_already_sent(conn: AsyncConnection, report_date: str) -> bool:
    row = await (
        await conn.execute(
            "SELECT 1 FROM health_alerts WHERE kind = %s LIMIT 1",
            (f"daily_status:{report_date}",),
        )
    ).fetchone()
    return row is not None


async def _record_daily_report_sent(
    conn: AsyncConnection, report_date: str, body: str
) -> None:
    await conn.execute(
        """
        INSERT INTO health_alerts
            (kind, detail, resolved_at, recovery_notified_at, last_sent_at, send_count)
        VALUES (%s, %s, now(), now(), now(), 1)
        """,
        (f"daily_status:{report_date}", body),
    )


async def _deliver_daily_report(conn: AsyncConnection, client: httpx.AsyncClient) -> None:
    now = datetime.now(KYIV)
    if now.hour < DAILY_REPORT_HOUR_KYIV:
        return

    report_date = now.date().isoformat()
    if await _daily_report_already_sent(conn, report_date):
        return

    snapshot = _read_snapshot()
    body = f"Звіт за {report_date}. " + _daily_report_body(snapshot, now=now)
    if await _notify(conn, client, "AvelRen: щоденний звіт", body, f"daily:{report_date}"):
        await _record_daily_report_sent(conn, report_date, body)
        log.info("FCM accepted daily status report for %s", report_date)


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
        row = await (
            await conn.execute(
                "SELECT pg_try_advisory_xact_lock(%s) AS acquired", (WATCHDOG_LOCK_ID,)
            )
        ).fetchone()
        if not row or not row["acquired"]:
            log.info("another watchdog cycle is active; skipping")
            return
        problems = await _checks(conn)
        open_alerts = await _open_alerts(conn)

        # Health incidents stay in the database and logs. The phone receives only
        # the daily report, so resolved incidents are closed without a recovery
        # push and marked as intentionally not requiring one.
        for kind, alert in open_alerts.items():
            if kind not in problems:
                await conn.execute(
                    """
                    UPDATE health_alerts
                    SET resolved_at = now(),
                        recovery_notified_at = COALESCE(recovery_notified_at, now())
                    WHERE id = %s
                    """,
                    (alert["id"],),
                )
                log.info("problem %s is gone", kind)

        await _deliver_daily_report(conn, client)

        for kind, detail in problems.items():
            alert = open_alerts.get(kind)

            if alert is None:
                await conn.execute(
                    "INSERT INTO health_alerts (kind, detail) VALUES (%s, %s)", (kind, detail)
                )
                log.error("PROBLEM %s: %s", kind, detail)


async def _deliver_recoveries(conn: AsyncConnection, client: httpx.AsyncClient) -> None:
    """Delivers recovery messages for already-closed problems (OBS-2).

    resolved_at is set immediately when the problem is gone, but
    recovery_notified_at — only after actual delivery. We retry every cycle until
    it succeeds; if after RECOVERY_GIVE_UP_DAYS it is still not delivered (e.g.
    there is no admin device), we give up, so as not to try forever.
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
            conn, client, "AvelRen recovered", f"{r['kind']}: all is well", r["kind"]
        ):
            # notified — ONLY on the fact of delivery. Give-up goes into a
            # separate field, so the DB can distinguish "delivered" from
            # "gave up" (B2).
            await conn.execute(
                "UPDATE health_alerts SET recovery_notified_at = now() WHERE id = %s",
                (r["id"],),
            )
            log.info("delivered recovery %s", r["kind"])
        elif age_days > RECOVERY_GIVE_UP_DAYS:
            await conn.execute(
                "UPDATE health_alerts SET recovery_abandoned_at = now() WHERE id = %s",
                (r["id"],),
            )
            log.warning(
                "giving up on recovery %s: not delivered within %d days",
                r["kind"],
                RECOVERY_GIVE_UP_DAYS,
            )


async def _notify(
    conn: AsyncConnection, client: httpx.AsyncClient, title: str, body: str, kind: str
) -> bool:
    tokens = await _admin_tokens(conn)
    if not tokens:
        log.warning("no admin devices, alert only in the log: %s", body)
        return False

    delivered = False
    daily = kind.startswith("daily:")
    payload = {"type": "health", "title": title, "body": body}
    if daily:
        payload["report_id"] = kind
    for token in tokens:
        try:
            await fcm.send(
                client,
                token,
                payload,
                # Офлайн-пристрій чекає останній звіт, не чергу старих дат.
                collapse_key="health:daily" if daily else f"health:{kind}",
                ttl_seconds=DAILY_REPORT_TTL_SECONDS if daily else 1800,
            )
            delivered = True
        except fcm.FcmError as exc:
            # A dead admin token would otherwise be retried every cycle forever;
            # we clear it the same way the notifier clears dead client tokens.
            if exc.dead_token:
                await conn.execute(
                    "UPDATE devices SET fcm_token = NULL WHERE fcm_token = %s", (token,)
                )
                log.warning("disabled a dead admin token")
            else:
                log.error("failed to send alert: %s", exc)
        except Exception as exc:
            log.error("failed to send alert: %s", exc)
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
    # Fail-closed schema check (issue #88): the service does not start if the
    # recorded schema version is LOWER than the code's requirement. Placed right
    # after the pool opens — before the first useful work.
    await assert_schema_at_least(pool)
    log.info("watchdog started, checking every %s s", CHECK_INTERVAL)

    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        while not _stop.is_set():
            try:
                await run_cycle(client)
            except Exception as exc:
                # A watchdog that crashes from its own error is worse than no
                # watchdog: it creates a false sense of supervision.
                log.error("check cycle failed: %s", exc)

            try:
                await asyncio.wait_for(_stop.wait(), timeout=CHECK_INTERVAL)
            except TimeoutError:
                pass

    await pool.close()
    log.info("watchdog stopped")


if __name__ == "__main__":
    asyncio.run(main())
