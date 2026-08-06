"""Публічний API AvelRen.

Дані віддаються ВИКЛЮЧНО з нашої БД. Жоден ендпоінт не звертається до
echerha.gov.ua — див. AGENTS.md, правило 1.
"""

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException, Query

from .config import settings
from .db import get_pool

log = logging.getLogger("avelren.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = get_pool()
    await pool.open(wait=True, timeout=30)
    yield
    await pool.close()


app = FastAPI(title="AvelRen", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Живий сервіс з протухлими даними — теж проблема, тому міряємо свіжість."""
    async with get_pool().connection() as conn:
        row = await (await conn.execute("SELECT max(time) AS last FROM observations")).fetchone()

    last = row["last"] if row else None
    age = (datetime.now(UTC) - last).total_seconds() if last else None
    fresh = age is not None and age < settings.poll_interval_seconds * 3

    return {
        "status": "ok" if fresh else "stale",
        "last_observation": last,
        "age_seconds": int(age) if age is not None else None,
    }


@app.get("/checkpoints")
async def checkpoints() -> list[dict]:
    async with get_pool().connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT id, title, country_id, queue_flow, cancel_after, lat, lng, last_seen
                FROM checkpoints
                WHERE for_vehicle_type = %s
                ORDER BY title
                """,
                (settings.echerha_vehicle_type,),
            )
        ).fetchall()
    return rows


@app.get("/workload")
async def workload() -> list[dict]:
    """Останній зріз по кожній черзі."""
    async with get_pool().connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT DISTINCT ON (o.checkpoint_id)
                    o.checkpoint_id, c.title, c.country_id, c.lat, c.lng,
                    o.time, o.wait_time_seconds, o.vehicles_in_queue, o.is_paused
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
    checkpoint_id: int,
    hours: int = Query(24, ge=1, le=24 * 90),
) -> dict:
    """Історія пункту. За довгі періоди віддаємо погодинні агрегати —
    сирий ряд на 90 днів це 130 тисяч точок, які клієнту нема куди подіти."""
    since = datetime.now(UTC) - timedelta(hours=hours)

    async with get_pool().connection() as conn:
        cp = await (
            await conn.execute("SELECT id, title FROM checkpoints WHERE id = %s", (checkpoint_id,))
        ).fetchone()
        if cp is None:
            raise HTTPException(status_code=404, detail="Пункт пропуску не знайдено")

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
