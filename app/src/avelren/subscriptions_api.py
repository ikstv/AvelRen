"""Ендпоінти підписок, цілей і підтверджень.

Реєстрація анонімна: пристрій, а не людина. `device_id` — випадковий uuid,
який фактично працює як ключ доступу до підписок, тому передається заголовком
`X-Device-Id`, а не в URL: параметри запитів осідають у логах проксі та в
історії браузера, заголовки — ні.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, Request

from . import telemetry
from .alerts import THRESHOLDS
from .db import get_pool
from .ratelimit import check as rate_check
from .schemas import DeviceIn, DeviceOut, EtaTargetIn, SubscriptionIn, TokenIn

router = APIRouter()


async def _device(x_device_id: str | None) -> str:
    if not x_device_id:
        raise HTTPException(status_code=401, detail="Потрібен заголовок X-Device-Id")
    async with get_pool().connection() as conn:
        try:
            row = await (
                await conn.execute(
                    "UPDATE devices SET last_seen = now() WHERE id = %s RETURNING id",
                    (x_device_id,),
                )
            ).fetchone()
        except Exception:  # не-uuid у заголовку
            raise HTTPException(status_code=400, detail="Некоректний X-Device-Id") from None
    if row is None:
        raise HTTPException(status_code=404, detail="Пристрій не знайдено")
    return str(row["id"])


@router.get("/thresholds")
async def thresholds() -> dict:
    return {"thresholds": THRESHOLDS}


@router.post("/devices", status_code=201)
async def create_device(request: Request, body: DeviceIn) -> DeviceOut:
    rate_check(request, "write")
    async with get_pool().connection() as conn:
        # Перевстановлення застосунку дає новий токен, але повторний запуск із
        # тим самим токеном не має плодити пристроїв-двійників.
        row = await (
            await conn.execute(
                """
                INSERT INTO devices (fcm_token, platform)
                VALUES (%s, %s)
                ON CONFLICT (fcm_token) DO UPDATE SET last_seen = now()
                RETURNING id
                """,
                (body.fcm_token, body.platform),
            )
        ).fetchone()
    return DeviceOut(device_id=str(row["id"]))


@router.put("/devices/token")
async def update_token(body: TokenIn, x_device_id: str | None = Header(None)) -> dict:
    device_id = await _device(x_device_id)
    async with get_pool().connection() as conn:
        await conn.execute(
            "UPDATE devices SET fcm_token = %s, last_seen = now() WHERE id = %s",
            (body.fcm_token, device_id),
        )
    return {"status": "ok"}


# --- Функція №1: пороги ---------------------------------------------------


@router.get("/subscriptions")
async def list_subscriptions(x_device_id: str | None = Header(None)) -> list[dict]:
    device_id = await _device(x_device_id)
    async with get_pool().connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT s.id, s.checkpoint_id, c.title, c.flag_emoji, c.country_name,
                       s.threshold, s.is_active, s.created_at,
                       (SELECT a.id FROM alerts a
                        WHERE a.subscription_id = s.id AND a.status = 'pending'
                        LIMIT 1) AS pending_alert_id
                FROM subscriptions s
                JOIN checkpoints c ON c.id = s.checkpoint_id
                WHERE s.device_id = %s
                ORDER BY c.title, s.threshold
                """,
                (device_id,),
            )
        ).fetchall()
    return rows


@router.post("/subscriptions", status_code=201)
async def create_subscription(
    request: Request, body: SubscriptionIn, x_device_id: str | None = Header(None)
) -> dict:
    rate_check(request, "write")
    if body.threshold not in THRESHOLDS:
        raise HTTPException(status_code=422, detail=f"Поріг має бути одним із {THRESHOLDS}")
    device_id = await _device(x_device_id)

    async with get_pool().connection() as conn:
        exists = await (
            await conn.execute("SELECT 1 FROM checkpoints WHERE id = %s", (body.checkpoint_id,))
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="Пункт пропуску не знайдено")

        row = await (
            await conn.execute(
                """
                INSERT INTO subscriptions (device_id, checkpoint_id, threshold)
                VALUES (%s, %s, %s)
                ON CONFLICT (device_id, checkpoint_id, threshold)
                    DO UPDATE SET is_active = true
                RETURNING id
                """,
                (device_id, body.checkpoint_id, body.threshold),
            )
        ).fetchone()
    return {"id": row["id"]}


