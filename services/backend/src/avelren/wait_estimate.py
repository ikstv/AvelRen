"""Канонічне читання оцінки та виміряного ETA, без прогнозних значень."""

from datetime import datetime, timedelta


def usable_wait_seconds(seconds: int, status: str) -> int | None:
    """Старий нуль неоднозначний; лише reported підтверджує справжній нуль."""
    if status == "reported" and seconds >= 0:
        return seconds
    if status == "legacy_unknown" and seconds > 0:
        return seconds
    return None


def measured_wait(at: datetime, seconds: int, status: str, is_paused: bool) -> dict:
    value = usable_wait_seconds(seconds, status)
    eta = None
    if value is not None and not (is_paused and value == 0):
        eta = at + timedelta(seconds=value)
    return {"status": status, "seconds": value, "entry_eta": eta}
