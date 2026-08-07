"""Ендпоінти підписок, цілей і підтверджень.

**Модель автентифікації.** Реєстрація анонімна: пристрій, а не людина. Кожна
installation отримує пару `(device_id, device_secret)`. `device_id` — UUID,
`device_secret` — 32 випадкові байти. У БД зберігається лише SHA-256 hex
digest секрета, перевірка через `hmac.compare_digest` (constant-time).
Обґрунтування вибору дайджеста (чому не bcrypt) — у міграції
`007_device_secret.sql`.

Стан-змінні запити (POST/PUT/DELETE, /ack, /admin) вимагають ОБОХ заголовків:
`X-Device-Id` і `X-Device-Secret`. Знання лише UUID саме по собі нічого не дає
— саме це закриває AUTH-1 (аудит): раніше POST /devices повертав існуючий
device_id за відомим FCM-токеном, а токен — не секрет (живе на клієнті, в
логах Google, у крешах). Тепер POST /devices завжди створює НОВУ installation
і повертає нову пару; знання чужого FCM-токена не дає доступу до чужих
підписок.

Заголовки, а не URL: параметри осідають у логах проксі та в історії, заголовки
— ні.
"""

import hashlib
import hmac
from datetime import UTC, datetime
from secrets import token_urlsafe

from fastapi import APIRouter, Header, HTTPException, Request
from psycopg import DataError, OperationalError
from psycopg.errors import InvalidTextRepresentation

from . import telemetry
from .alerts import THRESHOLDS
from .db import get_pool
from .ratelimit import check as rate_check
from .schemas import DeviceIn, DeviceOut, EtaTargetIn, SubscriptionIn, TokenIn

router = APIRouter()

# 32 байти ентропії — 43 символи url-safe base64. Достатньо, щоб перебір був
# нереальний навіть без rate limit на /ack.
SECRET_BYTES = 32


def _hash_secret(secret: str) -> str:
    """SHA-256 hex digest.

    Пояснення вибору — в міграції 007_device_secret.sql: 256-бітний випадковий
    секрет робить bcrypt зайвим (перебір усе одно нереальний), а bcrypt на
    кожному захищеному запиті — це готовий CPU-DoS вектор (NEW-AUTH-1).
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


async def _device(x_device_id: str | None, x_device_secret: str | None) -> str:
    """Двофакторна перевірка installation credential.

    Розділяємо помилки коректно: невалідний UUID у заголовку — 400, БД лежить
    — 503, невірна пара — 401. До цього виправлення (аудит API-1) будь-яке
    падіння БД читалося як «поганий device id» і клієнт міг вирішити
    перереєструватися.

    Порівняння через `hmac.compare_digest` (constant-time), не через
    `stored == given`: часовий attack на побайтне порівняння тривіальний.
    """
    if not x_device_id or not x_device_secret:
        raise HTTPException(
            status_code=401, detail="Потрібні заголовки X-Device-Id і X-Device-Secret"
        )
    # try огортає ВЕСЬ `async with connection()` — включно з UPDATE last_seen
    # і виходом з context manager (commit/close). Без цього падіння БД між
    # SELECT і UPDATE піде як необроблений 500, а не 503 (API-1).
    try:
        async with get_pool().connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT secret_hash FROM devices
                    WHERE id = %s AND secret_hash IS NOT NULL
                    """,
                    (x_device_id,),
                )
            ).fetchone()

            if row is None or not hmac.compare_digest(
                row["secret_hash"], _hash_secret(x_device_secret)
            ):
                # І неіснуючий id, і невірний secret ведуть сюди — не
                # розголошуємо, яка саме частина неправильна, щоб не давати
                # оракул для перебору.
                raise HTTPException(
                    status_code=401, detail="Невірні облікові дані пристрою"
                )

            # last_seen оновлюємо лише після успішної перевірки — інакше сам
            # факт оновлення був би оракулом «id існує».
            await conn.execute(
                "UPDATE devices SET last_seen = now() WHERE id = %s", (x_device_id,)
            )
    except HTTPException:
        # Наші власні 400/401/503 — прокидаємо як є, не мапимо на 503.
        raise
    except (InvalidTextRepresentation, DataError):
        raise HTTPException(status_code=400, detail="Некоректний X-Device-Id") from None
    except OperationalError as exc:
        raise HTTPException(status_code=503, detail="БД недоступна") from exc
    return x_device_id


@router.get("/thresholds")
async def thresholds() -> dict:
    return {"thresholds": THRESHOLDS}


