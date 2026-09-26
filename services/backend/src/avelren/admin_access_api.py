"""Approval-gated admin entry. Installation authentication is not PIN authentication."""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field, SecretStr

from .admin_pin import MAX_ATTEMPTS, evaluate_attempt, verify_pin
from .db import get_pool
from .ratelimit import check as rate_check
from .subscriptions_api import _device

router = APIRouter(prefix="/admin/access")


class PinIn(BaseModel):
    # A secret field avoids echoing its value in repr/logging.
    pin: SecretStr = Field(min_length=1, max_length=128)


class AccessOut(BaseModel):
    state: str
    attempts_remaining: int = 0
    locked_until: datetime | None = None


async def access(device_id: str, pin: str | None = None) -> AccessOut:
    async with get_pool().connection() as conn:
        async with conn.transaction():
            # Feature migrations are optional so older deployed schemas stay usable.
            installed = await (await conn.execute(
                "SELECT version FROM schema_migrations "
                "WHERE version IN ('013_admin_installation_lock', '014_admin_pin_rebind')"
            )).fetchall()
            versions = {row["version"] for row in installed}
            if "013_admin_installation_lock" not in versions:
                return AccessOut(state="unavailable")
            can_rebind = "014_admin_pin_rebind" in versions
            row = await (await conn.execute(
                "SELECT approved_device_id, pin_hash, failures, locked_until "
                "FROM admin_access WHERE singleton FOR UPDATE"
            )).fetchone()
            if not row or not row["pin_hash"]:
                return AccessOut(state="unavailable")
            device = await (await conn.execute(
                "SELECT admin_blocked_until, fcm_token "
                "FROM devices WHERE id=%s FOR UPDATE", (device_id,),
            )).fetchone()
            if device is None:
                return AccessOut(state="unavailable")
            # Read time after both locks, so an attempt has one consistent deadline.
            now = (await (await conn.execute("SELECT clock_timestamp() AS now")).fetchone())["now"]
            installation_lock = device["admin_blocked_until"]
            if installation_lock is not None and installation_lock > now:
                return AccessOut(state="blocked", locked_until=installation_lock)

            approved = str(row["approved_device_id"]) == device_id
            if not approved and not can_rebind:
                # An older schema must not grant a foreign installation PIN entry.
                if pin is None:
                    return AccessOut(state="awaiting_approval")
                installation_lock = await (await conn.execute(
                    "UPDATE devices SET admin_blocked_until=clock_timestamp()+interval '24 hours' "
                    "WHERE id=%s RETURNING admin_blocked_until", (device_id,),
                )).fetchone()
                return AccessOut(
                    state="blocked", locked_until=installation_lock["admin_blocked_until"],
                )

            locked = row["locked_until"]
            if locked is not None and locked > now:
                return AccessOut(state="blocked", locked_until=locked)
            if device["fcm_token"] is None:
                return AccessOut(state="unavailable")
            failures = 0 if locked is not None else row["failures"]
            if pin is None:
                return AccessOut(state="ready", attempts_remaining=MAX_ATTEMPTS - failures)

            matches = await asyncio.to_thread(verify_pin, pin, row["pin_hash"])
            result = evaluate_attempt(failures, locked, now, matches)
            await conn.execute(
                "UPDATE admin_access SET failures=%s, locked_until=%s WHERE singleton",
                (result.failures, result.locked_until),
            )
            if result.state == "authorized":
                if can_rebind:
                    await conn.execute("SELECT activate_admin_after_pin(%s::uuid)", (device_id,))
                else:
                    await conn.execute("SELECT activate_approved_admin(%s::uuid)", (device_id,))
            # Returning normally commits wrong attempts too; an HTTPException would roll back.
            return AccessOut(
                state=result.state, attempts_remaining=result.remaining,
                locked_until=result.locked_until,
            )


@router.get("", response_model=AccessOut)
async def status(
    request: Request,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> AccessOut:
    rate_check(request, "read")
    return await access(await _device(x_device_id, x_device_secret))


@router.post("", response_model=AccessOut)
async def unlock(
    request: Request, body: PinIn,
    x_device_id: str | None = Header(None),
    x_device_secret: str | None = Header(None),
) -> AccessOut:
    rate_check(request, "write")
    return await access(await _device(x_device_id, x_device_secret), body.pin.get_secret_value())
