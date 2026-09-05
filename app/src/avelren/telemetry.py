"""Server telemetry for the app.

**Trust boundary.** Previously this module read `/proc`, `/run`, and `/secrets`
directly from the filesystem. This meant the public API container had to have
bind-mounts to all of the above — including the directory where the Firebase
service account lives. A path-traversal bug or RCE in the API gave access to the
FCM key, even though the API itself does not need it (audit SEC-1 / A-01).

Now host-metric collection happens on the host itself
(`deploy/telemetry-snapshot.sh` under a systemd timer), the API reads just one
JSON file — and there are no secrets, proc, or run in the container. We
deliberately do not fall back to the old paths: "temporary compatibility" is the
worst way to sneak a security fix into production.

We deliberately do **not** mount `/var/run/docker.sock`: access to it is
equivalent to root on the host, and giving that away for a pretty container list
is a bad trade. We infer service state from what they do: the collector is alive
if it writes observations; the sender is alive if it sends.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from psycopg import AsyncConnection

from . import __version__ as APP_VERSION
from .config import settings

# Whitelist of fields we expose for each container. Deliberately HEAVY paranoia
# here: raw `docker inspect` contains env (may hold credentials), mounts (reveals
# secret paths), cmd, labels. We extend this set only explicitly and with a
# rationale in a comment — not "let's just add all fields".
_SERVICE_ALLOWED_FIELDS = frozenset(
    {"status", "health", "started_at", "restart_count", "exit_code", "oom_killed", "image"}
)

# Whitelist of containers we know and want to show. Anything else from the
# snapshot is ignored — so that a stray field in the JSON does not reach the client.
_SERVICE_ALLOWED_NAMES = frozenset(
    {"db", "api", "collector", "notifier", "watchdog", "caddy"}
)

# The bind-mount directory of the snapshot file. A variable for tests; in
# docker-compose /var/lib/avelren-telemetry:/telemetry:ro is mounted.
SNAPSHOT_PATH = Path(os.environ.get("AVELREN_TELEMETRY_SNAPSHOT", "/telemetry/host.json"))

# A snapshot older than 5 min is considered stale: the timer has a 1-min
# interval, so the margin is fourfold and covers a short pause without false alarms.
SNAPSHOT_MAX_AGE_SECONDS = 300


def _snapshot() -> dict:
    """Reads the latest host snapshot. An empty dict means the snapshot is absent.

    Errors do not raise an exception outward: the API handler must survive even
    if the snapshot pipeline disappears; the client will see `stale: true` instead
    of a 500.
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
        # Format from the snapshot script: ISO-8601 UTC with "Z".
        collected = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int((datetime.now(UTC) - collected).total_seconds())


def system() -> dict:
    """Host state: load, memory, disk, reboot need.

    `stale=true` means the snapshot file is older than `SNAPSHOT_MAX_AGE_SECONDS`
    or absent altogether. This is an important signal: otherwise stale numbers
    look fresh and hide a failure of the telemetry pipeline.
    """
    snap = _snapshot()
    data = dict(snap.get("system") or {})
    age = _snapshot_age_seconds(snap)
    data["snapshot_age_seconds"] = age
    data["stale"] = age is None or age > SNAPSHOT_MAX_AGE_SECONDS
    return data


async def alert_channel(conn: AsyncConnection) -> str:
    """Can the watchdog's alert channel reach anyone? (#113)

    "empty" — there is no admin device with a live FCM token, so the watchdog
    physically cannot deliver a health alert. This state is itself an alarm, but
    it cannot be delivered through the very channel that is empty — so an EXTERNAL
    black-box monitor reads this from the public /health and raises the alarm from
    outside the stack.

    A single BIT, deliberately: the exact count is admin-only telemetry (it would
    otherwise leak the size and dynamics of the admin fleet to anyone).

    This catches "empty" (no token at all), NOT "dead": an admin whose FCM token
    is present but expired reads as "ok" here — a dead token is an ack concern
    (#19), a different failure with a different fix.
    """
    row = await (
        await conn.execute(
            "SELECT count(*) FILTER (WHERE is_admin AND fcm_token IS NOT NULL) AS n FROM devices"
        )
    ).fetchone()
    return "ok" if row and row["n"] > 0 else "empty"


async def pipeline(conn: AsyncConnection) -> dict:
    """State of the data pipeline: the thing the server exists for."""
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
                (SELECT count(*) FROM devices
                  WHERE is_admin AND fcm_token IS NOT NULL)                AS admins_with_token,
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

    # We expect 60 cycles per hour. Fewer — there were gaps, and it shows
    # immediately. Completeness counts SUCCESSFUL cycles (error IS NULL), not just
    # attempts: when eCherha returns 502 every minute, collector_runs still fills
    # up (runs_last_hour → 60), but no observation is collected. Counting attempts
    # would mean showing 100% completeness during a total data-collection failure —
    # exactly what completeness is meant to protect against.
    successful = data.get("successful_runs_last_hour") or 0
    data["cycles_expected_per_hour"] = 60
    data["completeness_percent"] = min(100, round(successful / 60 * 100))

    return data


