import logging
from datetime import datetime

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import settings
from .models import Country, WorkloadItem

log = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None

# Upper bound on pool connections. Kept as a constant because it governs the
# headroom for cheap endpoints: the expensive concurrency gate must be SMALLER
# than this number (see Settings.api_max_concurrent_expensive), otherwise
# expensive reads would grab every connection and starve health/workload.
POOL_MAX_SIZE = 5


def get_pool(statement_timeout_ms: int | None = None) -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        kwargs: dict = {"row_factory": dict_row}
        if statement_timeout_ms is not None:
            # Applied per-connection only for THIS process's pool (the API
            # enables it in lifespan). collector/notifier/watchdog create their
            # own pool without the parameter and get no timeout — this is not a
            # global DB policy.
            kwargs["options"] = f"-c statement_timeout={int(statement_timeout_ms)}"
        _pool = AsyncConnectionPool(
            settings.database_dsn,
            min_size=1,
            max_size=POOL_MAX_SIZE,
            # In short: the collector cycle has 60s for everything, and waiting
            # for a connection must not eat into that budget — otherwise the
            # cycle vanishes without a trace.
            timeout=5,
            open=False,
            kwargs=kwargs,
        )
    return _pool


async def upsert_countries(conn: AsyncConnection, countries: list[Country]) -> None:
    await conn.cursor().executemany(
        """
        INSERT INTO countries (id, name, flag_emoji)
        VALUES (%s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            name       = EXCLUDED.name,
            flag_emoji = EXCLUDED.flag_emoji,
            last_seen  = now()
        """,
        [(c.id, c.name, c.flag_emoji) for c in countries],
    )


async def upsert_checkpoints(
    conn: AsyncConnection, items: list[WorkloadItem], countries: list[Country]
) -> None:
    """The reference list is alive: names and coordinates change, new points appear.

    `last_seen` is updated every cycle — it is what keeps the list current
    without manual intervention, and vanished points drop off on their own.
    """
    by_id = {c.id: c for c in countries}

    await conn.cursor().executemany(
        """
        INSERT INTO checkpoints
            (id, title, country_id, country_name, flag_emoji,
             for_vehicle_type, queue_flow, cancel_after, lat, lng)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            title        = EXCLUDED.title,
            country_id   = EXCLUDED.country_id,
            country_name = COALESCE(EXCLUDED.country_name, checkpoints.country_name),
            flag_emoji   = COALESCE(EXCLUDED.flag_emoji,   checkpoints.flag_emoji),
            queue_flow   = EXCLUDED.queue_flow,
            cancel_after = EXCLUDED.cancel_after,
            lat          = EXCLUDED.lat,
            lng          = EXCLUDED.lng,
            last_seen    = now()
        """,
        [
            (
                i.id,
                i.title,
                i.country_id,
                by_id[i.country_id].name if i.country_id in by_id else None,
                by_id[i.country_id].flag_emoji if i.country_id in by_id else None,
                i.for_vehicle_type,
                i.queue_flow,
                i.cancel_after,
                i.lat,
                i.lng,
            )
            for i in items
        ],
    )


async def insert_observations(
    conn: AsyncConnection, at: datetime, items: list[WorkloadItem]
) -> int:
    """All observations of a single cycle share one timestamp — this keeps the
    series of different points aligned."""
    await conn.cursor().executemany(
        """
        INSERT INTO observations
            (time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (checkpoint_id, time) DO NOTHING
        """,
        [(at, i.id, i.wait_time, i.vehicles_in_queue, i.is_paused) for i in items],
    )
    return len(items)


async def record_run(
    conn: AsyncConnection,
    at: datetime,
    http_status: int | None,
    duration_ms: int,
    body_sha256: str | None,
    rows_written: int,
    error: str | None,
) -> None:
    await conn.execute(
        """
        INSERT INTO collector_runs
            (time, http_status, duration_ms, body_sha256, rows_written, error)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (time) DO NOTHING
        """,
        (at, http_status, duration_ms, body_sha256, rows_written, error),
    )


async def record_derived(conn: AsyncConnection, at: datetime, error: str | None) -> None:
    """Status of the secondary phase (alerts/ETA) of the same cycle (OBS-1).

    Written in a SEPARATE transaction after the primary commit, into the same
    collector_runs row. `error=None` — the phase ran (even if there was no
    work); text — it failed, and this is exactly what the watchdog must see.
    """
    await conn.execute(
        """
        UPDATE collector_runs
        SET derived_processed_at = now(),
            derived_error = %s
        WHERE time = %s
        """,
        (error, at),
    )