@router.post("/devices", status_code=201)
async def create_device(request: Request, body: DeviceIn) -> DeviceOut:
    """Створення installation.

    На відміну від попередньої версії, при співпадінні FCM-токена ми НЕ
    повертаємо id вже існуючого пристрою — саме це було шляхом AUTH-1. Токен
    переноситься на нову installation (стара залишається сиротою і буде
    прибрана retention'ом), а клієнт отримує свіжу пару `(id, secret)`.
    """
    rate_check(request, "write")
    secret = token_urlsafe(SECRET_BYTES)
    async with get_pool().connection() as conn:
        async with conn.transaction():
            # UNIQUE(fcm_token) не дасть залишити токен на двох рядках. Спершу
            # знімаємо його зі старої installation (якщо був), потім вставляємо
            # нову з цим самим токеном.
            if body.fcm_token:
                await conn.execute(
                    "UPDATE devices SET fcm_token = NULL WHERE fcm_token = %s",
                    (body.fcm_token,),
                )
            row = await (
                await conn.execute(
                    """
                    INSERT INTO devices (fcm_token, platform, secret_hash)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (body.fcm_token, body.platform, _hash_secret(secret)),
                )
            ).fetchone()
    # Секрет віддається один-єдиний раз. У БД лежить лише хеш — відновити
    # неможливо, тільки створити нову installation.
    return DeviceOut(device_id=str(row["id"]), device_secret=secret)


@router.put("/devices/token")
async def update_token(
    body: TokenIn,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> dict:
    device_id = await _device(x_device_id, x_device_secret)
    async with get_pool().connection() as conn:
        async with conn.transaction():
            # Той самий токен може «переходити» з осиротілої installation:
            # знімаємо, щоб не порушити UNIQUE(fcm_token).
            await conn.execute(
                "UPDATE devices SET fcm_token = NULL WHERE fcm_token = %s AND id != %s",
                (body.fcm_token, device_id),
            )
            await conn.execute(
                "UPDATE devices SET fcm_token = %s, last_seen = now() WHERE id = %s",
                (body.fcm_token, device_id),
            )
    return {"status": "ok"}


# --- Функція №1: пороги ---------------------------------------------------


@router.get("/subscriptions")
async def list_subscriptions(
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> list[dict]:
    device_id = await _device(x_device_id, x_device_secret)
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
    request: Request,
    body: SubscriptionIn,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> dict:
    rate_check(request, "write")
    if body.threshold not in THRESHOLDS:
        raise HTTPException(status_code=422, detail=f"Поріг має бути одним із {THRESHOLDS}")
    device_id = await _device(x_device_id, x_device_secret)

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
async def delete_subscription(
    subscription_id: int,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> None:
    device_id = await _device(x_device_id, x_device_secret)
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
async def acknowledge_alert(
    alert_id: int,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> dict:
    """Кнопка «ОК». Після неї повтори припиняються назавжди."""
    device_id = await _device(x_device_id, x_device_secret)
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


# --- Функція №2: цільовий час вʼїзду --------------------------------------


@router.get("/eta-targets")
async def list_eta_targets(
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> list[dict]:
    device_id = await _device(x_device_id, x_device_secret)
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
    request: Request,
    body: EtaTargetIn,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> dict:
    rate_check(request, "write")
    if body.target_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="Цільовий час має бути в майбутньому")
    device_id = await _device(x_device_id, x_device_secret)

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
async def delete_eta_target(
    target_id: int,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> None:
    device_id = await _device(x_device_id, x_device_secret)
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
async def acknowledge_eta_alert(
    alert_id: int,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> dict:
    device_id = await _device(x_device_id, x_device_secret)
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
async def admin_telemetry(
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> dict:
    """Повний стан сервера.

    Доступ лише пристроям з позначкою `is_admin`: телеметрія розкриває
    внутрішній устрій — версії, обсяги, свіжість копій. Стороннім це не
    потрібно, а зловмиснику корисно.
    """
    device_id = await _device(x_device_id, x_device_secret)

    async with get_pool().connection() as conn:
        row = await (
            await conn.execute("SELECT is_admin FROM devices WHERE id = %s", (device_id,))
        ).fetchone()
        if not row or not row["is_admin"]:
            raise HTTPException(status_code=403, detail="Потрібен адміністративний пристрій")

        system = telemetry.system()
        problems = await telemetry.health_alerts(conn)

        # Протухлий host-snapshot підіймаємо в той самий список проблем:
        # інакше збій telemetry-таймера виглядає як здоровий сервер із нулями.
        stale = telemetry.snapshot_problem(system)
        if stale is not None:
            problems = [stale, *problems]

        return {
            "system": system,
            "network": telemetry.network(),
            "pipeline": await telemetry.pipeline(conn),
            "certificate": telemetry.certificate(),
            "backups": telemetry.backups(),
            "problems": problems,
        }
