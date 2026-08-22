"""AvelRen public API.

Data is served EXCLUSIVELY from our DB. No endpoint reaches out to
echerha.gov.ua — see AGENTS.md, rule 1.
"""

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from psycopg import OperationalError
from psycopg_pool import PoolTimeout

from . import forecast, telemetry
from .config import settings
from .db import get_pool
from .limits import BodySizeLimitMiddleware, ConcurrencyGate
from .ratelimit import check as rate_check
from .schema_gate import assert_schema_at_least
from .subscriptions_api import router as subscriptions_router

log = logging.getLogger("avelren.api")

# Expensive reads (history/forecast aggregations) pass through a shared gate:
# under load they must not exhaust the pool and take down cheap health/workload
# (audit #16). Cheap endpoints do NOT pass through the gate.
_expensive_gate = ConcurrencyGate(settings.api_max_concurrent_expensive)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # statement_timeout is enabled right here: it applies only to the API process's pool.
    pool = get_pool(settings.api_statement_timeout_ms)
    await pool.open(wait=True, timeout=30)
    # Fail-closed schema check (issue #88): the service does not start if the
    # recorded schema version is LOWER than the code's requirement. Placed right
    # after the pool opens — before the first useful work.
    await assert_schema_at_least(pool)
    yield
    await pool.close()


app = FastAPI(title="AvelRen", version="0.1.0", lifespan=lifespan)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.api_max_body_bytes)
app.include_router(subscriptions_router)


@app.exception_handler(OperationalError)
@app.exception_handler(PoolTimeout)
async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """A DB crash or unavailability is a "try later", not a "server bug".

    Without this, every public GET and the body of a write endpoint after auth
    would return a raw 500, and the client could not tell temporary
    unavailability from an error. _device in subscriptions_api already maps this
    to 503 locally; here is the global safety net for the remaining paths
    (audit M-9)."""
    log.warning("DB unavailable (%s): %s", type(exc).__name__, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Service temporarily unavailable, please try again later"},
        headers={"Retry-After": "5"},
    )


@app.get("/health")
async def health() -> dict:
    """A live service with stale data is also a problem, so we measure freshness.

    `status` is about LIVENESS only (ok/stale) — it is a deploy-acceptance gate
    and a container/LB healthcheck, so nothing unrelated may lower it. The
    separate `alert_channel` key is about DELIVERY: whether the watchdog's alert
    channel can reach anyone (#113). It is read by the external monitor and MUST
    NOT affect `status` — its probe is wrapped so that a failure to compute it
    degrades to "unknown" and still returns 200 with a valid liveness reading.
    Otherwise liveness would start depending on the `devices` table it has no
    business touching.
    """
    async with get_pool().connection() as conn:
        row = await (await conn.execute("SELECT max(time) AS last FROM observations")).fetchone()
        try:
            channel = await telemetry.alert_channel(conn)
        except Exception as exc:
            log.warning("alert_channel probe failed, reporting unknown: %s", exc)
            channel = "unknown"

    last = row["last"] if row else None
    age = (datetime.now(UTC) - last).total_seconds() if last else None
    fresh = age is not None and age < settings.poll_interval_seconds * 3

    return {
        "status": "ok" if fresh else "stale",
        "last_observation": last,
        "age_seconds": int(age) if age is not None else None,
        "alert_channel": channel,
    }


