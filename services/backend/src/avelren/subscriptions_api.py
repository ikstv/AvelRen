"""Endpoints for subscriptions, targets, and acknowledgements.

**Authentication model.** Registration is anonymous: a device, not a person.
Each installation gets a `(device_id, device_secret)` pair. `device_id` is a
UUID, `device_secret` is 32 random bytes. The DB stores only the SHA-256 hex
digest of the secret, verified via `hmac.compare_digest` (constant-time). The
rationale for the digest choice (why not bcrypt) is in the migration
`007_device_secret.sql`.

State-changing requests (POST/PUT/DELETE, /ack, /admin) require BOTH headers:
`X-Device-Id` and `X-Device-Secret`. Knowing the UUID alone gives nothing — this
is exactly what closes AUTH-1 (audit): previously POST /devices returned an
existing device_id for a known FCM token, and a token is not a secret (it lives
on the client, in Google's logs, in crashes). POST /devices creates a NEW
installation only for an absent or unclaimed token. A claimed token returns a
conflict, preserving its owner and granting no access to their subscriptions.

Headers, not the URL: parameters settle in proxy logs and in history, headers
do not.
"""

import hashlib
import hmac
from datetime import UTC, datetime
from secrets import token_urlsafe
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from psycopg import AsyncConnection, DataError, OperationalError
from psycopg.errors import InvalidTextRepresentation, UniqueViolation

from . import cancels, telemetry
from .alerts import THRESHOLDS
from .db import get_pool
from .ratelimit import check as rate_check
from .schemas import DeviceIn, DeviceOut, EtaTargetIn, SubscriptionIn, TokenIn

router = APIRouter()

# 32 bytes of entropy — 43 url-safe base64 characters. Enough to make brute force
# infeasible even without a rate limit on /ack.
SECRET_BYTES = 32


def _hash_secret(secret: str) -> str:
    """SHA-256 hex digest.

    The rationale is in the migration 007_device_secret.sql: a 256-bit random
    secret makes bcrypt unnecessary (brute force is infeasible anyway), while
    bcrypt on every protected request is a ready-made CPU-DoS vector (NEW-AUTH-1).
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


async def _device(x_device_id: str | None, x_device_secret: str | None) -> str:
    """Two-factor verification of the installation credential.

    We separate errors correctly: an invalid UUID in the header — 400, the DB is
    down — 503, a wrong pair — 401. Before this fix (audit API-1) any DB failure
    read as a "bad device id" and the client could decide to re-register.

    Comparison via `hmac.compare_digest` (constant-time), not via
    `stored == given`: a timing attack on a byte-by-byte comparison is trivial.
    """
    if not x_device_id or not x_device_secret:
        raise HTTPException(
            status_code=401, detail="X-Device-Id and X-Device-Secret headers are required"
        )
    # The try wraps the ENTIRE `async with connection()` — including the UPDATE
    # last_seen and exiting the context manager (commit/close). Without this, a DB
    # failure between the SELECT and the UPDATE would go as an unhandled 500, not
    # a 503 (API-1).
    try:
        async with get_pool().connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT secret_hash FROM devices
                    WHERE id = %s AND secret_hash IS NOT NULL
                    FOR UPDATE
                    """,
                    (x_device_id,),
                )
            ).fetchone()

            if row is None or not hmac.compare_digest(
                row["secret_hash"], _hash_secret(x_device_secret)
            ):
                # Both a nonexistent id and a wrong secret lead here — we do not
                # disclose which part is wrong, so as not to give an oracle for
                # brute force.
                raise HTTPException(status_code=401, detail="Invalid device credentials")

            # We update last_seen only after a successful check — otherwise the
            # very fact of the update would be an "id exists" oracle. Throttled to
            # one hour: last_seen is needed only for the "active in a day"
            # indicator (is_active), so there is no point writing to devices on
            # EVERY authorized request — otherwise a regular GET turns into a write
            # and creates needless load on the DB (audit MED).
            await conn.execute(
                "UPDATE devices SET last_seen = now() "
                "WHERE id = %s AND last_seen < now() - INTERVAL '1 hour'",
                (x_device_id,),
            )
    except HTTPException:
        # Our own 400/401/503 — re-raise as is, do not map to 503.
        raise
    except (InvalidTextRepresentation, DataError):
        raise HTTPException(status_code=400, detail="Invalid X-Device-Id") from None
    except OperationalError as exc:
        raise HTTPException(status_code=503, detail="DB unavailable") from exc
    return x_device_id


