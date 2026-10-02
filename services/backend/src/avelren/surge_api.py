"""Експериментальний моніторинг; жодних запитів до єЧерги."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Header, HTTPException, Request

from .config import settings
from .db import get_pool
from .ratelimit import check as rate_check
from .schema_gate import SchemaTooOldError, assert_surge_schema
from .subscriptions_api import _device
from .surge_model import SUPPORTED_CHECKPOINTS
from .surge_schemas import SurgeStatusOut, SurgeSubscriptionIn
from .surge_store import attach_alerts, expire_alerts
from .surge_text import surge_body

router = APIRouter()


@asynccontextmanager
async def feature_connection():
    if not settings.surge_enabled:
        raise HTTPException(503, "Функція тимчасово недоступна")
    async with get_pool().connection() as conn:
        try:
            await assert_surge_schema(conn)
        except SchemaTooOldError as exc:
            raise HTTPException(503, "Функція ще не встановлена на сервері") from exc
        yield conn


async def status(conn, checkpoint_id: int, now: datetime) -> SurgeStatusOut:
    exists = await (
        await conn.execute("SELECT 1 FROM checkpoints WHERE id=%s", (checkpoint_id,))
    ).fetchone()
    if not exists:
        raise HTTPException(404, "КПП не знайдено")
    latest = await (
        await conn.execute(
            (
                "SELECT time FROM observations WHERE checkpoint_id=%s AND time "
                "BETWEEN %s AND %s ORDER BY time DESC LIMIT 1"
            ),
            (checkpoint_id, now - timedelta(minutes=3), now),
        )
    ).fetchone()
    prediction = await (
        await conn.execute(
            (
                "SELECT * FROM surge_predictions WHERE checkpoint_id=%s ORDER BY "
                "issued_at DESC LIMIT 1"
            ),
            (checkpoint_id,),
        )
    ).fetchone()
    episodes = await (
        await conn.execute(
            (
                "SELECT * FROM surge_events WHERE checkpoint_id=%s AND closed_at "
                "IS NULL AND expires_at>%s"
            ),
            (checkpoint_id, now),
        )
    ).fetchall()
    supported = checkpoint_id in SUPPORTED_CHECKPOINTS
    data = {
        "checkpoint_id": checkpoint_id,
        "status": "unavailable",
        "forecast_supported": supported,
        "reason": "missing_prediction" if supported else "unsupported",
    }
    if prediction:
        for key in ("issued_at", "window_start", "window_end", "model_version"):
            data[key] = prediction[key]
        data["reason"] = prediction["reason"]
        if now - prediction["issued_at"] >= timedelta(minutes=65):
            data["reason"] = "prediction_expired"
        if (
            prediction["score"] is not None
            and latest
            and now - prediction["issued_at"] < timedelta(minutes=65)
        ):
            data["status"] = "no_signal"
    if not latest:
        data["reason"] = "stale"
        return SurgeStatusOut(**data)
    fact = next((e for e in episodes if e["kind"] == "surge_started"), None)
    forecast = next((e for e in episodes if e["kind"] == "surge_forecast"), None)
    if fact:
        data.update(
            status="started", reason=None, expires_at=fact["expires_at"], growth_5m=fact["growth"]
        )
    elif forecast:
        data.update(status="risk", reason=None, expires_at=forecast["expires_at"])
    return SurgeStatusOut(**data)


@router.get("/surge/checkpoints")
async def checkpoints(request: Request):
    rate_check(request, "read")
    now = datetime.now(UTC)
    async with feature_connection() as conn:
        rows = await (
            await conn.execute(
                """
            SELECT c.id AS checkpoint_id,c.title,c.flag_emoji,c.country_name,
                (SELECT o.time FROM observations o WHERE o.checkpoint_id=c.id
                 AND o.time BETWEEN %s AND %s ORDER BY o.time DESC LIMIT 1) AS observed_at
            FROM checkpoints c ORDER BY c.country_name NULLS LAST,c.title,c.id
        """,
                (now - timedelta(minutes=3), now),
            )
        ).fetchall()
        return [
            {
                **r,
                "forecast_supported": r["checkpoint_id"] in SUPPORTED_CHECKPOINTS,
                "fact_supported": True,
                "data_fresh": r["observed_at"] is not None,
            }
            for r in rows
        ]


@router.get("/surge/{checkpoint_id}", response_model=SurgeStatusOut)
async def checkpoint_status(request: Request, checkpoint_id: int):
    rate_check(request, "read")
    async with feature_connection() as conn:
        return await status(conn, checkpoint_id, datetime.now(UTC))


@router.get("/surge-subscriptions")
async def subscriptions(
    request: Request,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
):
    rate_check(request, "read")
    device = await _device(x_device_id, x_device_secret)
    now = datetime.now(UTC)
    async with feature_connection() as conn:
        rows = await (
            await conn.execute(
                (
                    "SELECT s.*,c.title FROM surge_subscriptions s JOIN checkpoints c "
                    "ON c.id=s.checkpoint_id WHERE device_id=%s ORDER BY c.title"
                ),
                (device,),
            )
        ).fetchall()
        alerts = await (
            await conn.execute(
                """
            SELECT a.id AS surge_alert_id,a.event_id,e.checkpoint_id,e.kind,e.expires_at,
                e.growth AS growth_5m,c.title FROM surge_alerts a
            JOIN surge_events e ON e.id=a.event_id JOIN checkpoints c ON c.id=e.checkpoint_id
            WHERE a.device_id=%s AND a.status='pending' AND e.closed_at IS NULL AND e.expires_at>%s
        """,
                (device, now),
            )
        ).fetchall()
        for alert in alerts:
            alert["body"] = surge_body(alert["kind"], alert["checkpoint_id"], alert["title"])
            alert["experimental"] = True
        for row in rows:
            row["device_id"] = str(row["device_id"])
            row["alerts"] = [a for a in alerts if a["checkpoint_id"] == row["checkpoint_id"]]
        return rows


async def subscription_events(conn, checkpoint_id: int, now: datetime):
    rows = await (
        await conn.execute(
            (
                "SELECT id FROM surge_events WHERE checkpoint_id=%s AND closed_at "
                "IS NULL AND expires_at>%s"
            ),
            (checkpoint_id, now),
        )
    ).fetchall()
    return [r["id"] for r in rows]


@router.put("/surge-subscriptions/{checkpoint_id}")
async def put_subscription(
    request: Request,
    checkpoint_id: int,
    body: SurgeSubscriptionIn,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
):
    rate_check(request, "write")
    device = await _device(x_device_id, x_device_secret)
    now = datetime.now(UTC)
    async with feature_connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(163514,%s)", (checkpoint_id,))
            if not await (
                await conn.execute("SELECT 1 FROM checkpoints WHERE id=%s", (checkpoint_id,))
            ).fetchone():
                raise HTTPException(404, "КПП не знайдено")
            if body.forecast_enabled and checkpoint_id not in SUPPORTED_CHECKPOINTS:
                raise HTTPException(
                    422,
                    "Для цього КПП прогноз ще недоступний; фактичне зростання можна відстежувати",
                )
            d = await (
                await conn.execute(
                    "SELECT notification_capabilities FROM devices WHERE id=%s", (device,)
                )
            ).fetchone()
            if "surge_v1" not in d["notification_capabilities"]:
                raise HTTPException(409, "Потрібне оновлення застосунку")
            await conn.execute(
                """
                INSERT INTO surge_subscriptions
                    (device_id,checkpoint_id,forecast_enabled,fact_enabled)
                VALUES(%s,%s,%s,%s) ON CONFLICT(device_id,checkpoint_id) DO UPDATE
                SET forecast_enabled=excluded.forecast_enabled,fact_enabled=excluded.fact_enabled,
                    updated_at=now()
            """,
                (device, checkpoint_id, body.forecast_enabled, body.fact_enabled),
            )
            for event_id in await subscription_events(conn, checkpoint_id, now):
                await attach_alerts(conn, event_id, now)
    return {"status": "ok"}


@router.delete("/surge-subscriptions/{checkpoint_id}")
async def delete_subscription(
    request: Request,
    checkpoint_id: int,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
):
    rate_check(request, "write")
    device = await _device(x_device_id, x_device_secret)
    now = datetime.now(UTC)
    async with feature_connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(163514,%s)", (checkpoint_id,))
            await conn.execute(
                "DELETE FROM surge_subscriptions WHERE device_id=%s AND checkpoint_id=%s",
                (device, checkpoint_id),
            )
            for event_id in await subscription_events(conn, checkpoint_id, now):
                await expire_alerts(conn, event_id, now, invalid_only=True)
    return {"status": "ok"}


@router.post("/surge-alerts/{alert_id}/ack")
async def acknowledge(
    request: Request,
    alert_id: int,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
):
    rate_check(request, "write")
    device = await _device(x_device_id, x_device_secret)
    async with feature_connection() as conn:
        async with conn.transaction():
            alert = await (
                await conn.execute(
                    (
                        "SELECT a.id,e.checkpoint_id FROM surge_alerts a JOIN "
                        "surge_events e ON e.id=a.event_id WHERE a.id=%s AND "
                        "a.device_id=%s"
                    ),
                    (alert_id, device),
                )
            ).fetchone()
            if not alert:
                raise HTTPException(404, "Повідомлення не знайдено")
            await conn.execute("SELECT pg_advisory_xact_lock(163514,%s)", (alert["checkpoint_id"],))
            # Lock is shared with worker/subscriptions. Do not ACK a removed row.
            row = await (
                await conn.execute(
                    (
                        "UPDATE surge_alerts SET status='acknowledged',"
                        "acknowledged_at=COALESCE(acknowledged_at,now()) WHERE id=%s AND "
                        "device_id=%s RETURNING id"
                    ),
                    (alert_id, device),
                )
            ).fetchone()
            if not row:
                raise HTTPException(404, "Повідомлення не знайдено")
            await conn.execute(
                """
                INSERT INTO notification_cancels(kind,alert_id,device_id)
                SELECT e.kind,a.id,a.device_id FROM surge_alerts a
                JOIN surge_events e ON e.id=a.event_id WHERE a.id=%s
                ON CONFLICT(kind,alert_id) DO NOTHING
            """,
                (alert_id,),
            )
    return {"status": "ok"}
