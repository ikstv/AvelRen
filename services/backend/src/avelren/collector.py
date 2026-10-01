"""One source poll every 60 seconds, independently of PostgreSQL replay."""

import asyncio
import logging
import signal
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import httpx
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .collector_replay import ReplayConflict, replay_loop
from .collector_spool import SpoolStore
from .config import settings, validate_collector_settings
from .echerha import fetch_workload
from .schema_gate import assert_schema_at_least

log = logging.getLogger("avelren.collector")
SPOOL_PATH = Path("/var/lib/avelren/collector-spool/cycles.sqlite3")
_stop = asyncio.Event()


def _request_stop(*_: object) -> None:
    log.info("stop signal received, finishing the current cycle")
    _stop.set()


async def run_cycle(client: httpx.AsyncClient, store: SpoolStore) -> None:
    """Capture before any DB activity; never fetch twice after a write failure."""
    at = datetime.now(UTC).replace(microsecond=0)
    seq = store.begin(at)
    result = await fetch_workload(client)
    store.finish(seq, result, settings.echerha_vehicle_type)
    log.info("cycle %s captured in spool as %s", at.isoformat(), seq)


async def poll_loop(
    client: httpx.AsyncClient,
    store: SpoolStore,
    stop: asyncio.Event,
    clock: Callable[[], float] | None = None,
) -> None:
    """Measure 60 seconds between starts, with no catch-up source requests."""
    loop = asyncio.get_running_loop()
    clock = clock or loop.time
    next_start = clock()
    while not stop.is_set():
        await run_cycle(client, store)
        next_start += settings.poll_interval_seconds
        delay = next_start - clock()
        if delay < 0:
            log.warning("cycle exceeded the interval by %.1f s", -delay)
            next_start = clock() + settings.poll_interval_seconds
            delay = settings.poll_interval_seconds
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            pass


def _new_writer_pool() -> AsyncConnectionPool:
    return AsyncConnectionPool(
        settings.database_dsn, min_size=1, max_size=1, timeout=5,
        open=False, kwargs={"row_factory": dict_row},
    )


async def stop_writer(pool: AsyncConnectionPool, task: asyncio.Task, store: SpoolStore) -> None:
    """Acknowledge capture-only only after the DB task and pool are closed."""
    task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await task
    await pool.close()
    store.set_mode_ack(True)


async def _wait_for_change(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def writer_supervisor(store: SpoolStore, stop: asyncio.Event) -> None:
    """Database failures pause only replay; producer remains scheduled."""
    pool: AsyncConnectionPool | None = None
    writer: asyncio.Task | None = None
    conflict_blocked = False
    try:
        while not stop.is_set():
            if store.capture_only():
                conflict_blocked = False
                if pool is not None and writer is not None:
                    await stop_writer(pool, writer, store)
                    pool = writer = None
                elif store.status().mode_ack is not True:
                    store.set_mode_ack(True)
            else:
                if writer is not None and writer.done():
                    error = writer.exception()
                    if error:
                        store.record_replay_error(str(error))
                        log.critical("DB writer stopped: %s", error)
                        if isinstance(error, ReplayConflict):
                            conflict_blocked = True
                    await pool.close()
                    pool = writer = None
                if conflict_blocked:
                    await _wait_for_change(stop, 1)
                    continue
                if pool is None:
                    candidate = None
                    try:
                        candidate = _new_writer_pool()
                        await candidate.open(wait=True, timeout=5)
                        await assert_schema_at_least(candidate)
                    except Exception as exc:
                        log.error("DB writer unavailable; capture continues: %s", exc)
                        store.record_replay_error(str(exc))
                        if candidate is not None:
                            await candidate.close()
                        await _wait_for_change(stop, 5)
                        continue
                    pool = candidate
                    writer = asyncio.create_task(replay_loop(store, pool, stop))
                if store.status().mode_ack is not False:
                    store.set_mode_ack(False)
            await _wait_for_change(stop, 0.25)
    finally:
        if writer is not None:
            if not writer.done():
                writer.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await writer
            else:
                with suppress(asyncio.CancelledError, Exception):
                    writer.result()
        if pool is not None:
            await pool.close()


async def main() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    validate_collector_settings(settings)
    store = SpoolStore(SPOOL_PATH)
    store.recover_started()
    store.prune_acked(datetime.now(UTC))
    _stop.clear()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _request_stop)
    log.info(
        "collector started: %s, interval %s s",
        settings.workload_url, settings.poll_interval_seconds,
    )

    supervisor = asyncio.create_task(writer_supervisor(store, _stop))
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            await poll_loop(client, store, _stop)
    finally:
        _stop.set()
        supervisor.cancel()
        with suppress(asyncio.CancelledError):
            await supervisor
        store.close()
        log.info("collector stopped")


if __name__ == "__main__":
    asyncio.run(main())