@router.get("/thresholds")
async def thresholds(request: Request) -> dict:
    rate_check(request, "read")
    return {"thresholds": THRESHOLDS}


async def save_capabilities(conn, device_id, capabilities):
    from .schema_gate import assert_surge_schema

    exists = await (
        await conn.execute(

                "SELECT EXISTS(SELECT 1 FROM schema_migrations WHERE "
                "version='016_surge_monitor') AS present"

        )
    ).fetchone()
    if exists["present"]:
        await assert_surge_schema(conn)
        await conn.execute(
            "UPDATE devices SET notification_capabilities=%s WHERE id=%s", (capabilities, device_id)
        )


async def _lock_token_candidate(conn: AsyncConnection, token: str) -> None:
    """Один lock кандидата до row lock; чинний API statement_timeout обмежує очікування."""
    digest = hashlib.sha256(b"avelren-fcm-token-v1" + token.encode("utf-8")).digest()
    key = int.from_bytes(digest[:8], "big", signed=True)
    await conn.execute("SELECT pg_advisory_xact_lock(%s)", (key,))


async def _token_owner(conn: AsyncConnection, token: str) -> str | None:
    row = await (
        await conn.execute("SELECT id FROM devices WHERE fcm_token = %s", (token,))
    ).fetchone()
    return str(row["id"]) if row else None


def _token_conflict() -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "fcm_token_conflict"})


@router.post("/devices", status_code=201)
async def create_device(request: Request, body: DeviceIn) -> DeviceOut:
    """Нова installation; знання зайнятого токена не змінює попереднього власника."""
    rate_check(request, "write")
    secret = token_urlsafe(SECRET_BYTES)
    async with get_pool().connection() as conn:
        async with conn.transaction():
            if body.fcm_token:
                await _lock_token_candidate(conn, body.fcm_token)
                if await _token_owner(conn, body.fcm_token) is not None:
                    raise _token_conflict()
            row = await (
                await conn.execute(
                    """
                    INSERT INTO devices (fcm_token, platform, secret_hash)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (fcm_token) DO NOTHING
                    RETURNING id
                    """,
                    (body.fcm_token, body.platform, _hash_secret(secret)),
                )
            ).fetchone()
            # Остаточний захист від writer, який не бере advisory lock.
            if row is None:
                raise _token_conflict()
            await save_capabilities(conn, row["id"], body.notification_capabilities)
    # The secret is returned exactly once. Only the hash is in the DB —
    # recovery is impossible, only creating a new installation.
    return DeviceOut(device_id=str(row["id"]), device_secret=secret)


