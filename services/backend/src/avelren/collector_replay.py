"""FIFO transfer from the durable local spool to PostgreSQL.

This module never contacts the upstream source. Existing rows are read back
before acknowledgement because INSERT ... ON CONFLICT DO NOTHING is not proof
that a retry wrote the same observation.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from . import alerts, eta
from .collector_spool import CapturedCycle, SpoolStore
from .db import (
    insert_observations,
    record_derived,
    record_run,
    upsert_checkpoints,
    upsert_countries,
)
from .echerha import describe_exception

log = logging.getLogger(__name__)
DELAYED_REPLAY_ERROR = "delayed_replay_over_120s: derived alerts skipped"


class ReplayConflict(RuntimeError):
    """PostgreSQL has different data for a cycle's original timestamp."""


async def _cycle_exists(conn: AsyncConnection, at: datetime) -> bool:
    row = await (
        await conn.execute("SELECT time FROM collector_runs WHERE time=%s FOR UPDATE", (at,))
    ).fetchone()
    return row is not None


async def verify_committed_cycle(conn: AsyncConnection, cycle: CapturedCycle) -> None:
    """Verify every persisted primary field and observation, not row counts alone."""
    run = await (
        await conn.execute(
            """SELECT http_status,duration_ms,body_sha256,rows_written,error
               FROM collector_runs WHERE time=%s""",
            (cycle.at,),
        )
    ).fetchone()
    expected_run = (
        cycle.http_status, cycle.duration_ms, cycle.body_sha256, len(cycle.items), cycle.error
    )
    if run is None or tuple(run[name] for name in (
        "http_status", "duration_ms", "body_sha256", "rows_written", "error"
    )) != expected_run:
        raise ReplayConflict(f"collector_runs mismatch at {cycle.at.isoformat()}")

    rows = await (
        await conn.execute(
            """SELECT checkpoint_id,wait_time_seconds,vehicles_in_queue,is_paused
               FROM observations WHERE time=%s ORDER BY checkpoint_id""",
            (cycle.at,),
        )
    ).fetchall()
    actual = [tuple(row[name] for name in (
        "checkpoint_id", "wait_time_seconds", "vehicles_in_queue", "is_paused"
    )) for row in rows]
    expected = sorted(
        (item.id, item.wait_time, item.vehicles_in_queue, item.is_paused)
        for item in cycle.items
    )
    if actual != expected:
        raise ReplayConflict(f"observations mismatch at {cycle.at.isoformat()}")


async def _derived_processed(conn: AsyncConnection, at: datetime) -> bool:
    row = await (
        await conn.execute("SELECT derived_processed_at FROM collector_runs WHERE time=%s", (at,))
    ).fetchone()
    return row is not None and row["derived_processed_at"] is not None


async def replay_once(store: SpoolStore, pool: AsyncConnectionPool, now: datetime) -> bool:
    """Replay the oldest cycle, returning False only if paused or empty."""
    replay_started = time.monotonic()
    if store.capture_only():
        return False
    cycle = store.next_pending()
    if cycle is None:
        return False

    # Primary rows must commit together, then be read back in a new transaction.
    async with pool.connection() as conn:
        if await _cycle_exists(conn, cycle.at):
            # Crash after commit-before-ack: verify before any new mutation.
            await verify_committed_cycle(conn, cycle)
        else:
            if cycle.items:
                await upsert_countries(conn, list(cycle.countries))
                await upsert_checkpoints(conn, list(cycle.items), list(cycle.countries))
                await insert_observations(conn, cycle.at, list(cycle.items))
            await record_run(
                conn, cycle.at, cycle.http_status, cycle.duration_ms, cycle.body_sha256,
                len(cycle.items), cycle.error,
            )
    async with pool.connection() as conn:
        await verify_committed_cycle(conn, cycle)
        processed = await _derived_processed(conn, cycle.at)

    if not processed:
        age_seconds = (now - cycle.at).total_seconds() + (time.monotonic() - replay_started)
        if age_seconds > 120:
            async with pool.connection() as conn:
                await record_derived(conn, cycle.at, error=DELAYED_REPLAY_ERROR)
        else:
            try:
                async with pool.connection() as conn:
                    if cycle.items:
                        await alerts.evaluate(conn, list(cycle.items))
                        await alerts.expire_stale(conn)
                        await eta.evaluate(conn, cycle.at, list(cycle.items))
                        await eta.expire_passed(conn)
                    await record_derived(conn, cycle.at, error=None)
            except Exception as exc:
                log.error("derived phase for %s failed: %s", cycle.at.isoformat(), exc)
                async with pool.connection() as conn:
                    await record_derived(conn, cycle.at, error=describe_exception(exc)[:500])
    store.ack(cycle.seq)
    store.prune_acked(now)
    store.record_replay_error(None)
    return True


async def replay_loop(store: SpoolStore, pool: AsyncConnectionPool, stop: asyncio.Event) -> None:
    """One writer, bounded DB-only retry, no upstream requests."""
    backoff = 1.0
    while not stop.is_set():
        try:
            wrote = await replay_once(store, pool, datetime.now(UTC))
        except ReplayConflict as exc:
            store.record_replay_error(describe_exception(exc))
            log.critical("replay conflict; pending cycle retained: %s", exc)
            raise
        except Exception as exc:
            store.record_replay_error(describe_exception(exc))
            log.error("replay failed, pending cycle retained: %s", exc)
            delay = backoff
            backoff = min(backoff * 2, 30.0)
        else:
            backoff = 1.0
            delay = 0.0 if wrote else 1.0
        if delay:
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass
