import asyncio
import logging
import signal
from datetime import UTC, datetime

import httpx

from .config import settings
from .db import get_pool, insert_observations, record_run, upsert_checkpoints
from .echerha import fetch_workload

log = logging.getLogger("avelren.collector")

_stop = asyncio.Event()


def _request_stop(*_: object) -> None:
    log.info("отримано сигнал зупинки, завершуємо поточний цикл")
    _stop.set()


async def run_cycle(client: httpx.AsyncClient) -> None:
    at = datetime.now(UTC).replace(microsecond=0)
    result = await fetch_workload(client)

    rows = 0
    error = result.error

    if result.response is not None:
        # Скоуп зараз — лише вантажівки; джерело може підмішати інші типи.
        items = [
            i for i in result.response.data if i.for_vehicle_type == settings.echerha_vehicle_type
        ]
        try:
            pool = get_pool()
            async with pool.connection() as conn:
                await upsert_checkpoints(conn, items)
                rows = await insert_observations(conn, at, items)
            log.info("цикл ok: %s черг записано", rows)
        except Exception as exc:  # БД впала — не привід гасити збирач
            error = f"db: {exc}"
            log.error("запис у БД не вдався: %s", exc)

    try:
        pool = get_pool()
        async with pool.connection() as conn:
            await record_run(
                conn, at, result.http_status, result.duration_ms, result.body_sha256, rows, error
            )
    except Exception as exc:
        log.error("не вдалося записати журнал циклу: %s", exc)


async def main() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _request_stop)

    pool = get_pool()
    await pool.open(wait=True, timeout=30)
    log.info(
        "збирач стартував: %s, інтервал %s с",
        settings.workload_url,
        settings.poll_interval_seconds,
    )

    interval = settings.poll_interval_seconds
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        # Відлік від початків циклів, а не після роботи — інакше інтервал повзе.
        next_start = loop.time()
        while not _stop.is_set():
            await run_cycle(client)

            next_start += interval
            delay = next_start - loop.time()
            if delay < 0:
                # Цикл не вклався в інтервал: не наздоганяємо, а вирівнюємось.
                log.warning("цикл перевищив інтервал на %.1f с", -delay)
                next_start = loop.time() + interval
                delay = interval
            try:
                await asyncio.wait_for(_stop.wait(), timeout=delay)
            except TimeoutError:
                pass

    await pool.close()
    log.info("збирач зупинено")


if __name__ == "__main__":
    asyncio.run(main())
