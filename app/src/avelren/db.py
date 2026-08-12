import logging
from datetime import datetime

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import settings
from .models import Country, WorkloadItem

log = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None


def get_pool(statement_timeout_ms: int | None = None) -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        kwargs: dict = {"row_factory": dict_row}
        if statement_timeout_ms is not None:
            # Застосовується per-connection лише для пулу ЦЬОГО процесу (API його
            # вмикає в lifespan). collector/notifier/watchdog створюють свій пул
            # без параметра й timeout не отримують — це не глобальна політика БД.
            kwargs["options"] = f"-c statement_timeout={int(statement_timeout_ms)}"
        _pool = AsyncConnectionPool(
            settings.database_dsn,
            min_size=1,
            max_size=5,
            # Коротко: цикл збирача має 60 с на все, і чекання з'єднання не
            # сміє з'їдати цей бюджет — інакше цикл зникає без сліду.
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
    """Довідник живий: назви й координати змінюються, нові пункти з'являються.

    `last_seen` оновлюється щоциклу — саме за ним список лишається актуальним
    без ручного втручання, і зниклі пункти самі відпадають.
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


async def record_derived(conn: AsyncConnection, at: datetime, error: str | None) -> None:
    """Статус вторинної фази (alerts/ETA) того самого циклу (OBS-1).

    Пишеться ОКРЕМОЮ транзакцією після primary-коміту, у той самий рядок
    collector_runs. `error=None` — фаза відпрацювала (навіть якщо роботи не
    було); текст — впала, і саме це має побачити watchdog.
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
