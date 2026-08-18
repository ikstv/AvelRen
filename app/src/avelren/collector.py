import asyncio
import logging
import signal
from datetime import UTC, datetime

import httpx

from . import alerts, eta
from .config import settings, validate_collector_settings
from .db import (
    get_pool,
    insert_observations,
    record_derived,
    record_run,
    upsert_checkpoints,
    upsert_countries,
)
from .echerha import fetch_workload
from .schema_gate import assert_schema_at_least

log = logging.getLogger("avelren.collector")

_stop = asyncio.Event()


def _request_stop(*_: object) -> None:
    log.info("stop signal received, finishing the current cycle")
    _stop.set()


async def run_cycle(client: httpx.AsyncClient) -> None:
    at = datetime.now(UTC).replace(microsecond=0)
    result = await fetch_workload(client)

    rows = 0
    error = result.error

    # The scope for now is trucks only; the source may mix in other types.
    items = (
        [i for i in result.response.data if i.for_vehicle_type == settings.echerha_vehicle_type]
        if result.response is not None
        else []
    )

    countries = result.response.filters.countries if result.response is not None else []

    # The primary write (observations + journal) is committed SEPARATELY from
    # the alert logic. Otherwise a failure of the secondary — say, an error in
    # eta.evaluate — would roll back the most valuable thing: the per-minute
    # observation, which the source will not give a second time (audit R-06).
    try:
        async with get_pool().connection() as conn:
            if items:
                await upsert_countries(conn, countries)
                await upsert_checkpoints(conn, items, countries)
                rows = await insert_observations(conn, at, items)
            await record_run(
                conn, at, result.http_status, result.duration_ms, result.body_sha256, rows, error
            )
        if rows:
            log.info("cycle ok: %s queues written", rows)
    except Exception as exc:  # DB is down — not a reason to kill the collector
        # There is nowhere to record the reason, so the log is this cycle's only trace.
        log.error("cycle %s lost, DB unavailable: %s", at.isoformat(), exc)
        return

    # Alerts are a separate transaction: their failure costs at most a delayed
    # notification, which the next cycle makes up for. The observation is already
    # in the DB (we do not roll back the R-06 split). But now the result of this
    # phase is durable: previously a failure went only to the log, and the
    # watchdog did not see it — the secondary pipeline could quietly die while
    # observations stayed fresh (audit OBS-1).
    try:
        async with get_pool().connection() as conn:
            if items:
                await alerts.evaluate(conn, items)
                await alerts.expire_stale(conn)
                await eta.evaluate(conn, at, items)
                await eta.expire_passed(conn)
            # An empty cycle is also successfully processed: there was no work.
            await record_derived(conn, at, error=None)
    except Exception as exc:
        log.error("alerts for cycle %s skipped: %s", at.isoformat(), exc)
        # Separate transaction: the previous one rolled back, we write the status
        # on a clean connection so the watchdog sees exactly the derived error.
        try:
            async with get_pool().connection() as conn:
                await record_derived(conn, at, error=str(exc)[:500])
        except Exception as exc2:
            log.error("failed to record derived error for cycle %s: %s", at.isoformat(), exc2)


async def main() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    validate_collector_settings(settings)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _request_stop)

    pool = get_pool()
    await pool.open(wait=True, timeout=30)
    # Fail-closed schema check (issue #88): the service does not start if the
    # recorded schema version is LOWER than the code's requirement. Placed right
    # after the pool opens — before the first useful work.
    await assert_schema_at_least(pool)
    log.info(
        "collector started: %s, interval %s s",
        settings.workload_url,
        settings.poll_interval_seconds,
    )

    interval = settings.poll_interval_seconds
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        # Count from cycle starts, not after the work — otherwise the interval drifts.
        next_start = loop.time()
        while not _stop.is_set():
            await run_cycle(client)

            next_start += interval
            delay = next_start - loop.time()
            if delay < 0:
                # The cycle did not fit the interval: we do not catch up, we realign.
                log.warning("cycle exceeded the interval by %.1f s", -delay)
                next_start = loop.time() + interval
                delay = interval
            try:
                await asyncio.wait_for(_stop.wait(), timeout=delay)
            except TimeoutError:
                pass

    await pool.close()
    log.info("collector stopped")


if __name__ == "__main__":
    asyncio.run(main())
