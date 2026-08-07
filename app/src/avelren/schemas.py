"""Схеми запитів і відповідей публічного API."""

from pydantic import AwareDatetime, BaseModel, Field

from .alerts import THRESHOLDS


class DeviceIn(BaseModel):
    # FCM-токен зʼявляється не одразу після старту застосунку: реєстрацію
    # пристрою слід не відкладати, тож перший POST /devices дозволено без
    # токена, а токен доставляється пізніше через PUT /devices/token.
    fcm_token: str | None = Field(None, min_length=32, max_length=4096)
    platform: str = Field("android", pattern="^(android|ios)$")


class DeviceOut(BaseModel):
    """Відповідь на реєстрацію. `device_secret` віддається ЄДИНИЙ раз —
    клієнт зберігає його як облікові дані installation. Втратив — довелося б
    створювати нову installation з нуля."""

    device_id: str
    device_secret: str


class TokenIn(BaseModel):
    fcm_token: str = Field(..., min_length=32, max_length=4096)


class SubscriptionIn(BaseModel):
    checkpoint_id: int = Field(..., gt=0)
    threshold: int = Field(..., description=f"одне зі значень: {THRESHOLDS}")


class EtaTargetIn(BaseModel):
    checkpoint_id: int = Field(..., gt=0)
    # AwareDatetime відсіює naive-значення на рівні валідації Pydantic — раніше
    # такі проходили і падали в 500 при порівнянні з aware now() (аудит API-3).
    target_at: AwareDatetime = Field(..., description="цільовий момент вʼїзду, ISO 8601 з зоною")
    tolerance_seconds: int = Field(900, ge=60, le=6 * 3600)
