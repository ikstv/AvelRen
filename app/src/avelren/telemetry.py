"""Телеметрія сервера для застосунку.

Читаємо з `/proc` і файлової системи — це дає стан **хоста**, а не контейнера,
бо Docker не ізолює ці лічильники.

Свідомо **не** монтуємо `/var/run/docker.sock`: доступ до нього рівносильний
root на хості, і віддавати таке заради красивого списку контейнерів — поганий
обмін. Стан сервісів виводимо з того, що вони роблять: збирач живий, якщо
пише спостереження; розсилач живий, якщо надсилає.
"""

import os
import time
from pathlib import Path

from psycopg import AsyncConnection

# `/secrets` — bind-монтування з хоста, тож statvfs тут показує диск хоста,
# а не тонкий шар контейнера.
HOST_FS_PROBE = "/secrets"
REBOOT_FLAG = Path("/host/run/reboot-required")


def _proc(path: str) -> str:
    try:
        return Path(path).read_text()
    except OSError:
        return ""


def system() -> dict:
    load = _proc("/proc/loadavg").split()
    uptime_raw = _proc("/proc/uptime").split()

    mem: dict[str, int] = {}
    for line in _proc("/proc/meminfo").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            mem[parts[0].rstrip(":")] = int(parts[1])  # кілобайти

    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", 0)
    swap_total = mem.get("SwapTotal", 0)
    swap_free = mem.get("SwapFree", 0)

    try:
        st = os.statvfs(HOST_FS_PROBE)
        disk_total = st.f_blocks * st.f_frsize
        disk_free = st.f_bavail * st.f_frsize
    except OSError:
        disk_total = disk_free = 0

    return {
        "uptime_seconds": int(float(uptime_raw[0])) if uptime_raw else None,
        "load_1m": float(load[0]) if load else None,
        "load_5m": float(load[1]) if len(load) > 1 else None,
        "cpu_count": os.cpu_count(),
        "memory_total_mb": total // 1024,
        "memory_used_mb": (total - available) // 1024,
        "swap_total_mb": swap_total // 1024,
        "swap_used_mb": (swap_total - swap_free) // 1024,
        "disk_total_gb": round(disk_total / 1024**3, 1),
        "disk_free_gb": round(disk_free / 1024**3, 1),
        "disk_used_percent": (
            round((1 - disk_free / disk_total) * 100) if disk_total else None
        ),
        "reboot_required": REBOOT_FLAG.exists(),
        "reboot_pending_days": (
            int((time.time() - REBOOT_FLAG.stat().st_mtime) // 86400)
            if REBOOT_FLAG.exists()
            else None
        ),
    }


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
    """Лічильники мережі з /proc — накопичувальні від старту системи."""
    rx = tx = 0
    for line in _proc("/proc/net/dev").splitlines()[2:]:
        name, _, rest = line.partition(":")
        if name.strip().startswith(("lo", "docker", "br-", "veth")):
            continue
        f = rest.split()
        if len(f) >= 9:
            rx += int(f[0])
            tx += int(f[8])
    return {
        "rx_total_gb": round(rx / 1024**3, 2),
        "tx_total_gb": round(tx / 1024**3, 2),
    }


def certificate() -> dict:
    """Термін сертифіката. Caddy оновлює його сам, але мовчазний збій
    оновлення покладе застосунок — Android не ходить по простроченому TLS."""
    from datetime import UTC, datetime

    import ssl

    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(
            __import__("socket").create_connection(("api.bordersignal.pp.ua", 443), timeout=5),
            server_hostname="api.bordersignal.pp.ua",
        ) as s:
            cert = s.getpeercert()
        until = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
        return {
            "expires_at": until,
            "days_left": (until - datetime.now(UTC)).days,
            "issuer": dict(x[0] for x in cert["issuer"]).get("organizationName"),
        }
    except Exception as exc:
        return {"error": str(exc)[:120]}


def backups() -> dict:
    """Свіжість резервних копій.

    Копія, про яку ніхто не дивиться, тихо ламається й лишається зламаною
    рівно до дня, коли знадобиться.
    """
    marker = Path("/host/run/avelren-backup.stamp")
    if not marker.exists():
        return {"last_run": None, "age_hours": None}
    age = time.time() - marker.stat().st_mtime
    return {
        "last_run": marker.stat().st_mtime,
        "age_hours": round(age / 3600, 1),
        "stale": age > 36 * 3600,  # добова копія, півтора дні — вже тривожно
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
