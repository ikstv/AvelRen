"""Схеми запитів і відповідей публічного API."""

from datetime import datetime

from pydantic import BaseModel, Field

from .alerts import THRESHOLDS


class DeviceIn(BaseModel):
    fcm_token: str | None = None
    platform: str = "android"


class DeviceOut(BaseModel):
    device_id: str


class TokenIn(BaseModel):
    fcm_token: str


class SubscriptionIn(BaseModel):
    checkpoint_id: int
    threshold: int = Field(..., description=f"одне зі значень: {THRESHOLDS}")


class EtaTargetIn(BaseModel):
    checkpoint_id: int
    target_at: datetime = Field(..., description="цільовий момент в'їзду, ISO 8601 з зоною")
    tolerance_seconds: int = Field(900, ge=60, le=6 * 3600)
