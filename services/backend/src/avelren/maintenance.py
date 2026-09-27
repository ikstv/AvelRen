"""Публічне вікно планових робіт, без доступу до БД чи первинного джерела."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

MAINTENANCE_PATH = Path(os.environ.get("AVELREN_MAINTENANCE_FILE", "/telemetry/maintenance.json"))
BOOT_ID_PATH = Path(os.environ.get("AVELREN_BOOT_ID_FILE", "/proc/sys/kernel/random/boot_id"))


def read_window(now: datetime) -> dict[str, str] | None:
    try:
        with MAINTENANCE_PATH.open(encoding="utf-8") as source:
            payload = json.loads(source.read(4097))
        if not isinstance(payload, dict):
            return None
        start = datetime.fromisoformat(payload["starts_at"])
        end = datetime.fromisoformat(payload["ends_at"])
        if start.tzinfo is None or end.tzinfo is None:
            return None
        if not 0 < (end - start).total_seconds() <= 900:
            return None
        if end <= now or start > now + timedelta(days=1):
            return None
        public = {
            "starts_at": start.astimezone(UTC).isoformat(),
            "ends_at": end.astimezone(UTC).isoformat(),
        }
        restart_text = payload.get("restarts_at")
        published_boot_id = payload.get("boot_id")
        if restart_text is None and published_boot_id is None:
            return public  # Backward compatibility with an ordinary maintenance window.
        if not isinstance(restart_text, str) or not isinstance(published_boot_id, str):
            return None
        restart = datetime.fromisoformat(restart_text)
        if restart.tzinfo is None or not start < restart < end:
            return None
        if not 0 < len(published_boot_id) <= 128:
            return None
        current_boot_id = BOOT_ID_PATH.read_text(encoding="utf-8").strip()
        if not current_boot_id:
            return None
        # A different boot identity proves that the planned restart completed.
        # The stale file may remain on persistent storage, but clients should
        # immediately return to ONLINE as soon as the new API process answers.
        if current_boot_id != published_boot_id:
            return None
        public["restarts_at"] = restart.astimezone(UTC).isoformat()
        return public
    except (OSError, ValueError, TypeError, KeyError):
        return None
