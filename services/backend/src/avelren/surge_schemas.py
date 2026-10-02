"""Новий прогноз явно відокремлений від вимірювання та валових реєстрацій."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SurgeSubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    forecast_enabled: bool = True
    fact_enabled: bool = True


class SurgeStatusOut(BaseModel):
    checkpoint_id: int
    status: Literal["disabled", "unavailable", "no_signal", "risk", "started"]
    reason: str | None = None
    issued_at: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    expires_at: datetime | None = None
    model_version: str | None = None
    growth_5m: int | None = None
    experimental: bool = True
    forecast_supported: bool