@app.get("/checkpoints")
async def checkpoints(request: Request, include_stale: bool = False) -> list[dict]:
    """The list of freight checkpoints for the selection screen.

    Currency maintains itself: `last_seen` is updated every cycle, so a new 39th
    point appears here the minute after it shows up in the source, and a vanished
    one drops off. The one-day threshold keeps a short outage of our collector
    from emptying the list in the app.
    """
    rate_check(request, "read")
    async with get_pool().connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT id, title, country_id, country_name, flag_emoji,
                       queue_flow, cancel_after, lat, lng, first_seen, last_seen,
                       last_seen > now() - INTERVAL '1 day' AS is_active
                FROM checkpoints
                WHERE for_vehicle_type = %s
                  AND (%s OR last_seen > now() - INTERVAL '1 day')
                ORDER BY country_name NULLS LAST, title
                """,
                (settings.echerha_vehicle_type, include_stale),
            )
        ).fetchall()
    return rows


@app.get("/workload")
async def workload(request: Request) -> list[dict]:
    """The latest snapshot for each queue.

    `entry_eta` is the approximate entry time for someone joining the queue now.
    The formula is verified against eCherha: the measurement moment plus
    `wait_time`. For a paused queue with zero wait there is no forecast, rather
    than "entry right now", so it is `null` there.
    """
    rate_check(request, "read")
    async with get_pool().connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT DISTINCT ON (o.checkpoint_id)
                    o.checkpoint_id, c.title, c.country_id, c.country_name,
                    c.flag_emoji, c.lat, c.lng,
                    o.time, o.wait_time_seconds, o.vehicles_in_queue, o.is_paused,
                    CASE WHEN o.is_paused AND o.wait_time_seconds = 0 THEN NULL
                         ELSE o.time + (o.wait_time_seconds * INTERVAL '1 second')
                    END AS entry_eta
                FROM observations o
                JOIN checkpoints c ON c.id = o.checkpoint_id
                WHERE o.time > now() - INTERVAL '1 hour'
                ORDER BY o.checkpoint_id, o.time DESC
                """
            )
        ).fetchall()
    return rows


@app.get("/history/{checkpoint_id}")
async def history(
    request: Request,
    checkpoint_id: int,
    hours: int = Query(24, ge=1, le=24 * 90),
) -> dict:
    """A point's history. For long periods we serve hourly aggregates — a raw
    series over 90 days is 130 thousand points, which the client has nowhere to put."""
    rate_check(request, "read")
    since = datetime.now(UTC) - timedelta(hours=hours)

    async with _expensive_gate.guard(), get_pool().connection() as conn:
        cp = await (
            await conn.execute("SELECT id, title FROM checkpoints WHERE id = %s", (checkpoint_id,))
        ).fetchone()
        if cp is None:
            raise HTTPException(status_code=404, detail="Checkpoint not found")

        if hours <= 48:
            rows = await (
                await conn.execute(
                    """
                    SELECT time, wait_time_seconds, vehicles_in_queue, is_paused
                    FROM observations
                    WHERE checkpoint_id = %s AND time >= %s
                    ORDER BY time
                    """,
                    (checkpoint_id, since),
                )
            ).fetchall()
            resolution = "raw"
        else:
            rows = await (
                await conn.execute(
                    """
                    SELECT bucket AS time, avg_wait_seconds, max_wait_seconds,
                           avg_vehicles, max_vehicles, samples
                    FROM observations_hourly
                    WHERE checkpoint_id = %s AND bucket >= %s
                    ORDER BY bucket
                    """,
                    (checkpoint_id, since),
                )
            ).fetchall()
            resolution = "hourly"

    return {
        "checkpoint": cp,
        "resolution": resolution,
        "hours": hours,
        "points": rows,
    }


@app.get("/forecast/{checkpoint_id}")
async def forecast_endpoint(
    request: Request, checkpoint_id: int, hours: int = Query(24, ge=1, le=168)
) -> dict:
    """Feature #3: workload forecast.

    While there is too little history, it returns `status: collecting` and an
    empty list of points. This is deliberate: a forecast on a day's worth of data
    would look convincing and be a fabrication, and people plan trips on it.
    """
    rate_check(request, "read")
    async with _expensive_gate.guard(), get_pool().connection() as conn:
        cp = await (
            await conn.execute(
                "SELECT id, title, flag_emoji FROM checkpoints WHERE id = %s", (checkpoint_id,)
            )
        ).fetchone()
        if cp is None:
            raise HTTPException(status_code=404, detail="Checkpoint not found")

        result = await forecast.forecast(conn, checkpoint_id, hours)

    result["checkpoint"] = cp
    return result


@app.get("/forecast/{checkpoint_id}/quality")
async def forecast_quality(request: Request, checkpoint_id: int) -> dict:
    """Error of the base model. Without this number it is impossible to say
    whether a future more complex model improved anything at all."""
    rate_check(request, "read")
    async with _expensive_gate.guard(), get_pool().connection() as conn:
        return await forecast.evaluate(conn, checkpoint_id)
