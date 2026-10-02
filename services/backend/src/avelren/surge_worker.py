"""Хвилинний worker напливів; джерело даних — тільки наша БД."""

import asyncio
import logging
from datetime import UTC, datetime

from .config import settings
from .db import get_pool
from .schema_gate import assert_surge_schema
from .surge_model import MODEL_VERSION

log = logging.getLogger("avelren.surge_worker")
LOCK_ID = 1635148147


async def run_cycle(now: datetime) -> int:
    if not settings.surge_enabled:
        return 0
    from .surge_store import process_checkpoint

    pool = get_pool(statement_timeout_ms=5000)
    async with pool.connection() as conn:
        async with conn.transaction():
            await assert_surge_schema(conn)
            from psycopg.rows import tuple_row

            cursor = conn.cursor(row_factory=tuple_row)
            await cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", (LOCK_ID,))
            if not (await cursor.fetchone())[0]:
                return 0
            await cursor.execute(
                "SELECT id FROM checkpoints WHERE id IN (1,6,17,29) OR EXISTS(SELECT 1 "
                "FROM surge_subscriptions s WHERE s.checkpoint_id=checkpoints.id AND "
                "s.fact_enabled)"
            )
            checkpoints = await cursor.fetchall()
            processed = 0
            failed = 0
            for (checkpoint_id,) in checkpoints:
                try:
                    async with conn.transaction():
                        await process_checkpoint(conn, checkpoint_id, now)
                    processed += 1
                except Exception:
                    failed += 1
                    log.exception("surge checkpoint failed: %s", checkpoint_id)
    log.info(
        "surge cycle committed at=%s processed=%s failed=%s model=%s",
        now.isoformat(),
        processed,
        failed,
        MODEL_VERSION,
    )
    return processed


async def main() -> None:
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    pool = get_pool(statement_timeout_ms=5000)
    await pool.open()
    try:
        async with pool.connection() as conn:
            await assert_surge_schema(conn)
            if not settings.surge_enabled:
                from .surge_store import disable_monitoring

                await disable_monitoring(conn, datetime.now(UTC))
                return
        while True:
            start = asyncio.get_running_loop().time()
            try:
                await run_cycle(datetime.now(UTC))
            except Exception:
                log.exception("surge cycle failed")
            await asyncio.sleep(max(0, 60 - (asyncio.get_running_loop().time() - start)))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