@router.put("/devices/token")
async def update_token(
    request: Request,
    body: TokenIn,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> dict:
    rate_check(request, "write")
    device_id = await _device(x_device_id, x_device_secret)
    # PostgreSQL приймає різні записи UUID; порівнюємо канонічну identity.
    device_id = str(UUID(device_id))
    async with get_pool().connection() as conn:
        async with conn.transaction():
            await _lock_token_candidate(conn, body.fcm_token)
            owner = await _token_owner(conn, body.fcm_token)
            if owner is not None and owner != device_id:
                raise _token_conflict()
            try:
                # Savepoint відновлює транзакцію до обробки race з зовнішнім writer.
                async with conn.transaction():
                    row = await (
                        await conn.execute(
                            "UPDATE devices SET fcm_token = %s, last_seen = now() WHERE id = %s "
                            "RETURNING id",
                            (body.fcm_token, device_id),
                        )
                    ).fetchone()
            except UniqueViolation as exc:
                if (
                    exc.diag.table_name == "devices"
                    and exc.diag.constraint_name == "devices_fcm_token_key"
                ):
                    raise _token_conflict() from None
                raise
            if row is None:
                raise HTTPException(status_code=401, detail="Invalid device credentials")
            await save_capabilities(conn, device_id, body.notification_capabilities)
    return {"status": "ok"}


# --- Feature #1: thresholds ------------------------------------------------


@router.get("/subscriptions")
async def list_subscriptions(
    request: Request,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> list[dict]:
    rate_check(request, "read")
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
        raise HTTPException(status_code=422, detail=f"Threshold must be one of {THRESHOLDS}")
    device_id = await _device(x_device_id, x_device_secret)

    async with get_pool().connection() as conn:
        exists = await (
            await conn.execute("SELECT 1 FROM checkpoints WHERE id = %s", (body.checkpoint_id,))
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="Checkpoint not found")

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
    request: Request,
    subscription_id: int,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> None:
    rate_check(request, "write")
    device_id = await _device(x_device_id, x_device_secret)
    async with get_pool().connection() as conn:
        async with conn.transaction():
            # Enqueue the cancels BEFORE the delete, in one transaction:
            # otherwise the cascade delete would remove the alert rows, and the
            # phone would be left with an ongoing notification that cannot be
            # closed (audit A-02).
            await conn.execute(
                """
                INSERT INTO notification_cancels (kind, alert_id, device_id)
                SELECT 'threshold', a.id, s.device_id
                FROM alerts a
                JOIN subscriptions s ON s.id = a.subscription_id
                WHERE a.subscription_id = %s AND s.device_id = %s
                  AND a.status = 'pending'
                ON CONFLICT (kind, alert_id) DO NOTHING
                """,
                (subscription_id, device_id),
            )
            row = await (
                await conn.execute(
                    "DELETE FROM subscriptions WHERE id = %s AND device_id = %s RETURNING id",
                    (subscription_id, device_id),
                )
            ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Subscription not found")


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(
    request: Request,
    alert_id: int,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> dict:
    """The "OK" button dismisses the current delivery until the next resend."""
    rate_check(request, "write")
    device_id = await _device(x_device_id, x_device_secret)
    async with get_pool().connection() as conn:
        row = await (
            await conn.execute(
                """
                UPDATE alerts a
                SET acknowledged_at = CASE
                    WHEN a.acknowledged_at IS NULL OR a.last_sent_at > a.acknowledged_at
                    THEN GREATEST(now(), a.last_sent_at)
                    ELSE a.acknowledged_at
                END
                FROM subscriptions s
                WHERE a.id = %s AND a.subscription_id = s.id
                  AND s.device_id = %s AND a.status = 'pending'
                RETURNING a.id
                """,
                (alert_id, device_id),
            )
        ).fetchone()
    # A repeated acknowledgement is not an error: the user may have tapped twice,
    # and the app may retry the request after losing the network.
    return {"status": "acknowledged" if row else "already_closed"}


# --- Reconciliation of active notifications (A-02) -------------------------


@router.get("/active-alerts")
async def active_alerts(
    request: Request,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> dict[str, list[int]]:
    """Canonical list of the device's active (pending) alerts.

    On returning to foreground, the client reconciles the shown ongoing
    notifications against this list and dismisses those not present here — a
    convergence guarantee when the cancel-push was lost (Doze/offline/force-stop).
    The server remains the single source of truth; the phone only brings its
    local state in line with it.
    """
    rate_check(request, "read")
    device_id = await _device(x_device_id, x_device_secret)
    async with get_pool().connection() as conn:
        return await cancels.active_alert_keys(conn, device_id)


# --- Feature #2: target entry time -----------------------------------------


@router.get("/eta-targets")
async def list_eta_targets(
    request: Request,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> list[dict]:
    rate_check(request, "read")
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
                WHERE t.device_id = %s AND t.is_active
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
        raise HTTPException(status_code=422, detail="The target time must be in the future")
    device_id = await _device(x_device_id, x_device_secret)

    async with get_pool().connection() as conn:
        exists = await (
            await conn.execute("SELECT 1 FROM checkpoints WHERE id = %s", (body.checkpoint_id,))
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="Checkpoint not found")

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
    request: Request,
    target_id: int,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> None:
    rate_check(request, "write")
    device_id = await _device(x_device_id, x_device_secret)
    async with get_pool().connection() as conn:
        async with conn.transaction():
            # Mirror of delete_subscription: enqueue the cancels BEFORE the
            # cascade delete, in one transaction, scoped by ownership (audit A-02).
            await conn.execute(
                """
                INSERT INTO notification_cancels (kind, alert_id, device_id)
                SELECT 'eta', a.id, t.device_id
                FROM eta_alerts a
                JOIN eta_targets t ON t.id = a.target_id
                WHERE a.target_id = %s AND t.device_id = %s
                  AND a.status = 'pending'
                ON CONFLICT (kind, alert_id) DO NOTHING
                """,
                (target_id, device_id),
            )
            row = await (
                await conn.execute(
                    "DELETE FROM eta_targets WHERE id = %s AND device_id = %s RETURNING id",
                    (target_id, device_id),
                )
            ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Target not found")


@router.post("/eta-alerts/{alert_id}/ack")
async def acknowledge_eta_alert(
    request: Request,
    alert_id: int,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> dict:
    rate_check(request, "write")
    device_id = await _device(x_device_id, x_device_secret)
    async with get_pool().connection() as conn:
        row = await (
            await conn.execute(
                """
                UPDATE eta_alerts a
                SET acknowledged_at = CASE
                    WHEN a.acknowledged_at IS NULL OR a.last_sent_at > a.acknowledged_at
                    THEN GREATEST(now(), a.last_sent_at)
                    ELSE a.acknowledged_at
                END
                FROM eta_targets t
                WHERE a.id = %s AND a.target_id = t.id
                  AND t.device_id = %s AND a.status = 'pending'
                RETURNING a.target_id
                """,
                (alert_id, device_id),
            )
        ).fetchone()
    return {"status": "acknowledged" if row else "already_closed"}


# --- Public aggregate; no installation identifiers are returned -----------


@router.get("/active-devices")
async def active_devices(request: Request) -> dict:
    """Number of device records still retained on our server."""
    rate_check(request, "read")
    async with get_pool().connection() as conn:
        count = await (await conn.execute("SELECT count(*) AS total FROM devices")).fetchone()
    return {"active_devices": count["total"], "retention_days": 90}


# --- Telemetry (admin devices only) ----------------------------------------


@router.get("/admin/telemetry")
async def admin_telemetry(
    request: Request,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> dict:
    """Full server state.

    Access only for devices marked `is_admin`: telemetry reveals the internal
    workings — versions, volumes, backup freshness. Outsiders do not need it, and
    an attacker finds it useful.
    """
    # The "write" bucket, not "read": telemetry.pipeline counts rows across
    # observations, a sequential scan over millions of them. A 300/min read
    # allowance would be a permission, not a limit.
    rate_check(request, "write")
    device_id = await _device(x_device_id, x_device_secret)

    async with get_pool().connection() as conn:
        row = await (
            await conn.execute("SELECT is_admin FROM devices WHERE id = %s", (device_id,))
        ).fetchone()
        if not row or not row["is_admin"]:
            raise HTTPException(status_code=403, detail="An administrative device is required")

        system = telemetry.system()
        problems = await telemetry.health_alerts(conn)

        # A stale host snapshot is surfaced into the same problem list:
        # otherwise a failure of the telemetry timer looks like a healthy server
        # with zeros.
        stale = telemetry.snapshot_problem(system)
        if stale is not None:
            problems = [stale, *problems]

        # Extension (PR-B): the new blocks are backward-compatible, NO existing
        # field is removed or renamed — an old Android will keep parsing this
        # response unchanged.
        return {
            "system": system,
            "network": telemetry.network(),
            "inodes": telemetry.inodes(),
            "docker": telemetry.docker(),
            "services": telemetry.services(),
            "pipeline": await telemetry.pipeline(conn),
            "last_collector_run": await telemetry.last_collector_run(conn),
            "last_collector_success": await telemetry.last_collector_success(conn),
            "upstream": telemetry.upstream(),
            "certificate": telemetry.certificate(),
            "backups": telemetry.backups(),
            "version": await telemetry.version(conn),
            "problems": problems,
        }