async def last_collector_run(conn: AsyncConnection) -> dict | None:
    """The collector's last cycle — success or not, including the upstream HTTP status.

    Needed so the Server Dashboard does not rely on indirect signals
    (last_observation, errors_last_hour): in the "eCherha responds 502 every
    minute" mode, observations become stale, and the reason is visible only in
    this row. We deliberately do NOT expose `body_sha256` — it is a technical
    artifact for comparing payloads, the client does not need it, and it could
    potentially speed up inferring whether there is new content upstream.
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
    """The last successful cycle. Separate from last_run — we need to distinguish
    "eCherha just returned 200, N rows saved" vs "the last cycle failed, the
    previous success was an hour ago". Without this field the dashboard shows the
    same ⚪ for "problems just started" and for "everything has been broken for a
    long time"."""
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
    """What the collector currently fetches and from where. Does not read the DB:
    the endpoint comes from settings — the source of truth for the same collector.
    The client sees the link "this URL, this is where we pull from" without
    guessing."""
    return {
        "base_url": settings.echerha_base_url,
        "workload_url": settings.workload_url,
        "vehicle_type": settings.echerha_vehicle_type,
        "poll_interval_seconds": settings.poll_interval_seconds,
    }


def services() -> list[dict]:
    """The list of containers from the snapshot. The field whitelist is applied
    HERE, not in the snapshot script: even if the host script accidentally writes
    an extra field, the API exposes nothing extra. Classic defence-in-depth — one
    careless commit in deploy/ must not open a channel for leaking env/mounts."""
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
    # Stable order — so the UI does not "jump" between compositions.
    order = ["db", "api", "collector", "notifier", "watchdog", "caddy"]
    out.sort(key=lambda s: order.index(s["name"]) if s["name"] in order else 999)
    return out


def docker() -> dict:
    """Docker daemon and compose versions from the snapshot. The goal is that the
    dashboard shows when the host lags behind the recommended version."""
    raw = _snapshot().get("docker") or {}
    if not isinstance(raw, dict):
        return {}
    return {
        "daemon_version": raw.get("daemon_version"),
        "compose_version": raw.get("compose_version"),
        # #160: whether the compose model still mounts the 001-009 migration pin.
        # A plain boolean carrying no host detail, and worth surfacing next to the
        # versions: the watchdog alerts on it, but an alert says "it broke now"
        # while the dashboard answers "is it right at this moment" — which is the
        # question anyone asks before touching migrations.
        "migrate_pin_active": raw.get("migrate_pin_active"),
    }


def inodes() -> dict:
    """Inode usage. A filesystem full by inode looks like "plenty of disk left",
    until you try to create a file. Hence separate from diskUsage."""
    raw = _snapshot().get("inodes") or {}
    if not isinstance(raw, dict):
        return {"total": None, "used": None, "used_percent": None}
    return {
        "total": raw.get("total"),
        "used": raw.get("used"),
        "used_percent": raw.get("used_percent"),
    }


async def version(conn: AsyncConnection) -> dict:
    """Identifying the app version on the server.

    - `app_version` comes from the package's `__version__` (the single source of
      truth).
    - `git_sha` — from the env `AVELREN_GIT_SHA`, which docker-build sets from
      `SOURCE_COMMIT` (see Dockerfile). In dev mode it may be absent — then null,
      not "unknown": the client must distinguish "version known, this is dev" from
      "version was there but vanished".
    - `migrations_version` — max(version) from `schema_migrations`. A fresh schema
      and stale code (or vice versa) is the main class of deploy failures.
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
    """Server traffic since system start (from the host snapshot).

    Previously the API read `/host/proc/1/net/dev` directly — this required
    mounting the entire host `/proc` into the public container. Now the counters
    come from the snapshot, collected as root on the host.
    """
    data = dict(_snapshot().get("network") or {})
    data.setdefault("rx_total_gb", 0.0)
    data.setdefault("tx_total_gb", 0.0)
    return data


def certificate() -> dict:
    """Certificate expiry (from the host snapshot).

    Previously this call did a synchronous ssl handshake directly from an async
    FastAPI handler — it blocked the event loop for seconds and gave the API an
    outward network surface. Now a host timer checks the cert, the API only reads
    the number.
    """
    return dict(_snapshot().get("certificate") or {"error": "snapshot missing"})


def backups() -> dict:
    """Backup freshness (from the host snapshot).

    A backup nobody looks at quietly breaks and stays broken right up to the day
    it is needed.
    """
    return dict(_snapshot().get("backups") or {"last_run": None, "age_hours": None})


def snapshot_problem(system_data: dict) -> dict | None:
    """A synthetic problem when the host snapshot went stale or disappeared.

    Without this, a failure of the telemetry timer would look on the phone like a
    healthy server: fields from a missing snapshot default to zeros, and the app
    even writes "No problems". A silent monitoring failure is worse than no
    monitoring, so the stale state must land in exactly the list the user reads
    first.

    The shape matches the `health_alerts` rows, so the client does not need to
    know anything about a new field — it renders this as an ordinary problem.
    """
    if not system_data.get("stale"):
        return None

    age = system_data.get("snapshot_age_seconds")
    if age is None:
        detail = "Host telemetry is not being collected: snapshot absent"
    else:
        detail = f"Host telemetry has not updated for {age // 60} min"

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
