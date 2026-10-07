"""Вузька нормалізація публічних показників ресурсів."""
from datetime import UTC, datetime


def resource_status(used: object, total: object, measured_at: object,
                    now: datetime, max_age_seconds: int,
                    allow_overage: bool = False) -> dict:
    unavailable = {"used_bytes": None, "total_bytes": None,
                   "measured_at": None, "stale": True}
    if (type(used) is not int or type(total) is not int
            or not 0 <= used < 2**63 or not 0 < total < 2**63
            or (not allow_overage and used > total)):
        return unavailable
    try:
        if not isinstance(measured_at, str):
            return unavailable
        measured = datetime.fromisoformat(measured_at.replace("Z", "+00:00"))
        if measured.tzinfo is None or measured.utcoffset() is None:
            return unavailable
        stamp = measured.astimezone(UTC).isoformat().replace("+00:00", "Z")
        age = (now - measured).total_seconds()
    except (ValueError, OverflowError, TypeError):
        return unavailable
    if not 0 <= age <= max_age_seconds:
        return unavailable | {"measured_at": stamp}
    return {"used_bytes": used, "total_bytes": total,
            "measured_at": stamp, "stale": False}