@router.delete("/subscriptions/{subscription_id}", status_code=204)
async def delete_subscription(subscription_id: int, x_device_id: str | None = Header(None)) -> None:
    device_id = await _device(x_device_id)
    async with get_pool().connection() as conn:
        row = await (
            await conn.execute(
                "DELETE FROM subscriptions WHERE id = %s AND device_id = %s RETURNING id",
                (subscription_id, device_id),
            )
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Підписку не знайдено")


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(alert_id: int, x_device_id: str | None = Header(None)) -> dict:
    """Кнопка «ОК». Після неї повтори припиняються назавжди."""
    device_id = await _device(x_device_id)
    async with get_pool().connection() as conn:
        row = await (
            await conn.execute(
                """
                UPDATE alerts a
                SET status = 'acknowledged', acknowledged_at = now()
                FROM subscriptions s
                WHERE a.id = %s AND a.subscription_id = s.id
                  AND s.device_id = %s AND a.status = 'pending'
                RETURNING a.id
                """,
                (alert_id, device_id),
            )
        ).fetchone()
    # Повторне підтвердження не помилка: користувач міг натиснути двічі, а
    # застосунок — повторити запит після втрати мережі.
    return {"status": "acknowledged" if row else "already_closed"}


# --- Функція №2: цільовий час в'їзду --------------------------------------


@router.get("/eta-targets")
async def list_eta_targets(x_device_id: str | None = Header(None)) -> list[dict]:
    device_id = await _device(x_device_id)
    async with get_pool().connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT t.id, t.checkpoint_id, c.title, c.flag_emoji, c.country_name,
                       t.target_at, t.tolerance_seconds, t.is_active, t.created_at,
                       (SELECT a.id FROM eta_alerts a
                        WHERE a.target_id = t.id AND a.status = 'pending'
                        LIMIT 1) AS pending_alert_id
                FROM eta_targets t
                JOIN checkpoints c ON c.id = t.checkpoint_id
                WHERE t.device_id = %s
                ORDER BY t.target_at
                """,
                (device_id,),
            )
        ).fetchall()
    return rows


@router.post("/eta-targets", status_code=201)
async def create_eta_target(
    request: Request, body: EtaTargetIn, x_device_id: str | None = Header(None)
) -> dict:
    rate_check(request, "write")
    if body.target_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="Цільовий час має бути в майбутньому")
    device_id = await _device(x_device_id)

    async with get_pool().connection() as conn:
        exists = await (
            await conn.execute("SELECT 1 FROM checkpoints WHERE id = %s", (body.checkpoint_id,))
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="Пункт пропуску не знайдено")

        row = await (
            await conn.execute(
                """
                INSERT INTO eta_targets
                    (device_id, checkpoint_id, target_at, tolerance_seconds)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (device_id, checkpoint_id, target_at)
                    DO UPDATE SET is_active = true,
                                  tolerance_seconds = EXCLUDED.tolerance_seconds
                RETURNING id
                """,
                (device_id, body.checkpoint_id, body.target_at, body.tolerance_seconds),
            )
        ).fetchone()
    return {"id": row["id"]}


@router.delete("/eta-targets/{target_id}", status_code=204)
async def delete_eta_target(target_id: int, x_device_id: str | None = Header(None)) -> None:
    device_id = await _device(x_device_id)
    async with get_pool().connection() as conn:
        row = await (
            await conn.execute(
                "DELETE FROM eta_targets WHERE id = %s AND device_id = %s RETURNING id",
                (target_id, device_id),
            )
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Ціль не знайдено")


@router.post("/eta-alerts/{alert_id}/ack")
async def acknowledge_eta_alert(alert_id: int, x_device_id: str | None = Header(None)) -> dict:
    device_id = await _device(x_device_id)
    async with get_pool().connection() as conn:
        row = await (
            await conn.execute(
                """
                UPDATE eta_alerts a
                SET status = 'acknowledged', acknowledged_at = now()
                FROM eta_targets t
                WHERE a.id = %s AND a.target_id = t.id
                  AND t.device_id = %s AND a.status = 'pending'
                RETURNING a.target_id
                """,
                (alert_id, device_id),
            )
        ).fetchone()
        if row:
            # Ціль виконала призначення. Без цього наступний цикл у тому ж
            # вікні створив би НОВИЙ алерт (аудит R-05) — а вимога власника
            # пряма: після ОК сповіщення більше не потрібне.
            await conn.execute(
                "UPDATE eta_targets SET is_active = false WHERE id = %s",
                (row["target_id"],),
            )
    return {"status": "acknowledged" if row else "already_closed"}


# --- Телеметрія (лише для адмін-пристроїв) --------------------------------


@router.get("/admin/telemetry")
async def admin_telemetry(x_device_id: str | None = Header(None)) -> dict:
    """Повний стан сервера.

    Доступ лише пристроям з позначкою `is_admin`: телеметрія розкриває
    внутрішній устрій — версії, обсяги, свіжість копій. Стороннім це не
    потрібно, а зловмиснику корисно.
    """
    device_id = await _device(x_device_id)

    async with get_pool().connection() as conn:
        row = await (
            await conn.execute("SELECT is_admin FROM devices WHERE id = %s", (device_id,))
        ).fetchone()
        if not row or not row["is_admin"]:
            raise HTTPException(status_code=403, detail="Потрібен адміністративний пристрій")

        return {
            "system": telemetry.system(),
            "network": telemetry.network(),
            "pipeline": await telemetry.pipeline(conn),
            "certificate": telemetry.certificate(),
            "backups": telemetry.backups(),
            "problems": await telemetry.health_alerts(conn),
        }
