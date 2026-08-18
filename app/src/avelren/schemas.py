"""Request and response schemas for the public API."""

from pydantic import AwareDatetime, BaseModel, Field

from .alerts import THRESHOLDS


class DeviceIn(BaseModel):
    # The FCM token does not appear right after app startup: device
    # registration should not be delayed, so the first POST /devices is allowed
    # without a token, and the token is delivered later via PUT /devices/token.
    fcm_token: str | None = Field(None, min_length=32, max_length=4096)
    platform: str = Field("android", pattern="^(android|ios)$")


class DeviceOut(BaseModel):
    """Registration response. `device_secret` is returned ONLY once — the
    client stores it as the installation credentials. Lose it and you would
    have to create a new installation from scratch."""

    device_id: str
    device_secret: str


class TokenIn(BaseModel):
    fcm_token: str = Field(..., min_length=32, max_length=4096)


class SubscriptionIn(BaseModel):
    checkpoint_id: int = Field(..., gt=0)
    threshold: int = Field(..., description=f"one of: {THRESHOLDS}")


class EtaTargetIn(BaseModel):
    checkpoint_id: int = Field(..., gt=0)
    # AwareDatetime filters out naive values at Pydantic validation time —
    # previously they passed and crashed with a 500 when compared to an aware
    # now() (audit API-3).
    target_at: AwareDatetime = Field(..., description="target entry moment, ISO 8601 with timezone")
    tolerance_seconds: int = Field(900, ge=60, le=6 * 3600)
