import logging
from datetime import datetime

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import settings
from .models import WorkloadItem

log = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None


def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=5,
            # Коротко: цикл збирача має 60 с на все, і чекання з'єднання не
            # сміє з'їдати цей бюджет — інакше цикл зникає без сліду.
            timeout=5,
            open=False,
            kwargs={"row_factory": dict_row},
        )
    return _pool


async def upsert_checkpoints(conn: AsyncConnection, items: list[WorkloadItem]) -> None:
    """Довідник живий: назви й координати змінюються, нові пункти з'являються."""
    await conn.cursor().executemany(
        """
        INSERT INTO checkpoints
            (id, title, country_id, for_vehicle_type, queue_flow, cancel_after, lat, lng)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            title        = EXCLUDED.title,
            country_id   = EXCLUDED.country_id,
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
    """Усі спостереження одного циклу мають спільну мітку часу — так ряди
    різних пунктів залишаються вирівняними."""
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
