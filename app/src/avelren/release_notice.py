"""Backward-compatible release notices; publication gating belongs to the sender."""

import re


def release_payload(version_name: str, version_code: int) -> dict[str, str]:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version_name):
        raise ValueError("Expected a release version such as 0.1.1")
    if type(version_code) is not int or not 0 < version_code <= 2_100_000_000:
        raise ValueError("Invalid Android version code")
    return {
        # 0.1.0 recognizes health information, but not a new top-level message type.
        "type": "health",
        "subtype": "app_update",
        "version_code": str(version_code),
        "version_name": version_name,
        "title": "Доступна нова версія AvelRen",
        "body": (
            f"Вийшла версія {version_name}. Оновіть застосунок у Google Play, "
            "щоб отримати нові можливості та виправлення."
        ),
    }
